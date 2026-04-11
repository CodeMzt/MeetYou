from __future__ import annotations

from uuid import uuid4

from core.db.repositories import ThreadRepository
from core.services.base import ServiceBase


class ThreadService(ServiceBase):
    def create_thread(self, *, principal_id, workspace_id, title: str = "", pinned_procedure_id: str | None = None):
        with self.session_scope() as session:
            return ThreadRepository(session).create(
                thread_id=f"thr_{uuid4().hex}",
                principal_id=principal_id,
                workspace_id=workspace_id,
                title=title,
                pinned_procedure_id=pinned_procedure_id,
            )

    def get_by_thread_id(self, thread_id: str):
        with self.session_scope() as session:
            return ThreadRepository(session).get_by_thread_id(thread_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return ThreadRepository(session).get_by_id(row_id)
