from __future__ import annotations

from core.db.models.client import Client, ClientWorkspaceMembership
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

    def bind_workspace(
        self,
        *,
        workspace_id,
        client_id,
        membership_role: str = "member",
        enabled: bool = True,
        metadata: dict | None = None,
    ) -> ClientWorkspaceMembership:
        row = (
            self.session.query(ClientWorkspaceMembership)
            .filter_by(workspace_id=workspace_id, client_id=client_id)
            .one_or_none()
        )
        if row is None:
            row = ClientWorkspaceMembership(
                workspace_id=workspace_id,
                client_id=client_id,
                membership_role=membership_role or "member",
                enabled=enabled,
                meta=dict(metadata or {}),
            )
            self.session.add(row)
        else:
            row.membership_role = membership_role or row.membership_role or "member"
            row.enabled = enabled
            if metadata:
                merged = dict(row.meta or {})
                merged.update(dict(metadata or {}))
                row.meta = merged
        self.session.flush()
        return row

    def list_workspace_bindings(self, client_id: str) -> list[ClientWorkspaceMembership]:
        client = self.get_by_client_id(client_id)
        if client is None:
            return []
        return list(
            self.session.query(ClientWorkspaceMembership)
            .filter_by(client_id=client.id)
            .order_by(ClientWorkspaceMembership.created_at.asc())
            .all()
        )

    def list_clients_for_workspace(self, workspace_id) -> list[tuple[Client, ClientWorkspaceMembership]]:
        rows = (
            self.session.query(Client, ClientWorkspaceMembership)
            .join(ClientWorkspaceMembership, ClientWorkspaceMembership.client_id == Client.id)
            .filter(ClientWorkspaceMembership.workspace_id == workspace_id)
            .order_by(Client.display_name.asc(), Client.client_id.asc())
            .all()
        )
        return list(rows)

    def is_bound_to_workspace(self, *, client_id: str, workspace_id) -> bool:
        client = self.get_by_client_id(client_id)
        if client is None:
            return False
        row = (
            self.session.query(ClientWorkspaceMembership)
            .filter_by(client_id=client.id, workspace_id=workspace_id, enabled=True)
            .one_or_none()
        )
        return row is not None
