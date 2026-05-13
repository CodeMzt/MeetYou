from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.runtime_context import bind_event_context, reset_event_context
from tools.endpoint_tools import EndpointTools


class _FakeEndpointWsManager:
    def __init__(self):
        self.notices: list[dict] = []
        self._snapshots = [
            {
                "endpoint_id": "desktop.main.executor",
                "provider": {"provider_type": "desktop", "display_name": "Desktop Main"},
                "connected_at": "2026-04-26T00:00:00Z",
                "updated_at": "2026-04-26T00:00:01Z",
            }
        ]
        self._connected_ids = {"desktop.main.executor"}

    async def snapshot(self, **filters):
        rows = [dict(item) for item in self._snapshots]
        for key, value in filters.items():
            normalized = str(value or "").strip()
            if normalized:
                rows = [item for item in rows if str(item.get(key) or "").strip() == normalized]
        return rows

    async def connected_endpoint_ids(self):
        return set(self._connected_ids)

    async def publish_notice(self, *, target_endpoint_id: str, payload: dict) -> int:
        self.notices.append({"target_endpoint_id": target_endpoint_id, "payload": dict(payload)})
        return 1


class _FakeEndpointService:
    def __init__(self):
        self.workspace = SimpleNamespace(id="workspace-row-personal", workspace_id="personal")
        self.endpoint = SimpleNamespace(
            id="endpoint-row-1",
            endpoint_id="desktop.main.executor",
            endpoint_type="desktop_executor",
            provider_type="desktop",
            transport_type="websocket",
            status="registered",
            workspace_scope=["personal", "desktop-main"],
            meta={"display_name": "Desktop Main"},
            updated_at=None,
        )
        self.endpoints = [self.endpoint]
        self.capabilities_by_endpoint = {
            self.endpoint.id: [
                SimpleNamespace(
                    capability_id="endpoint.desktop.main.executor.shell.exec",
                    tool_key="shell.exec",
                    risk_level="system",
                    requires_confirmation=True,
                    enabled=True,
                )
            ]
        }
        self.memberships_by_endpoint = {self.endpoint.id: [SimpleNamespace(workspace_id=self.workspace.id)]}

    def get_by_endpoint_id(self, endpoint_id: str):
        return next((endpoint for endpoint in self.endpoints if endpoint.endpoint_id == endpoint_id), None)

    def list_all(self):
        return list(self.endpoints)

    def add_raspberry_endpoint_with_membership_only_scope(self):
        endpoint = SimpleNamespace(
            id="endpoint-row-rpi",
            endpoint_id="raspberry.pi.executor",
            endpoint_type="edge_executor",
            provider_type="raspberry_pi",
            transport_type="websocket",
            status="registered",
            workspace_scope=["legacy-lab"],
            meta={"display_name": "Raspberry Pi"},
            updated_at=None,
        )
        self.endpoints.append(endpoint)
        self.capabilities_by_endpoint[endpoint.id] = [
            SimpleNamespace(
                capability_id="endpoint.raspberry.pi.executor.sensor.read",
                tool_key="sensor.read",
                risk_level="read",
                requires_confirmation=False,
                enabled=True,
            )
        ]
        self.memberships_by_endpoint[endpoint.id] = [SimpleNamespace(workspace_id=self.workspace.id)]
        return endpoint


class _FakeToolRouter:
    def __init__(self):
        self.calls: list[dict] = []

    async def dispatch_tool_call(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"summary": "read ok"}


