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

    def update_pinned_procedure(self, *, thread_id, pinned_procedure_id: str | None) -> Thread | None:
        thread = self.get_by_id(thread_id)
        if thread is None:
            return None
        thread.pinned_procedure_id = pinned_procedure_id
        self.session.flush()
        return thread

    def update_metadata(self, *, thread_id, metadata: dict) -> Thread | None:
        thread = self.get_by_id(thread_id)
        if thread is None:
            return None
        merged = dict(thread.meta or {})
        merged.update(dict(metadata or {}))
        thread.meta = merged
        self.session.flush()
        return thread

    def clear_pinned_procedure_for_procedure(self, *, procedure_id: str) -> int:
        rows = list(self.session.query(Thread).filter_by(pinned_procedure_id=procedure_id).all())
        for row in rows:
            row.pinned_procedure_id = None
        if rows:
            self.session.flush()
        return len(rows)
