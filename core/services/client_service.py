from __future__ import annotations

from core.db.repositories import ClientRepository, WorkspaceRepository
from core.services.base import ServiceBase


class ClientService(ServiceBase):
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

    def list_clients(self):
        with self.session_scope() as session:
            return ClientRepository(session).list_all()

    def register_client(
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
    ):
        with self.session_scope() as session:
            return ClientRepository(session).update_registration(
                client_id=client_id,
                principal_id=principal_id,
                client_type=client_type,
                display_name=display_name,
                status=status,
                available_tools=available_tools,
                executable_tools=executable_tools,
                transport_profile=transport_profile,
                host=host,
                metadata=metadata,
            )

    def record_heartbeat(self, *, client_id: str, status: str = "online", metadata: dict | None = None):
        with self.session_scope() as session:
            return ClientRepository(session).record_heartbeat(client_id=client_id, status=status, metadata=metadata)

    def replace_workspace_bindings(self, *, client_id: str, workspace_ids: list):
        with self.session_scope() as session:
            return ClientRepository(session).replace_workspace_bindings(
                client_id=client_id,
                workspace_ids=workspace_ids,
                workspace_repo=WorkspaceRepository(session),
            )

    def bind_workspace(
        self,
        *,
        workspace_id,
        client_id,
        membership_role: str = "member",
        enabled: bool = True,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return ClientRepository(session).bind_workspace(
                workspace_id=workspace_id,
                client_id=client_id,
                membership_role=membership_role,
                enabled=enabled,
                metadata=metadata,
            )

    def list_workspace_bindings(self, client_id: str):
        with self.session_scope() as session:
            return ClientRepository(session).list_workspace_bindings(client_id)

    def list_clients_for_workspace(self, workspace_id):
        with self.session_scope() as session:
            return ClientRepository(session).list_clients_for_workspace(workspace_id)

    def is_bound_to_workspace(self, *, client_id: str, workspace_id) -> bool:
        with self.session_scope() as session:
            resolved_workspace_id = workspace_id
            workspace = WorkspaceRepository(session).get_by_workspace_id(str(workspace_id or ""))
            if workspace is not None:
                resolved_workspace_id = workspace.id
            return ClientRepository(session).is_bound_to_workspace(client_id=client_id, workspace_id=resolved_workspace_id)

    def can_start_tool(self, *, client_id: str, tool_key: str) -> bool:
        client = self.get_by_client_id(client_id)
        if client is None:
            return False
        tools = self._string_list(getattr(client, "available_tools", []) or [])
        return not tools or str(tool_key or "").strip() in tools

    def can_execute_tool(self, *, client_id: str, tool_key: str) -> bool:
        client = self.get_by_client_id(client_id)
        if client is None:
            return False
        return str(tool_key or "").strip() in self._string_list(getattr(client, "executable_tools", []) or [])

    def list_tool_clients_for_workspace(self, *, workspace_id, tool_key: str = ""):
        with self.session_scope() as session:
            rows = ClientRepository(session).list_clients_for_workspace(workspace_id)
            normalized_tool = str(tool_key or "").strip()
            if not normalized_tool:
                return rows
            return [
                (client, membership)
                for client, membership in rows
                if normalized_tool in self._string_list(getattr(client, "executable_tools", []) or [])
            ]

    def select_workspace_client(
        self,
        *,
        workspace_id,
        requesting_client_id=None,
        preferred_target_endpoint_ids: list[str] | None = None,
        preferred_endpoint_provider_types: list[str] | None = None,
        routing_policy: str = "balanced",
        allowed_client_ids: list[str] | None = None,
    ):
        del requesting_client_id, routing_policy
        allowed = set(self._string_list(allowed_client_ids or []))
        preferred_ids = self._string_list(preferred_target_endpoint_ids or [])
        preferred_types = self._string_list(preferred_endpoint_provider_types or [])
        with self.session_scope() as session:
            rows = ClientRepository(session).list_clients_for_workspace(workspace_id)
            clients = [
                client
                for client, membership in rows
                if bool(getattr(membership, "enabled", True))
                and str(getattr(client, "status", "") or "").strip().lower() in {"online", "ready", "active"}
                and (not allowed or str(getattr(client, "client_id", "") or "") in allowed)
            ]
            for preferred_id in preferred_ids:
                for client in clients:
                    if str(getattr(client, "client_id", "") or "") == preferred_id:
                        return client
            for preferred_type in preferred_types:
                for client in clients:
                    if str(getattr(client, "client_type", "") or "") == preferred_type:
                        return client
            return clients[0] if clients else None
