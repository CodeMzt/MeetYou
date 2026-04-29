from __future__ import annotations

from uuid import uuid4

from core.db.repositories import ThreadRepository
from core.services.base import ServiceBase


class ThreadService(ServiceBase):
    def create_thread(
        self,
        *,
        principal_id,
        home_workspace_id=None,
        workspace_id=None,
        title: str = "",
        metadata: dict | None = None,
    ):
        resolved_home_workspace_id = home_workspace_id if home_workspace_id is not None else workspace_id
        with self.session_scope() as session:
            return ThreadRepository(session).create(
                thread_id=f"thr_{uuid4().hex}",
                principal_id=principal_id,
                home_workspace_id=resolved_home_workspace_id,
                title=title,
                metadata=metadata,
            )

    def get_by_thread_id(self, thread_id: str):
        with self.session_scope() as session:
            return ThreadRepository(session).get_by_thread_id(thread_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return ThreadRepository(session).get_by_id(row_id)

    def list_threads(self, *, principal_id, workspace_id=None, limit: int = 50):
        with self.session_scope() as session:
            return ThreadRepository(session).list_for_principal(
                principal_id=principal_id,
                workspace_id=workspace_id,
                limit=limit,
            )

    def ensure_default_thread(
        self,
        *,
        principal_id,
        home_workspace_id=None,
        workspace_id=None,
        default_key: str = "frontend.default",
        title: str = "",
    ):
        resolved_home_workspace_id = home_workspace_id if home_workspace_id is not None else workspace_id
        normalized_key = str(default_key or "frontend.default").strip() or "frontend.default"
        with self.session_scope() as session:
            repo = ThreadRepository(session)
            existing = repo.find_default(
                principal_id=principal_id,
                workspace_id=resolved_home_workspace_id,
                default_key=normalized_key,
            )
            if existing is not None:
                return existing
            return repo.create(
                thread_id=f"thr_{uuid4().hex}",
                principal_id=principal_id,
                home_workspace_id=resolved_home_workspace_id,
                title=title or "Desktop Chat",
                metadata={"default_key": normalized_key},
            )

