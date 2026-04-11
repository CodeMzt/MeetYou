from __future__ import annotations

from core.db.repositories import ClientRepository
from core.services.base import ServiceBase


class ClientService(ServiceBase):
    def ensure_client(self, *, client_id: str, principal_id, client_type: str, display_name: str):
        with self.session_scope() as session:
            repo = ClientRepository(session)
            existing = repo.get_by_client_id(client_id)
            if existing is not None:
                return existing
            return repo.create(
                client_id=client_id,
                principal_id=principal_id,
                client_type=client_type,
                display_name=display_name,
            )

    def get_by_client_id(self, client_id: str):
        with self.session_scope() as session:
            return ClientRepository(session).get_by_client_id(client_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return ClientRepository(session).get_by_id(row_id)
