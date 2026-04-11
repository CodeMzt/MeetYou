from __future__ import annotations

from core.db.models.thread import Thread
from core.db.repositories.base import RepositoryBase


class ThreadRepository(RepositoryBase):
    def create(self, *, thread_id: str, principal_id, workspace_id, title: str = "", pinned_procedure_id: str | None = None) -> Thread:
        thread = Thread(
            thread_id=thread_id,
            principal_id=principal_id,
            workspace_id=workspace_id,
            title=title,
            pinned_procedure_id=pinned_procedure_id,
        )
        self.session.add(thread)
        self.session.flush()
        return thread

    def get_by_thread_id(self, thread_id: str) -> Thread | None:
        return self.session.query(Thread).filter_by(thread_id=thread_id).one_or_none()

    def get_by_id(self, row_id) -> Thread | None:
        return self.session.query(Thread).filter_by(id=row_id).one_or_none()