class EndpointToolsTests(unittest.IsolatedAsyncioTestCase):
    def _tools(self):
        endpoint_service = _FakeEndpointService()
        router = _FakeToolRouter()
        manager = _FakeEndpointWsManager()
        tools = EndpointTools()
        tools.set_core_domain(
            SimpleNamespace(
                tool_router=router,
                services=SimpleNamespace(
                    endpoint=endpoint_service,
                    endpoint_capability=SimpleNamespace(
                        list_for_endpoint=lambda endpoint_row_id: endpoint_service.capabilities_by_endpoint.get(endpoint_row_id, [])
                    ),
                    endpoint_workspace_membership=SimpleNamespace(
                        list_for_endpoint=lambda endpoint_row_id: endpoint_service.memberships_by_endpoint.get(endpoint_row_id, [])
                    ),
                    workspace=SimpleNamespace(
                        get_by_workspace_id=lambda workspace_id: endpoint_service.workspace
                        if workspace_id == endpoint_service.workspace.workspace_id
                        else None,
                        get_by_id=lambda row_id: endpoint_service.workspace
                        if row_id == endpoint_service.workspace.id
                        else None,
                    ),
                    session=SimpleNamespace(get_by_session_id=lambda session_id: None),
                ),
            )
        )
        tools.set_runtime(gateway_getter=lambda: SimpleNamespace(endpoint_ws_manager=manager))
        return tools, router, manager

    async def test_endpoint_notice_delivers_notice_frame_only(self):
        tools, _, manager = self._tools()

        result = await tools.send_endpoint_message(
            target_type="endpoint",
            target_id="desktop.main.executor",
            delivery_kind="notice",
            content="desktop notice",
            session_id="sess-1",
            workspace_id="desktop-main",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["target_id"], "desktop.main.executor")
        self.assertEqual(result["connection_count"], 1)
        self.assertEqual(manager.notices[0]["target_endpoint_id"], "desktop.main.executor")
        notice = manager.notices[0]["payload"]
        self.assertEqual(notice["content"], "desktop notice")
        self.assertEqual(notice["metadata"]["runtime_action"], "delivery.notice")
        self.assertEqual(notice["metadata"]["target_type"], "endpoint")

    async def test_endpoint_notice_rejects_same_origin_reply_path(self):
        tools, _, manager = self._tools()
        token = bind_event_context(source_id="desktop.main.executor")
        try:
            with self.assertRaises(RuntimeError) as raised:
                await tools.send_endpoint_message(
                    target_type="endpoint",
                    target_id="desktop.main.executor",
                    delivery_kind="notice",
                    content="duplicate reply",
                    session_id="sess-1",
                    workspace_id="desktop-main",
                )
        finally:
            reset_event_context(token)

        self.assertEqual(raised.exception.tool_error_code, "same_origin_endpoint_notice_forbidden")
        self.assertEqual(manager.notices, [])

    async def test_endpoint_tool_call_routes_through_tool_router(self):
        tools, router, _ = self._tools()

        result = await tools.send_endpoint_message(
            target_type="endpoint",
            target_id="desktop.main.executor",
            delivery_kind="tool_call",
            tool_key="file.read",
            arguments={"path": "demo.txt"},
            session_id="sess-1",
            workspace_id="desktop-main",
            confirmed=True,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["target_endpoint_id"], "desktop.main.executor")
        self.assertEqual(result["result"], {"summary": "read ok"})
        self.assertEqual(router.calls[0]["target_endpoint_id"], "desktop.main.executor")
        self.assertEqual(router.calls[0]["tool_key"], "file.read")
        self.assertEqual(router.calls[0]["arguments"], {"path": "demo.txt"})
        self.assertTrue(router.calls[0]["confirmed"])

    async def test_list_active_endpoints_reports_workspace_ids_without_unpack_error(self):
        tools, _, _ = self._tools()

        payload = await tools.list_active_endpoints(workspace_id="personal")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["endpoints"][0]["endpoint_id"], "desktop.main.executor")
        self.assertEqual(payload["endpoints"][0]["workspace_ids"], ["personal", "desktop-main"])

    async def test_list_endpoint_tool_targets_filters_executable_tools(self):
        tools, _, _ = self._tools()

        payload = await tools.list_endpoint_tool_targets(workspace_id="personal", tool_key="shell.exec")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["endpoints"][0]["endpoint_id"], "desktop.main.executor")
        self.assertEqual(payload["endpoints"][0]["matched_tool_key"], "shell.exec")

    async def test_list_endpoint_tools_uses_workspace_membership_like_operator_topology(self):
        tools, _, manager = self._tools()
        endpoint_service = tools._core_domain.services.endpoint
        raspberry = endpoint_service.add_raspberry_endpoint_with_membership_only_scope()
        manager._connected_ids.add(raspberry.endpoint_id)

        payload = await tools.list_endpoint_tool_targets(workspace_id="personal", include_tools=True)

        self.assertTrue(payload["ok"])
        endpoint_ids = {item["endpoint_id"] for item in payload["endpoints"]}
        self.assertIn("desktop.main.executor", endpoint_ids)
        self.assertIn("raspberry.pi.executor", endpoint_ids)
        self.assertIn("raspberry.pi.executor", payload["endpoint_ids"])
        compact_raspberry = next(item for item in payload["compact_endpoints"] if item["endpoint_id"] == "raspberry.pi.executor")
        self.assertEqual(compact_raspberry["executable_tools"], ["sensor.read"])
        raspberry_payload = next(item for item in payload["endpoints"] if item["endpoint_id"] == "raspberry.pi.executor")
        self.assertEqual(raspberry_payload["workspace_ids"], ["personal", "legacy-lab"])
        self.assertEqual(raspberry_payload["status"], "online")
        self.assertEqual(raspberry_payload["tool_keys"], ["sensor.read"])
        self.assertEqual(raspberry_payload["capability_count"], 1)

        active_payload = await tools.list_active_endpoints(workspace_id="personal", include_tools=True)
        self.assertIn("raspberry.pi.executor", active_payload["endpoint_ids"])
        active_endpoint_ids = {item["endpoint_id"] for item in active_payload["endpoints"]}
        self.assertIn("raspberry.pi.executor", active_endpoint_ids)


if __name__ == "__main__":
    unittest.main()
