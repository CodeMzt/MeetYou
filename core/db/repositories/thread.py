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
        metadata: dict | None = None,
    ) -> Thread:
        resolved_home_workspace_id = home_workspace_id if home_workspace_id is not None else workspace_id
        thread = Thread(
            thread_id=thread_id,
            principal_id=principal_id,
            home_workspace_id=resolved_home_workspace_id,
            title=title,
            meta=dict(metadata or {}),
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

    def list_for_principal(self, *, principal_id, workspace_id=None, limit: int = 50) -> list[Thread]:
        query = self.session.query(Thread).filter_by(principal_id=principal_id)
        if workspace_id is not None:
            query = query.filter_by(home_workspace_id=workspace_id)
        limit = max(1, min(int(limit or 50), 200))
        return list(query.order_by(Thread.updated_at.desc(), Thread.created_at.desc()).limit(limit).all())

    def find_default(self, *, principal_id, workspace_id, default_key: str) -> Thread | None:
        normalized_key = str(default_key or "").strip()
        if not normalized_key:
            return None
        rows = self.list_for_principal(principal_id=principal_id, workspace_id=workspace_id, limit=200)
        for row in rows:
            metadata = dict(row.meta or {})
            if metadata.get("default_key") == normalized_key:
                return row
        return None
