from __future__ import annotations

from uuid import uuid4

from core.db.repositories import SessionRepository
from core.services.base import ServiceBase


class SessionService(ServiceBase):
    def create_session(self, *, thread_id, client_id, workspace_id, status: str = "active"):
        with self.session_scope() as session:
            return SessionRepository(session).create(
                session_id=f"sess_{uuid4().hex}",
                thread_id=thread_id,
                client_id=client_id,
                workspace_id=workspace_id,
                status=status,
            )

    def get_by_session_id(self, session_id: str):
        with self.session_scope() as session:
            return SessionRepository(session).get_by_session_id(session_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return SessionRepository(session).get_by_id(row_id)
