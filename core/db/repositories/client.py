from __future__ import annotations

from core.db.models.client import Client
from core.db.repositories.base import RepositoryBase


class ClientRepository(RepositoryBase):
    def create(self, *, client_id: str, principal_id, client_type: str, display_name: str) -> Client:
        client = Client(
            client_id=client_id,
            principal_id=principal_id,
            client_type=client_type,
            display_name=display_name,
        )
        self.session.add(client)
        self.session.flush()
        return client

    def get_by_client_id(self, client_id: str) -> Client | None:
        return self.session.query(Client).filter_by(client_id=client_id).one_or_none()

    def get_by_id(self, row_id) -> Client | None:
        return self.session.query(Client).filter_by(id=row_id).one_or_none()
