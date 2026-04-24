from __future__ import annotations

from core.db.models.session import Session
from core.db.repositories.base import RepositoryBase


class SessionRepository(RepositoryBase):
    def create(
        self,
        *,
        session_id: str,
        thread_id,
        client_id,
        active_workspace_id=None,
        workspace_id=None,
        status: str = "active",
    ) -> Session:
        resolved_active_workspace_id = active_workspace_id if active_workspace_id is not None else workspace_id
        session = Session(
            session_id=session_id,
            thread_id=thread_id,
            client_id=client_id,
            active_workspace_id=resolved_active_workspace_id,
            status=status,
        )
        self.session.add(session)
        self.session.flush()
        return session

    def get_by_session_id(self, session_id: str) -> Session | None:
        return self.session.query(Session).filter_by(session_id=session_id).one_or_none()

    def get_by_id(self, row_id) -> Session | None:
        return self.session.query(Session).filter_by(id=row_id).one_or_none()

    def update_active_workspace(self, *, session_id: str, active_workspace_id, metadata: dict | None = None) -> Session | None:
        row = self.get_by_session_id(session_id)
        if row is None:
            return None
        row.active_workspace_id = active_workspace_id
        if metadata:
            merged = dict(row.meta or {})
            merged.update(dict(metadata or {}))
            row.meta = merged
        self.session.flush()
        return row
