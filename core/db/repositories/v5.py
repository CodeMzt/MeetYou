from __future__ import annotations

from core.db.base import utcnow
from core.db.models import Artifact, ConversationCheckpoint, Message, Project, ProjectSource, ResearchTask, Thread, ThreadBranch
from core.db.repositories.base import RepositoryBase


class ProjectRepository(RepositoryBase):
    def create(
        self,
        *,
        project_id: str,
        principal_id,
        workspace_id=None,
        title: str = "",
        description: str = "",
        instructions: str = "",
        memory_scope: dict | None = None,
        metadata: dict | None = None,
    ) -> Project:
        row = Project(
            project_id=project_id,
            principal_id=principal_id,
            workspace_id=workspace_id,
            title=title,
            description=description,
            instructions=instructions,
            memory_scope=dict(memory_scope or {}),
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_project_id(self, project_id: str) -> Project | None:
        return self.session.query(Project).filter_by(project_id=str(project_id or "").strip()).one_or_none()

    def get_by_id(self, row_id) -> Project | None:
        return self.session.query(Project).filter_by(id=row_id).one_or_none()

    def list_for_principal(self, *, principal_id, workspace_id=None, include_archived: bool = False, limit: int = 100) -> list[Project]:
        query = self.session.query(Project).filter_by(principal_id=principal_id)
        if workspace_id is not None:
            query = query.filter_by(workspace_id=workspace_id)
        if not include_archived:
            query = query.filter(Project.status != "archived")
        return list(query.order_by(Project.updated_at.desc(), Project.created_at.desc()).limit(max(1, min(int(limit or 100), 500))).all())

    def update(self, *, project_id: str, fields: dict) -> Project | None:
        row = self.get_by_project_id(project_id)
        if row is None:
            return None
        for key in ("title", "description", "instructions", "status"):
            if key in fields and fields[key] is not None:
                setattr(row, key, str(fields[key] or ""))
        if "memory_scope" in fields and isinstance(fields["memory_scope"], dict):
            row.memory_scope = dict(fields["memory_scope"])
        if "metadata" in fields and isinstance(fields["metadata"], dict):
            merged = dict(row.meta or {})
            merged.update(dict(fields["metadata"] or {}))
            row.meta = merged
        self.session.flush()
        return row


class ProjectSourceRepository(RepositoryBase):
    def create(
        self,
        *,
        source_id: str,
        project_id,
        principal_id,
        source_type: str = "note",
        title: str = "",
        content: str = "",
        content_type: str = "text",
        source_thread_id=None,
        source_message_id=None,
        artifact_id=None,
        checksum: str = "",
        metadata: dict | None = None,
    ) -> ProjectSource:
        row = ProjectSource(
            source_id=source_id,
            project_id=project_id,
            principal_id=principal_id,
            source_type=source_type,
            title=title,
            content=content,
            content_type=content_type,
            source_thread_id=source_thread_id,
            source_message_id=source_message_id,
            artifact_id=artifact_id,
            checksum=checksum,
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_source_id(self, source_id: str) -> ProjectSource | None:
        return self.session.query(ProjectSource).filter_by(source_id=str(source_id or "").strip()).one_or_none()

    def list_for_project(self, *, project_id, include_archived: bool = False, limit: int = 100) -> list[ProjectSource]:
        query = self.session.query(ProjectSource).filter_by(project_id=project_id)
        if not include_archived:
            query = query.filter(ProjectSource.status != "archived")
        return list(query.order_by(ProjectSource.updated_at.desc(), ProjectSource.created_at.desc()).limit(max(1, min(int(limit or 100), 500))).all())


class ArtifactRepository(RepositoryBase):
    def create(
        self,
        *,
        artifact_id: str,
        principal_id,
        project_id=None,
        thread_id=None,
        created_by_run_id=None,
        artifact_type: str = "document",
        storage_backend: str = "local",
        storage_key: str = "",
        filename: str = "",
        content_type: str = "application/octet-stream",
        byte_size: int = 0,
        checksum: str = "",
        metadata: dict | None = None,
    ) -> Artifact:
        row = Artifact(
            artifact_id=artifact_id,
            principal_id=principal_id,
            project_id=project_id,
            thread_id=thread_id,
            created_by_run_id=created_by_run_id,
            artifact_type=artifact_type,
            storage_backend=storage_backend,
            storage_key=storage_key,
            filename=filename,
            content_type=content_type,
            byte_size=int(byte_size or 0),
            checksum=checksum,
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_artifact_id(self, artifact_id: str) -> Artifact | None:
        return self.session.query(Artifact).filter_by(artifact_id=str(artifact_id or "").strip()).one_or_none()

    def get_by_id(self, row_id) -> Artifact | None:
        return self.session.query(Artifact).filter_by(id=row_id).one_or_none()

    def list_for_project(self, *, project_id, include_archived: bool = False, limit: int = 100) -> list[Artifact]:
        query = self.session.query(Artifact).filter_by(project_id=project_id)
        if not include_archived:
            query = query.filter(Artifact.status != "archived")
        return list(query.order_by(Artifact.updated_at.desc(), Artifact.created_at.desc()).limit(max(1, min(int(limit or 100), 500))).all())


class ThreadBranchRepository(RepositoryBase):
    def create(
        self,
        *,
        branch_id: str,
        thread_id,
        parent_branch_id=None,
        root_message_id=None,
        current_leaf_message_id=None,
        title: str = "",
        metadata: dict | None = None,
    ) -> ThreadBranch:
        row = ThreadBranch(
            branch_id=branch_id,
            thread_id=thread_id,
            parent_branch_id=parent_branch_id,
            root_message_id=root_message_id,
            current_leaf_message_id=current_leaf_message_id,
            title=title,
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_branch_id(self, branch_id: str) -> ThreadBranch | None:
        return self.session.query(ThreadBranch).filter_by(branch_id=str(branch_id or "").strip()).one_or_none()

    def get_by_id(self, row_id) -> ThreadBranch | None:
        return self.session.query(ThreadBranch).filter_by(id=row_id).one_or_none()

    def list_for_thread(self, *, thread_id, include_archived: bool = False) -> list[ThreadBranch]:
        query = self.session.query(ThreadBranch).filter_by(thread_id=thread_id)
        if not include_archived:
            query = query.filter(ThreadBranch.status != "archived")
        return list(query.order_by(ThreadBranch.created_at.asc()).all())

    def find_default_for_thread(self, *, thread_id) -> ThreadBranch | None:
        rows = self.list_for_thread(thread_id=thread_id, include_archived=True)
        for row in rows:
            if dict(row.meta or {}).get("default_branch"):
                return row
        return rows[0] if rows else None

    def update_leaf(self, *, branch_id, current_leaf_message_id=None) -> ThreadBranch | None:
        row = self.get_by_id(branch_id)
        if row is None:
            return None
        row.current_leaf_message_id = current_leaf_message_id
        self.session.flush()
        return row


class ConversationCheckpointRepository(RepositoryBase):
    def create(
        self,
        *,
        checkpoint_id: str,
        thread_id,
        branch_id=None,
        message_id=None,
        run_id=None,
        checkpoint_type: str = "manual",
        title: str = "",
        state: dict | None = None,
        metadata: dict | None = None,
    ) -> ConversationCheckpoint:
        row = ConversationCheckpoint(
            checkpoint_id=checkpoint_id,
            thread_id=thread_id,
            branch_id=branch_id,
            message_id=message_id,
            run_id=run_id,
            checkpoint_type=checkpoint_type,
            title=title,
            state=dict(state or {}),
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_checkpoint_id(self, checkpoint_id: str) -> ConversationCheckpoint | None:
        return self.session.query(ConversationCheckpoint).filter_by(checkpoint_id=str(checkpoint_id or "").strip()).one_or_none()

    def list_for_thread(self, *, thread_id, include_archived: bool = False, limit: int = 100) -> list[ConversationCheckpoint]:
        query = self.session.query(ConversationCheckpoint).filter_by(thread_id=thread_id)
        if not include_archived:
            query = query.filter(ConversationCheckpoint.status != "archived")
        return list(query.order_by(ConversationCheckpoint.created_at.desc()).limit(max(1, min(int(limit or 100), 500))).all())


class ResearchTaskRepository(RepositoryBase):
    def create(
        self,
        *,
        research_task_id: str,
        principal_id,
        project_id=None,
        thread_id=None,
        topic: str = "",
        plan: dict | None = None,
        source_policy: dict | None = None,
        output_format: str = "markdown",
        metadata: dict | None = None,
    ) -> ResearchTask:
        row = ResearchTask(
            research_task_id=research_task_id,
            principal_id=principal_id,
            project_id=project_id,
            thread_id=thread_id,
            topic=topic,
            plan=dict(plan or {}),
            source_policy=dict(source_policy or {}),
            output_format=output_format,
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_research_task_id(self, research_task_id: str) -> ResearchTask | None:
        return self.session.query(ResearchTask).filter_by(research_task_id=str(research_task_id or "").strip()).one_or_none()

    def list_for_principal(self, *, principal_id, project_id=None, limit: int = 100) -> list[ResearchTask]:
        query = self.session.query(ResearchTask).filter_by(principal_id=principal_id)
        if project_id is not None:
            query = query.filter_by(project_id=project_id)
        return list(query.order_by(ResearchTask.updated_at.desc(), ResearchTask.created_at.desc()).limit(max(1, min(int(limit or 100), 500))).all())

    def update(self, *, research_task_id: str, fields: dict) -> ResearchTask | None:
        row = self.get_by_research_task_id(research_task_id)
        if row is None:
            return None
        for key in ("topic", "status", "output_format", "summary"):
            if key in fields and fields[key] is not None:
                setattr(row, key, str(fields[key] or ""))
        for key in ("plan", "source_policy"):
            if key in fields and isinstance(fields[key], dict):
                setattr(row, key, dict(fields[key] or {}))
        if "evidence_ledger" in fields and isinstance(fields["evidence_ledger"], list):
            row.evidence_ledger = list(fields["evidence_ledger"])
        if "artifact_id" in fields:
            row.artifact_id = fields["artifact_id"]
        if "metadata" in fields and isinstance(fields["metadata"], dict):
            merged = dict(row.meta or {})
            merged.update(dict(fields["metadata"] or {}))
            row.meta = merged
        self.session.flush()
        return row


def last_message_for_thread(session, *, thread_id, branch_id=None) -> Message | None:
    query = session.query(Message).filter_by(thread_id=thread_id)
    if branch_id is not None:
        query = query.filter_by(branch_id=branch_id)
    return query.order_by(Message.created_at.desc()).first()


def update_thread_version_pointer(session, *, thread_id, active_branch_id=None, current_leaf_message_id=None) -> Thread | None:
    row = session.query(Thread).filter_by(id=thread_id).one_or_none()
    if row is None:
        return None
    if active_branch_id is not None:
        row.active_branch_id = active_branch_id
    row.current_leaf_message_id = current_leaf_message_id
    row.updated_at = utcnow()
    session.flush()
    return row
