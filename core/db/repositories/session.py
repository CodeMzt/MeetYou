from __future__ import annotations

from core.db.models.session import Session
from core.db.repositories.base import RepositoryBase


class SessionRepository(RepositoryBase):
    def create(self, *, session_id: str, thread_id, client_id, workspace_id, status: str = "active") -> Session:
        session = Session(
            session_id=session_id,
            thread_id=thread_id,
            client_id=client_id,
            workspace_id=workspace_id,
            status=status,
        )
        self.session.add(session)
        self.session.flush()
        return session

    def get_by_session_id(self, session_id: str) -> Session | None:
        return self.session.query(Session).filter_by(session_id=session_id).one_or_none()

    def get_by_id(self, row_id) -> Session | None:
        return self.session.query(Session).filter_by(id=row_id).one_or_none()
