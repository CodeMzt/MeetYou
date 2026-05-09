from __future__ import annotations

import hashlib
from uuid import uuid4
from typing import Any

from core.artifacts import LocalArtifactStore
from core.db.models import Message
from core.db.repositories import (
    ArtifactRepository,
    ConversationCheckpointRepository,
    MessageRepository,
    ProjectRepository,
    ProjectSourceRepository,
    ResearchTaskRepository,
    ThreadBranchRepository,
    ThreadRepository,
)
from core.db.repositories.v5 import last_message_for_thread, update_thread_version_pointer
from core.services.base import ServiceBase


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _public_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


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
                title=str(title or "").strip() or "Untitled Project",
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
                title=str(title or "").strip() or "Project Source",
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
                title=str(title or "").strip() or f"Message {message.message_id}",
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


class ArtifactService(ServiceBase):
    def __init__(self, session_factory, *, store: LocalArtifactStore | None = None):
        super().__init__(session_factory)
        self.store = store or LocalArtifactStore()

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
                title="Default",
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
                title="Default",
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
                title=str(title or "").strip() or "Checkpoint",
                state=state,
                metadata=metadata,
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
                title=str(title or "").strip() or f"Checkout from {checkpoint.checkpoint_id}",
                metadata={"checkout_checkpoint_id": checkpoint.checkpoint_id},
            )
            update_thread_version_pointer(
                session,
                thread_id=thread.id,
                active_branch_id=branch.id,
                current_leaf_message_id=checkpoint.message_id,
            )
            return branch

    def edit_retry(self, *, message_id: str, new_content: str, title: str = "") -> dict[str, Any] | None:
        with self.session_scope() as session:
            message = MessageRepository(session).get_by_message_id(message_id)
            if message is None or str(getattr(message, "role", "") or "") != "user":
                return None
            thread = ThreadRepository(session).get_by_id(message.thread_id)
            if thread is None:
                return None
            self._ensure_default_branch_in_session(session, thread)
            branch = ThreadBranchRepository(session).create(
                branch_id=_public_id("br"),
                thread_id=thread.id,
                parent_branch_id=message.branch_id,
                root_message_id=message.parent_message_id,
                title=str(title or "").strip() or f"Edit retry from {message.message_id}",
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
                session_id=message.session_id,
                run_id=None,
                active_workspace_id=message.active_workspace_id,
                role=message.role,
                channel=message.channel,
                content=str(new_content or ""),
                content_type=message.content_type,
                status="completed",
                created_by_actor_id=message.created_by_actor_id,
                origin_endpoint_id=message.origin_endpoint_id,
                meta={
                    **dict(message.meta or {}),
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
            return {"branch": branch, "message": edited, "replay_status": "branch_created"}


class ResearchTaskService(ServiceBase):
    @staticmethod
    def build_default_plan(topic: str, source_policy: dict | None = None) -> dict[str, Any]:
        policy = dict(source_policy or {})
        return {
            "schema": "meetyou.research.plan.v1",
            "topic": str(topic or "").strip(),
            "steps": [
                {"id": "intake", "title": "Clarify scope and constraints", "status": "planned"},
                {"id": "gather", "title": "Gather web, academic, and project-source evidence", "status": "planned"},
                {"id": "synthesize", "title": "Synthesize findings with cited claims", "status": "planned"},
                {"id": "artifact", "title": "Create downloadable report artifact", "status": "planned"},
            ],
            "source_adapters": list(policy.get("source_adapters") or ["web", "arxiv", "openalex", "crossref", "semantic_scholar"]),
            "requires_approval": True,
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
                plan=self.build_default_plan(normalized_topic, source_policy),
                source_policy=source_policy,
                output_format=str(output_format or "markdown").strip() or "markdown",
                metadata=metadata,
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
