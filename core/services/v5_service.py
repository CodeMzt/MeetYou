from __future__ import annotations

import hashlib
import re
from uuid import uuid4
from typing import Any

from core.artifacts import LocalArtifactStore
from core.db.base import utcnow
from core.db.models import ConversationCheckpoint, Message
from core.db.repositories import (
    ArtifactRepository,
    ConversationCheckpointRepository,
    MessageRepository,
    ProjectRepository,
    ProjectSourceRepository,
    ResearchTaskRepository,
    SessionRepository,
    ThreadBranchRepository,
    ThreadRepository,
)
from core.db.repositories.v5 import last_message_for_thread, update_thread_version_pointer
from core.services.base import ServiceBase


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _public_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


_CITATION_RE = re.compile(r"(?<!!)\[(\d+)\]")
_RESEARCH_TERMINAL_STATUSES = {"cancelled", "completed", "failed"}
_RESEARCH_ALLOWED_STATUSES = {"planned", "approved", "running", *_RESEARCH_TERMINAL_STATUSES}


class ResearchTaskCitationError(ValueError):
    def __init__(self, *, missing_source_ids: list[str], citation_ids: list[str], evidence_source_ids: list[str]) -> None:
        self.missing_source_ids = missing_source_ids
        self.citation_ids = citation_ids
        self.evidence_source_ids = evidence_source_ids
        missing = ", ".join(missing_source_ids)
        super().__init__(f"research report cites source ids not present in evidence_ledger: {missing}")


class ResearchTaskStateError(ValueError):
    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _evidence_source_ids(evidence_ledger: list[dict[str, Any]] | None) -> list[str]:
    ids: list[str] = []
    for entry in evidence_ledger or []:
        if not isinstance(entry, dict):
            continue
        value = entry.get("source_id", entry.get("id", entry.get("evidence_id", "")))
        normalized = str(value or "").strip()
        if normalized and normalized not in ids:
            ids.append(normalized)
    return ids


