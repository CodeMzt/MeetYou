from __future__ import annotations

from datetime import datetime, timezone

from core.db.models.client import Client, ClientWorkspaceMembership
from core.db.models.workspace import Workspace
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

    @staticmethod
    def _string_list(values) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            item = str(value or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def get_by_client_id(self, client_id: str) -> Client | None:
        return self.session.query(Client).filter_by(client_id=client_id).one_or_none()

    def get_by_id(self, row_id) -> Client | None:
        return self.session.query(Client).filter_by(id=row_id).one_or_none()

    def list_all(self) -> list[Client]:
        return list(self.session.query(Client).order_by(Client.display_name.asc(), Client.client_id.asc()).all())

    def update_registration(
        self,
        *,
        client_id: str,
        principal_id,
        client_type: str,
        display_name: str,
        status: str = "online",
        available_tools=None,
        executable_tools=None,
        transport_profile: str = "",
        host: dict | None = None,
        metadata: dict | None = None,
    ) -> Client:
        row = self.get_by_client_id(client_id)
        host_payload = dict(host or {})
        if row is None:
            row = Client(
                client_id=client_id,
                principal_id=principal_id,
                client_type=client_type,
                display_name=display_name,
            )
            self.session.add(row)
        row.principal_id = principal_id
        row.client_type = client_type or row.client_type
        row.display_name = display_name or row.display_name
        row.status = status or "online"
        row.available_tools = self._string_list(available_tools)
        row.executable_tools = self._string_list(executable_tools)
        row.transport_profile = str(transport_profile or "").strip()
        row.host_name = str(host_payload.get("hostname") or host_payload.get("host_name") or "").strip()
        row.host_os = str(host_payload.get("os") or host_payload.get("host_os") or "").strip()
        row.host_arch = str(host_payload.get("arch") or host_payload.get("host_arch") or "").strip()
        row.last_seen_at = datetime.now(timezone.utc)
        if metadata:
            merged = dict(row.meta or {})
            merged.update(dict(metadata or {}))
            row.meta = merged
        self.session.flush()
        return row

    def record_heartbeat(self, *, client_id: str, status: str = "online", metadata: dict | None = None) -> Client | None:
        row = self.get_by_client_id(client_id)
        if row is None:
            return None
        row.status = status or row.status or "online"
        row.last_seen_at = datetime.now(timezone.utc)
        if metadata:
            merged = dict(row.meta or {})
            merged.update(dict(metadata or {}))
            row.meta = merged
        self.session.flush()
        return row

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

    def list_workspace_bindings(self, client_id: str) -> list[tuple[Workspace, ClientWorkspaceMembership]]:
        client = self.get_by_client_id(client_id)
        if client is None:
            return []
        return list(
            self.session.query(Workspace, ClientWorkspaceMembership)
            .join(Workspace, Workspace.id == ClientWorkspaceMembership.workspace_id)
            .filter(ClientWorkspaceMembership.client_id == client.id)
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

    def replace_workspace_bindings(self, *, client_id: str, workspace_ids: list, workspace_repo) -> list[ClientWorkspaceMembership]:
        client = self.get_by_client_id(client_id)
        if client is None:
            return []
        requested = self._string_list(workspace_ids)
        rows: list[ClientWorkspaceMembership] = []
        for public_workspace_id in requested:
            workspace = workspace_repo.get_by_workspace_id(public_workspace_id)
            if workspace is None:
                workspace = workspace_repo.create(
                    workspace_id=public_workspace_id,
                    principal_id=client.principal_id,
                    title=public_workspace_id,
                    description="Client-advertised workspace",
                    metadata={"source": "client.hello"},
                )
            rows.append(
                self.bind_workspace(
                    workspace_id=workspace.id,
                    client_id=client.id,
                    membership_role="member",
                    enabled=True,
                    metadata={"source": "client.hello"},
                )
            )
        return rows

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
