from __future__ import annotations

import unittest
from types import SimpleNamespace

from tools.endpoint_tools import EndpointTools


class _FakeEndpointWsManager:
    def __init__(self):
        self._snapshots = [
            {
                "endpoint_id": "desktop.desktop-app.executor",
                "provider": {"provider_type": "desktop", "display_name": "Desktop App"},
                "connected_at": "2026-04-26T00:00:00Z",
                "updated_at": "2026-04-26T00:00:01Z",
            }
        ]

    async def snapshot(self, **filters):
        rows = [dict(item) for item in self._snapshots]
        for key, value in filters.items():
            normalized = str(value or "").strip()
            if normalized:
                rows = [item for item in rows if str(item.get(key) or "").strip() == normalized]
        return rows

    async def connected_endpoint_ids(self):
        return {str(item["endpoint_id"]) for item in self._snapshots}


class _FakeEndpointService:
    def __init__(self):
        self.workspace = SimpleNamespace(id="workspace-row-personal", workspace_id="personal")
        self.endpoint = SimpleNamespace(
            id="endpoint-row-desktop",
            endpoint_id="desktop.desktop-app.executor",
            endpoint_type="desktop_executor",
            provider_type="desktop",
            transport_type="websocket",
            status="online",
            workspace_scope=["personal"],
            meta={"display_name": "Desktop App"},
            updated_at=None,
        )
        self.capabilities = [
            SimpleNamespace(
                capability_id="endpoint.desktop.desktop-app.executor.shell.exec",
                tool_key="shell.exec",
                risk_level="system",
                requires_confirmation=True,
                enabled=True,
            )
        ]

    def list_all(self):
        return [self.endpoint]


class _FakeWorkspaceService:
    def __init__(self, workspace):
        self.workspace = workspace

    def get_by_workspace_id(self, workspace_id: str):
        return self.workspace if workspace_id == self.workspace.workspace_id else None


class EndpointClientToolsTests(unittest.IsolatedAsyncioTestCase):
    def _tools(self):
        endpoint_service = _FakeEndpointService()
        tools = EndpointTools()
        tools.set_core_domain(
            SimpleNamespace(
                services=SimpleNamespace(
                    endpoint=endpoint_service,
                    endpoint_capability=SimpleNamespace(
                        list_for_endpoint=lambda endpoint_row_id: endpoint_service.capabilities
                        if endpoint_row_id == endpoint_service.endpoint.id
                        else []
                    ),
                    workspace=_FakeWorkspaceService(endpoint_service.workspace),
                    session=SimpleNamespace(get_by_session_id=lambda _session_id: None),
                )
            )
        )
        tools.set_runtime(gateway_getter=lambda: SimpleNamespace(endpoint_ws_manager=_FakeEndpointWsManager()))
        return tools

    async def test_list_active_clients_reports_workspace_ids_without_unpack_error(self):
        payload = await self._tools().list_active_clients(workspace_id="personal")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["endpoints"][0]["endpoint_id"], "desktop.desktop-app.executor")
        self.assertEqual(payload["endpoints"][0]["workspace_ids"], ["personal"])

    async def test_list_client_tool_targets_filters_executable_tools(self):
        payload = await self._tools().list_client_tool_targets(workspace_id="personal", tool_key="shell.exec")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["endpoints"][0]["endpoint_id"], "desktop.desktop-app.executor")
        self.assertEqual(payload["endpoints"][0]["matched_tool_key"], "shell.exec")


if __name__ == "__main__":
    unittest.main()
