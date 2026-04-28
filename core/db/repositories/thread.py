from __future__ import annotations

from core.db.models.thread import Thread
from core.db.repositories.base import RepositoryBase


class ThreadRepository(RepositoryBase):
    def create(
        self,
        *,
        thread_id: str,
        principal_id,
        home_workspace_id=None,
        workspace_id=None,
        title: str = "",
    ) -> Thread:
        resolved_home_workspace_id = home_workspace_id if home_workspace_id is not None else workspace_id
        thread = Thread(
            thread_id=thread_id,
            principal_id=principal_id,
            home_workspace_id=resolved_home_workspace_id,
            title=title,
        )
        self.session.add(thread)
        self.session.flush()
        return thread

    def get_by_thread_id(self, thread_id: str) -> Thread | None:
        return self.session.query(Thread).filter_by(thread_id=thread_id).one_or_none()

    def get_by_id(self, row_id) -> Thread | None:
        return self.session.query(Thread).filter_by(id=row_id).one_or_none()

    def update_metadata(self, *, thread_id, metadata: dict) -> Thread | None:
        thread = self.get_by_id(thread_id)
        if thread is None:
            return None
        merged = dict(thread.meta or {})
        merged.update(dict(metadata or {}))
        thread.meta = merged
        self.session.flush()
        return thread
