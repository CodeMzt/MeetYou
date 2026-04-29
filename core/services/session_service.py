from __future__ import annotations

from uuid import uuid4

from core.db.repositories import SessionRepository
from core.services.base import ServiceBase


class SessionService(ServiceBase):
    def create_session(self, *, thread_id, origin_endpoint_id=None, active_workspace_id=None, workspace_id=None, status: str = "active"):
        resolved_active_workspace_id = active_workspace_id if active_workspace_id is not None else workspace_id
        with self.session_scope() as session:
            return SessionRepository(session).create(
                session_id=f"sess_{uuid4().hex}",
                thread_id=thread_id,
                origin_endpoint_id=origin_endpoint_id,
                active_workspace_id=resolved_active_workspace_id,
                status=status,
            )

    def get_by_session_id(self, session_id: str):
        with self.session_scope() as session:
            return SessionRepository(session).get_by_session_id(session_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return SessionRepository(session).get_by_id(row_id)

    def set_active_workspace(self, *, session_id: str, active_workspace_id, metadata: dict | None = None):
        with self.session_scope() as session:
            return SessionRepository(session).update_active_workspace(
                session_id=session_id,
                active_workspace_id=active_workspace_id,
                metadata=metadata,
            )