class ProjectService(ServiceBase):
    def create_project(
        self,
        *,
        principal_id,
        workspace_id=None,
        title: str = "",
        description: str = "",
        instructions: str = "",
        memory_scope: dict | None = None,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return ProjectRepository(session).create(
                project_id=_public_id("prj"),
                principal_id=principal_id,
                workspace_id=workspace_id,
                title=str(title or "").strip() or "未命名项目",
                description=str(description or "").strip(),
                instructions=str(instructions or "").strip(),
                memory_scope=memory_scope,
                metadata=metadata,
            )

    def list_projects(self, *, principal_id, workspace_id=None, include_archived: bool = False, limit: int = 100):
        with self.session_scope() as session:
            return ProjectRepository(session).list_for_principal(
                principal_id=principal_id,
                workspace_id=workspace_id,
                include_archived=include_archived,
                limit=limit,
            )

    def get_by_project_id(self, project_id: str):
        with self.session_scope() as session:
            return ProjectRepository(session).get_by_project_id(project_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return ProjectRepository(session).get_by_id(row_id)

    def update_project(self, *, project_id: str, fields: dict[str, Any]):
        with self.session_scope() as session:
            return ProjectRepository(session).update(project_id=project_id, fields=fields)

    def archive_project(self, *, project_id: str):
        return self.update_project(project_id=project_id, fields={"status": "archived"})

    def add_source(
        self,
        *,
        project_id: str,
        principal_id,
        source_type: str = "note",
        title: str = "",
        content: str = "",
        content_type: str = "text",
        metadata: dict | None = None,
    ):
        text = str(content or "").strip()
        if not text:
            raise ValueError("content is required")
        with self.session_scope() as session:
            project = ProjectRepository(session).get_by_project_id(project_id)
            if project is None:
                return None
            return ProjectSourceRepository(session).create(
                source_id=_public_id("src"),
                project_id=project.id,
                principal_id=principal_id,
                source_type=str(source_type or "note").strip() or "note",
                title=str(title or "").strip() or "项目源",
                content=text,
                content_type=str(content_type or "text").strip() or "text",
                checksum=_sha256_text(text),
                metadata=metadata,
            )

    def save_message_source(
        self,
        *,
        project_id: str,
        principal_id,
        message_id: str,
        title: str = "",
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            project = ProjectRepository(session).get_by_project_id(project_id)
            message = MessageRepository(session).get_by_message_id(message_id)
            if project is None or message is None:
                return None
            thread = ThreadRepository(session).get_by_id(message.thread_id)
            content = str(getattr(message, "content", "") or "")
            return ProjectSourceRepository(session).create(
                source_id=_public_id("src"),
                project_id=project.id,
                principal_id=principal_id,
                source_type="message_snapshot",
                title=str(title or "").strip() or f"消息快照 {str(message.message_id or '')[-8:]}",
                content=content,
                content_type=str(getattr(message, "content_type", "") or "text"),
                source_thread_id=getattr(thread, "id", None),
                source_message_id=message.id,
                checksum=_sha256_text(content),
                metadata={
                    **dict(metadata or {}),
                    "source_message_id": message.message_id,
                    "source_thread_id": str(getattr(thread, "thread_id", "") or ""),
                    "role": str(getattr(message, "role", "") or ""),
                },
            )

    def list_sources(self, *, project_id: str, include_archived: bool = False, limit: int = 100):
        with self.session_scope() as session:
            project = ProjectRepository(session).get_by_project_id(project_id)
            if project is None:
                return None
            return ProjectSourceRepository(session).list_for_project(
                project_id=project.id,
                include_archived=include_archived,
                limit=limit,
            )

    def get_source(self, *, project_id: str, source_id: str):
        with self.session_scope() as session:
            project = ProjectRepository(session).get_by_project_id(project_id)
            source = ProjectSourceRepository(session).get_by_source_id(source_id)
            if project is None or source is None or source.project_id != project.id:
                return None
            return source

    def archive_source(self, *, project_id: str, source_id: str):
        with self.session_scope() as session:
            project = ProjectRepository(session).get_by_project_id(project_id)
            repo = ProjectSourceRepository(session)
            source = repo.get_by_source_id(source_id)
            if project is None or source is None or source.project_id != project.id:
                return None
            return repo.update_status(source_id=source_id, status="archived")


class ArtifactService(ServiceBase):
    def __init__(self, session_factory, *, store: LocalArtifactStore | None = None):
        super().__init__(session_factory)
        self.store = store or LocalArtifactStore()

    def create_bytes_artifact(
        self,
        *,
        principal_id,
        data: bytes | bytearray | memoryview,
        filename: str,
        project_id=None,
        thread_id=None,
        created_by_run_id=None,
        artifact_type: str = "document",
        content_type: str = "application/octet-stream",
        metadata: dict | None = None,
    ):
        artifact_id = _public_id("art")
        stored = self.store.put_bytes(
            artifact_id=artifact_id,
            data=bytes(data or b""),
            filename=filename,
            content_type=content_type,
        )
        with self.session_scope() as session:
            return ArtifactRepository(session).create(
                artifact_id=artifact_id,
                principal_id=principal_id,
                project_id=project_id,
                thread_id=thread_id,
                created_by_run_id=created_by_run_id,
                artifact_type=artifact_type,
                storage_backend=stored.storage_backend,
                storage_key=stored.storage_key,
                filename=stored.filename,
                content_type=stored.content_type,
                byte_size=stored.byte_size,
                checksum=stored.checksum,
                metadata=metadata,
            )

    def create_text_artifact(
        self,
        *,
        principal_id,
        text: str,
        filename: str,
        project_id=None,
        thread_id=None,
        created_by_run_id=None,
        artifact_type: str = "report",
        content_type: str = "text/markdown; charset=utf-8",
        metadata: dict | None = None,
    ):
        artifact_id = _public_id("art")
        stored = self.store.put_text(
            artifact_id=artifact_id,
            text=text,
            filename=filename,
            content_type=content_type,
        )
        with self.session_scope() as session:
            return ArtifactRepository(session).create(
                artifact_id=artifact_id,
                principal_id=principal_id,
                project_id=project_id,
                thread_id=thread_id,
                created_by_run_id=created_by_run_id,
                artifact_type=artifact_type,
                storage_backend=stored.storage_backend,
                storage_key=stored.storage_key,
                filename=stored.filename,
                content_type=stored.content_type,
                byte_size=stored.byte_size,
                checksum=stored.checksum,
                metadata=metadata,
            )

    def get_by_artifact_id(self, artifact_id: str):
        with self.session_scope() as session:
            return ArtifactRepository(session).get_by_artifact_id(artifact_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return ArtifactRepository(session).get_by_id(row_id)

    def list_for_project(self, *, project_id: str, include_archived: bool = False, limit: int = 100):
        with self.session_scope() as session:
            project = ProjectRepository(session).get_by_project_id(project_id)
            if project is None:
                return None
            return ArtifactRepository(session).list_for_project(
                project_id=project.id,
                include_archived=include_archived,
                limit=limit,
            )

    def resolve_local_path(self, artifact) -> str:
        if artifact is None:
            return ""
        if str(getattr(artifact, "storage_backend", "") or "") != self.store.backend_name:
            return ""
        try:
            return str(self.store.resolve_path(getattr(artifact, "storage_key", "") or ""))
        except ValueError:
            return ""


class ConversationVersionService(ServiceBase):
    def ensure_default_branch(self, *, thread_row_id):
        with self.session_scope() as session:
            branch_repo = ThreadBranchRepository(session)
            existing = branch_repo.find_default_for_thread(thread_id=thread_row_id)
            if existing is not None:
                return existing
            leaf = last_message_for_thread(session, thread_id=thread_row_id)
            branch = branch_repo.create(
                branch_id=_public_id("br"),
                thread_id=thread_row_id,
                current_leaf_message_id=getattr(leaf, "id", None),
                title="默认分支",
                metadata={"default_branch": True},
            )
            for message in session.query(Message).filter_by(thread_id=thread_row_id).order_by(Message.created_at.asc()).all():
                message.branch_id = branch.id
            update_thread_version_pointer(
                session,
                thread_id=thread_row_id,
                active_branch_id=branch.id,
                current_leaf_message_id=getattr(leaf, "id", None),
            )
            return branch

    def list_branches(self, *, thread_id: str):
        with self.session_scope() as session:
            thread = ThreadRepository(session).get_by_thread_id(thread_id)
            if thread is None:
                return None
            self._ensure_default_branch_in_session(session, thread)
            return ThreadBranchRepository(session).list_for_thread(thread_id=thread.id)

    def _ensure_default_branch_in_session(self, session, thread):
        branch_repo = ThreadBranchRepository(session)
        branch = branch_repo.find_default_for_thread(thread_id=thread.id)
        if branch is None:
            leaf = last_message_for_thread(session, thread_id=thread.id)
            branch = branch_repo.create(
                branch_id=_public_id("br"),
                thread_id=thread.id,
                current_leaf_message_id=getattr(leaf, "id", None),
                title="默认分支",
                metadata={"default_branch": True},
            )
            for message in session.query(Message).filter_by(thread_id=thread.id).order_by(Message.created_at.asc()).all():
                message.branch_id = branch.id
        if thread.active_branch_id is None:
            update_thread_version_pointer(
                session,
                thread_id=thread.id,
                active_branch_id=branch.id,
                current_leaf_message_id=branch.current_leaf_message_id,
            )
        return branch

    def create_checkpoint(
        self,
        *,
        thread_id: str,
        title: str = "",
        checkpoint_type: str = "manual",
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            thread = ThreadRepository(session).get_by_thread_id(thread_id)
            if thread is None:
                return None
            branch = self._ensure_default_branch_in_session(session, thread)
            active_branch = ThreadBranchRepository(session).get_by_id(thread.active_branch_id) or branch
            leaf_id = thread.current_leaf_message_id or getattr(active_branch, "current_leaf_message_id", None)
            state = {
                "thread_id": thread.thread_id,
                "active_branch_id": getattr(active_branch, "branch_id", ""),
                "current_leaf_message_id": "",
            }
            leaf = session.get(Message, leaf_id) if leaf_id is not None else None
            if leaf is not None:
                state["current_leaf_message_id"] = leaf.message_id
            return ConversationCheckpointRepository(session).create(
                checkpoint_id=_public_id("chk"),
                thread_id=thread.id,
                branch_id=getattr(active_branch, "id", None),
                message_id=leaf_id,
                checkpoint_type=checkpoint_type,
                title=str(title or "").strip() or "检查点",
                state=state,
                metadata=metadata,
            )

    def _create_auto_checkpoint_in_session(self, session, *, thread, branch, message):
        if thread is None or branch is None or message is None:
            return None
        existing = (
            session.query(ConversationCheckpoint)
            .filter(
                ConversationCheckpoint.thread_id == thread.id,
                ConversationCheckpoint.message_id == message.id,
                ConversationCheckpoint.checkpoint_type == "auto",
            )
            .one_or_none()
        )
        if existing is not None:
            return existing
        message_meta = dict(getattr(message, "meta", {}) or {})
        state = {
            "thread_id": thread.thread_id,
            "active_branch_id": getattr(branch, "branch_id", "") or "",
            "current_leaf_message_id": getattr(message, "message_id", "") or "",
        }
        role_label = {
            "user": "用户消息",
            "assistant": "助手消息",
            "system": "系统消息",
            "tool": "工具消息",
        }.get(str(getattr(message, "role", "") or "").strip().lower(), "消息")
        title = f"自动检查点：{role_label} {str(getattr(message, 'message_id', '') or '')[-8:]}"
        return ConversationCheckpointRepository(session).create(
            checkpoint_id=_public_id("chk"),
            thread_id=thread.id,
            branch_id=getattr(branch, "id", None),
            message_id=message.id,
            checkpoint_type="auto",
            title=title,
            state=state,
            metadata={
                "auto": True,
                "auto_reason": "message_persisted",
                "message_id": getattr(message, "message_id", "") or "",
                "role": getattr(message, "role", "") or "",
                "turn_id": str(message_meta.get("turn_id") or ""),
                "stream_id": str(message_meta.get("stream_id") or ""),
            },
        )

    def attach_message_to_active_branch(self, *, thread_row_id, message_row_id):
        with self.session_scope() as session:
            thread = ThreadRepository(session).get_by_id(thread_row_id)
            message = MessageRepository(session).get_by_id(message_row_id)
            if thread is None or message is None:
                return None
            branch = self._ensure_default_branch_in_session(session, thread)
            active_branch = ThreadBranchRepository(session).get_by_id(thread.active_branch_id) or branch
            if message.branch_id is None:
                message.branch_id = active_branch.id
            if message.parent_message_id is None and thread.current_leaf_message_id != message.id:
                message.parent_message_id = thread.current_leaf_message_id
            active_branch.current_leaf_message_id = message.id
            update_thread_version_pointer(
                session,
                thread_id=thread.id,
                active_branch_id=active_branch.id,
                current_leaf_message_id=message.id,
            )
            self._create_auto_checkpoint_in_session(
                session,
                thread=thread,
                branch=active_branch,
                message=message,
            )
            return message

    def list_checkpoints(self, *, thread_id: str, limit: int = 100):
        with self.session_scope() as session:
            thread = ThreadRepository(session).get_by_thread_id(thread_id)
            if thread is None:
                return None
            return ConversationCheckpointRepository(session).list_for_thread(thread_id=thread.id, limit=limit)

    def restore_checkpoint(self, *, thread_id: str, checkpoint_id: str):
        with self.session_scope() as session:
            thread = ThreadRepository(session).get_by_thread_id(thread_id)
            checkpoint = ConversationCheckpointRepository(session).get_by_checkpoint_id(checkpoint_id)
            if thread is None or checkpoint is None or checkpoint.thread_id != thread.id:
                return None
            update_thread_version_pointer(
                session,
                thread_id=thread.id,
                active_branch_id=checkpoint.branch_id,
                current_leaf_message_id=checkpoint.message_id,
            )
            return checkpoint

    def checkout_checkpoint(self, *, thread_id: str, checkpoint_id: str, title: str = ""):
        with self.session_scope() as session:
            thread = ThreadRepository(session).get_by_thread_id(thread_id)
            checkpoint = ConversationCheckpointRepository(session).get_by_checkpoint_id(checkpoint_id)
            if thread is None or checkpoint is None or checkpoint.thread_id != thread.id:
                return None
            parent_branch_id = checkpoint.branch_id
            branch = ThreadBranchRepository(session).create(
                branch_id=_public_id("br"),
                thread_id=thread.id,
                parent_branch_id=parent_branch_id,
                root_message_id=checkpoint.message_id,
                current_leaf_message_id=checkpoint.message_id,
                title=str(title or "").strip() or f"从检查点签出 {str(checkpoint.checkpoint_id or '')[-8:]}",
                metadata={"checkout_checkpoint_id": checkpoint.checkpoint_id},
            )
            update_thread_version_pointer(
                session,
                thread_id=thread.id,
                active_branch_id=branch.id,
                current_leaf_message_id=checkpoint.message_id,
            )
            return branch

    def activate_branch(self, *, thread_id: str, branch_id: str):
        with self.session_scope() as session:
            thread = ThreadRepository(session).get_by_thread_id(thread_id)
            branch = ThreadBranchRepository(session).get_by_branch_id(branch_id)
            if thread is None or branch is None or branch.thread_id != thread.id:
                return None
            update_thread_version_pointer(
                session,
                thread_id=thread.id,
                active_branch_id=branch.id,
                current_leaf_message_id=branch.current_leaf_message_id,
            )
            return branch

    def edit_retry(
        self,
        *,
        message_id: str,
        new_content: str,
        title: str = "",
        fallback_session_row_id=None,
        fallback_origin_endpoint_row_id=None,
        fallback_active_workspace_row_id=None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self.session_scope() as session:
            message = MessageRepository(session).get_by_message_id(message_id)
            if message is None or str(getattr(message, "role", "") or "") != "user":
                return None
            thread = ThreadRepository(session).get_by_id(message.thread_id)
            if thread is None:
                return None
            fallback_session = None
            if fallback_session_row_id is not None:
                fallback_session = SessionRepository(session).get_by_id(fallback_session_row_id)
                if fallback_session is not None and getattr(fallback_session, "thread_id", None) != thread.id:
                    fallback_session = None
            resolved_session_id = message.session_id or getattr(fallback_session, "id", None)
            resolved_workspace_id = (
                message.active_workspace_id
                or getattr(fallback_session, "active_workspace_id", None)
                or fallback_active_workspace_row_id
            )
            resolved_endpoint_id = (
                message.origin_endpoint_id
                or getattr(fallback_session, "origin_endpoint_id", None)
                or fallback_origin_endpoint_row_id
            )
            fallback_metadata = {
                key: value
                for key, value in dict(metadata or {}).items()
                if str(value or "").strip()
            }
            self._ensure_default_branch_in_session(session, thread)
            branch = ThreadBranchRepository(session).create(
                branch_id=_public_id("br"),
                thread_id=thread.id,
                parent_branch_id=message.branch_id,
                root_message_id=message.parent_message_id,
                title=str(title or "").strip() or f"编辑重试 {str(message.message_id or '')[-8:]}",
                metadata={"edit_retry_of_message_id": message.message_id},
            )
            sibling_count = (
                session.query(Message)
                .filter(Message.revision_of_message_id == message.id)
                .count()
            )
            edited = MessageRepository(session).create(
                message_id=_public_id("msg"),
                thread_id=thread.id,
                session_id=resolved_session_id,
                run_id=None,
                active_workspace_id=resolved_workspace_id,
                role=message.role,
                channel=message.channel,
                content=str(new_content or ""),
                content_type=message.content_type,
                status="completed",
                created_by_actor_id=message.created_by_actor_id,
                origin_endpoint_id=resolved_endpoint_id,
                meta={
                    **dict(message.meta or {}),
                    **fallback_metadata,
                    "edit_retry": True,
                    "revision_of_message_id": message.message_id,
                },
            )
            edited.parent_message_id = message.parent_message_id
            edited.branch_id = branch.id
            edited.revision_of_message_id = message.id
            edited.variant_index = sibling_count + 1
            branch.current_leaf_message_id = edited.id
            update_thread_version_pointer(
                session,
                thread_id=thread.id,
                active_branch_id=branch.id,
                current_leaf_message_id=edited.id,
            )
            self._create_auto_checkpoint_in_session(
                session,
                thread=thread,
                branch=branch,
                message=edited,
            )
            return {"branch": branch, "message": edited, "replay_status": "branch_created"}


class ResearchTaskService(ServiceBase):
    @staticmethod
    def validate_report_citations(report_markdown: str, evidence_ledger: list[dict[str, Any]] | None) -> dict[str, Any]:
        citation_ids = sorted({match.group(1) for match in _CITATION_RE.finditer(str(report_markdown or ""))}, key=int)
        evidence_source_ids = _evidence_source_ids(evidence_ledger)
        missing_source_ids = [source_id for source_id in citation_ids if source_id not in evidence_source_ids]
        if missing_source_ids:
            raise ResearchTaskCitationError(
                missing_source_ids=missing_source_ids,
                citation_ids=citation_ids,
                evidence_source_ids=evidence_source_ids,
            )
        return {
            "citation_ids": citation_ids,
            "evidence_source_ids": evidence_source_ids,
            "missing_source_ids": [],
        }

    @staticmethod
    def _policy_list(policy: dict[str, Any], *keys: str) -> list[str]:
        values: list[Any] = []
        for key in keys:
            raw = policy.get(key)
            if isinstance(raw, (list, tuple, set)):
                values.extend(raw)
            elif isinstance(raw, (str, bytes)) and str(raw).strip():
                values.append(raw)
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @staticmethod
    def _policy_bool(policy: dict[str, Any], *keys: str) -> bool:
        for key in keys:
            value = policy.get(key)
            if isinstance(value, str):
                if value.strip().lower() in {"1", "true", "yes", "on", "enabled"}:
                    return True
                continue
            if bool(value):
                return True
        return False

    @staticmethod
    def _policy_limit(policy: dict[str, Any]) -> int:
        raw = policy.get("max_sources", policy.get("limit", 8))
        try:
            return max(1, min(int(raw or 8), 24))
        except (TypeError, ValueError):
            return 8

    @classmethod
    def _derived_formats(cls, policy: dict[str, Any], output_format: str) -> list[str]:
        formats = cls._policy_list(policy, "derived_formats", "artifact_formats", "report_formats")
        if cls._policy_bool(policy, "include_pdf"):
            formats.append("pdf")
        if cls._policy_bool(policy, "include_docx"):
            formats.append("docx")
        normalized_output = str(output_format or "").strip().lower()
        if normalized_output in {"all", "pdf"} or "pdf" in normalized_output:
            formats.append("pdf")
        if normalized_output in {"all", "docx", "word"} or "docx" in normalized_output:
            formats.append("docx")
        result: list[str] = []
        for item in formats:
            normalized = str(item or "").strip().lower()
            if normalized in {"pdf", "docx"} and normalized not in result:
                result.append(normalized)
        return result

    @classmethod
    def build_default_plan(cls, topic: str, source_policy: dict | None = None, output_format: str = "markdown") -> dict[str, Any]:
        policy = dict(source_policy or {})
        topic_text = str(topic or "").strip()
        adapters = cls._policy_list(policy, "source_adapters") or ["web", "arxiv", "openalex", "crossref", "semantic_scholar"]
        web_urls = cls._policy_list(policy, "web_urls", "seed_urls", "source_urls")
        web_queries = cls._policy_list(policy, "web_queries", "web_search_queries", "search_queries", "queries")
        derived_formats = cls._derived_formats(policy, output_format)
        source_limit = cls._policy_limit(policy)
        return {
            "schema": "meetyou.research.plan.v1",
            "language": "zh-CN",
            "topic": topic_text,
            "steps": [
                {
                    "id": "intake",
                    "title": "确认研究主题、范围与输出标准",
                    "status": "planned",
                    "editable_fields": ["topic", "constraints", "audience", "output_format"],
                },
                {
                    "id": "plan_review",
                    "title": "用户确认或编辑研究计划",
                    "status": "planned",
                    "requires_user_confirmation": True,
                },
                {"id": "gather", "title": "收集只读网页、学术与项目来源证据", "status": "planned"},
                {"id": "evidence_review", "title": "去重、排序并校验证据账本", "status": "planned"},
                {"id": "synthesize", "title": "综合带引用的研究结论", "status": "planned"},
                {"id": "artifact", "title": "生成可下载报告产物", "status": "planned"},
            ],
            "research_questions": [
                f"围绕「{topic_text}」梳理核心结论与关键背景。",
                "识别证据之间的一致点、冲突点与不确定性。",
                "给出可复核的来源清单、风险说明和后续研究建议。",
            ],
            "source_strategy": {
                "read_only": policy.get("read_only", True) is not False,
                "source_adapters": adapters,
                "include_project_sources": cls._policy_bool(policy, "include_project_sources"),
                "web_search": cls._policy_bool(policy, "web_search", "enable_web_search", "discover_urls", "search_discovery"),
                "web_queries": web_queries,
                "web_url_count": len(web_urls),
                "max_sources": source_limit,
            },
            "quality_gates": [
                {"id": "read_only", "title": "只读收集证据", "enforcement": "fail_if_write_policy_requested"},
                {"id": "evidence_required", "title": "至少收集一条可读证据", "enforcement": "fail_without_evidence"},
                {"id": "citation_guard", "title": "报告引用必须来自最终证据账本", "enforcement": "citation_guard"},
                {"id": "prompt_injection", "title": "来源文本按不可信证据处理", "enforcement": "ignore_source_instructions"},
            ],
            "deliverables": {
                "primary": "markdown",
                "derived_formats": derived_formats,
                "final_message": "summary_with_artifact_links",
            },
            "source_adapters": adapters,
            "requires_approval": True,
            "approval": {
                "required": True,
                "editable": True,
                "editable_before_start": True,
                "start_after": "approve_or_explicit_start",
            },
        }

    def create_task(
        self,
        *,
        principal_id,
        project_id=None,
        thread_id=None,
        topic: str,
        source_policy: dict | None = None,
        output_format: str = "markdown",
        metadata: dict | None = None,
    ):
        normalized_topic = str(topic or "").strip()
        if not normalized_topic:
            raise ValueError("topic is required")
        with self.session_scope() as session:
            return ResearchTaskRepository(session).create(
                research_task_id=_public_id("res"),
                principal_id=principal_id,
                project_id=project_id,
                thread_id=thread_id,
                topic=normalized_topic,
                plan=self.build_default_plan(normalized_topic, source_policy, output_format),
                source_policy=source_policy,
                output_format=str(output_format or "markdown").strip() or "markdown",
                metadata=metadata,
            )

    @staticmethod
    def _normalized_transition_fields(
        *,
        current_status: str,
        action: str,
        fields: dict[str, Any],
        existing_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_action = str(action or "").strip().lower()
        normalized_status = str(current_status or "planned").strip().lower() or "planned"
        next_fields = dict(fields or {})
        requested_status = next_fields.get("status")

        if "plan" in next_fields and normalized_status in {"running", *_RESEARCH_TERMINAL_STATUSES}:
            raise ResearchTaskStateError(
                code="research_plan_locked",
                message="Research plan can only be edited before the task starts.",
            )

        if normalized_action:
            if normalized_action == "approve":
                if normalized_status != "planned":
                    raise ResearchTaskStateError(
                        code="research_transition_invalid",
                        message=f"Cannot approve research task from status {normalized_status}.",
                    )
                requested_status = "approved"
            elif normalized_action == "start":
                if normalized_status not in {"planned", "approved"}:
                    raise ResearchTaskStateError(
                        code="research_transition_invalid",
                        message=f"Cannot start research task from status {normalized_status}.",
                    )
                requested_status = "running"
            elif normalized_action == "cancel":
                if normalized_status in _RESEARCH_TERMINAL_STATUSES:
                    raise ResearchTaskStateError(
                        code="research_transition_invalid",
                        message=f"Cannot cancel research task from status {normalized_status}.",
                    )
                requested_status = "cancelled"
            elif normalized_action == "complete":
                if normalized_status in _RESEARCH_TERMINAL_STATUSES:
                    raise ResearchTaskStateError(
                        code="research_transition_invalid",
                        message=f"Cannot complete research task from status {normalized_status}.",
                    )
                requested_status = "completed"
            elif normalized_action == "fail":
                if normalized_status in _RESEARCH_TERMINAL_STATUSES:
                    raise ResearchTaskStateError(
                        code="research_transition_invalid",
                        message=f"Cannot fail research task from status {normalized_status}.",
                    )
                requested_status = "failed"
            else:
                raise ResearchTaskStateError(
                    code="research_action_invalid",
                    message=f"Unsupported research task action: {normalized_action}",
                )

        if requested_status is not None:
            target_status = str(requested_status or "").strip().lower()
            if target_status not in _RESEARCH_ALLOWED_STATUSES:
                raise ResearchTaskStateError(
                    code="research_status_invalid",
                    message=f"Unsupported research task status: {target_status}",
                )
            if not normalized_action and normalized_status in _RESEARCH_TERMINAL_STATUSES and target_status != normalized_status:
                raise ResearchTaskStateError(
                    code="research_transition_invalid",
                    message=f"Cannot move research task from terminal status {normalized_status} to {target_status}.",
                )
            next_fields["status"] = target_status

        if normalized_action or requested_status is not None:
            target_status = str(next_fields.get("status") or normalized_status).strip().lower()
            metadata = dict(existing_metadata or {})
            metadata.update(dict(next_fields.get("metadata") or {}))
            events = list(metadata.get("events") or [])
            events.append(
                {
                    "action": normalized_action or "status",
                    "from_status": normalized_status,
                    "to_status": target_status,
                    "at": utcnow().isoformat(),
                }
            )
            metadata["events"] = events
            next_fields["metadata"] = metadata

        return next_fields

    @classmethod
    def normalize_update_fields(
        cls,
        *,
        current_status: str,
        action: str = "",
        fields: dict[str, Any] | None = None,
        existing_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return cls._normalized_transition_fields(
            current_status=current_status,
            action=action,
            fields=dict(fields or {}),
            existing_metadata=existing_metadata,
        )

    def get_by_research_task_id(self, research_task_id: str):
        with self.session_scope() as session:
            return ResearchTaskRepository(session).get_by_research_task_id(research_task_id)

    def list_tasks(self, *, principal_id, project_id=None, limit: int = 100):
        with self.session_scope() as session:
            return ResearchTaskRepository(session).list_for_principal(principal_id=principal_id, project_id=project_id, limit=limit)

    def update_task(self, *, research_task_id: str, fields: dict[str, Any]):
        with self.session_scope() as session:
            return ResearchTaskRepository(session).update(research_task_id=research_task_id, fields=fields)

    def transition_task(self, *, research_task_id: str, action: str = "", fields: dict[str, Any] | None = None):
        with self.session_scope() as session:
            repo = ResearchTaskRepository(session)
            row = repo.get_by_research_task_id(research_task_id)
            if row is None:
                return None
            next_fields = self._normalized_transition_fields(
                current_status=str(getattr(row, "status", "") or "planned"),
                action=action,
                fields=dict(fields or {}),
                existing_metadata=dict(getattr(row, "meta", {}) or {}),
            )
            return repo.update(research_task_id=research_task_id, fields=next_fields)
