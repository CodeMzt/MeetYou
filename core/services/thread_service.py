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
    ):
        resolved_home_workspace_id = home_workspace_id if home_workspace_id is not None else workspace_id
        with self.session_scope() as session:
            return ThreadRepository(session).create(
                thread_id=f"thr_{uuid4().hex}",
                principal_id=principal_id,
                home_workspace_id=resolved_home_workspace_id,
                title=title,
            )

    def get_by_thread_id(self, thread_id: str):
        with self.session_scope() as session:
            return ThreadRepository(session).get_by_thread_id(thread_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return ThreadRepository(session).get_by_id(row_id)

