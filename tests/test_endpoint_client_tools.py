from __future__ import annotations

import unittest
from types import SimpleNamespace

from tools.endpoint_tools import EndpointTools


class _FakeClientWsManager:
    def __init__(self):
        self._snapshots = [
            {
                "client_id": "desktop-app",
                "display_name": "Desktop App",
                "client_type": "desktop",
                "thread_id": "thr-1",
                "session_id": "sess-1",
                "workspace_id": "personal",
                "available_tools": ["search_web", "shell.exec"],
                "executable_tools": ["shell.exec", "file.read"],
                "transport_profile": "desktop",
                "connected_at": "2026-04-26T00:00:00Z",
                "updated_at": "2026-04-26T00:00:01Z",
                "host": {"name": "desk", "os": "windows", "arch": "x64"},
            }
        ]

    async def snapshot(self, **filters):
        rows = [dict(item) for item in self._snapshots]
        for key, value in filters.items():
            normalized = str(value or "").strip()
            if normalized:
                rows = [item for item in rows if str(item.get(key) or "").strip() == normalized]
        return rows

    async def connected_client_ids(self):
        return {str(item["client_id"]) for item in self._snapshots}


class _FakeClientService:
    def __init__(self):
        self.workspace = SimpleNamespace(id="workspace-row-personal", workspace_id="personal")
        self.membership = SimpleNamespace(enabled=True)
        self.client = SimpleNamespace(
            id="client-row-desktop",
            client_id="desktop-app",
            display_name="Desktop App",
            client_type="desktop",
            status="online",
            available_tools=["search_web", "shell.exec"],
            executable_tools=["shell.exec", "file.read"],
            transport_profile="desktop",
            host_name="desk",
            host_os="windows",
            host_arch="x64",
            last_seen_at=None,
        )

    def list_workspace_bindings(self, client_id: str):
        if client_id == self.client.client_id:
            return [(self.workspace, self.membership)]
        return []

    def list_clients_for_workspace(self, workspace_id):
        if workspace_id == self.workspace.id:
            return [(self.client, self.membership)]
        return []

    def list_tool_clients_for_workspace(self, *, workspace_id, tool_key: str = ""):
        rows = self.list_clients_for_workspace(workspace_id)
        if not tool_key:
            return rows
        return [
            (client, membership)
            for client, membership in rows
            if tool_key in getattr(client, "executable_tools", [])
        ]

    def list_clients(self):
        return [self.client]


class _FakeWorkspaceService:
    def __init__(self, workspace):
        self.workspace = workspace

    def get_by_workspace_id(self, workspace_id: str):
        return self.workspace if workspace_id == self.workspace.workspace_id else None


class EndpointClientToolsTests(unittest.IsolatedAsyncioTestCase):
    def _tools(self):
        client_service = _FakeClientService()
        tools = EndpointTools()
        tools.set_core_domain(
            SimpleNamespace(
                services=SimpleNamespace(
                    client=client_service,
                    workspace=_FakeWorkspaceService(client_service.workspace),
                    session=SimpleNamespace(get_by_session_id=lambda _session_id: None),
                )
            )
        )
        tools.set_runtime(gateway_getter=lambda: SimpleNamespace(client_ws_manager=_FakeClientWsManager()))
        return tools

    async def test_list_active_clients_reports_workspace_ids_without_unpack_error(self):
        payload = await self._tools().list_active_clients(workspace_id="personal")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["clients"][0]["client_id"], "desktop-app")
        self.assertEqual(payload["clients"][0]["workspace_ids"], ["personal"])

    async def test_list_client_tool_targets_filters_executable_tools(self):
        payload = await self._tools().list_client_tool_targets(workspace_id="personal", tool_key="shell.exec")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["clients"][0]["client_id"], "desktop-app")
        self.assertEqual(payload["clients"][0]["matched_tool_key"], "shell.exec")


if __name__ == "__main__":
    unittest.main()
