from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from core.runtime_context import bind_event_context, reset_event_context
from core.services.tool_router_service import ToolRouterError, ToolRouterService
from tools.endpoint_tools import EndpointTools


_RPI_DEVICE_TOOLS = [
    "rpi.device.list",
    "rpi.device.status",
    "rpi.device.set",
    "rpi.device.pulse",
    "rpi.device.blink",
    "rpi.button.read",
]


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

    def connect_endpoint(self, *, endpoint_id: str, provider_type: str, display_name: str):
        self._connected_ids.add(endpoint_id)
        self._snapshots.append(
            {
                "endpoint_id": endpoint_id,
                "provider": {"provider_type": provider_type, "display_name": display_name},
                "connected_at": "2026-04-26T00:00:02Z",
                "updated_at": "2026-04-26T00:00:03Z",
            }
        )

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
            endpoint_type="rpi_executor",
            provider_type="rpi",
            transport_type="websocket",
            status="registered",
            workspace_scope=["legacy-lab"],
            meta={"display_name": "Raspberry Pi"},
            updated_at=None,
        )
        self.endpoints.append(endpoint)
        self.capabilities_by_endpoint[endpoint.id] = [
            SimpleNamespace(
                capability_id=f"endpoint.raspberry.pi.executor.{tool_key}",
                tool_key=tool_key,
                risk_level="local_write"
                if tool_key in {"rpi.device.set", "rpi.device.pulse", "rpi.device.blink"}
                else "read",
                requires_confirmation=tool_key in {"rpi.device.set", "rpi.device.pulse", "rpi.device.blink"},
                enabled=True,
            )
            for tool_key in _RPI_DEVICE_TOOLS
        ]
        self.memberships_by_endpoint[endpoint.id] = [SimpleNamespace(workspace_id=self.workspace.id)]
        return endpoint


class _FakeToolRouter:
    def __init__(self):
        self.calls: list[dict] = []

    async def dispatch_tool_call(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"summary": "read ok"}


class _RouterWorkspaceService:
    def get_by_workspace_id(self, workspace_id):
        return SimpleNamespace(id="workspace-row-personal", workspace_id=workspace_id)

    def get_by_id(self, row_id):
        return SimpleNamespace(id=row_id, workspace_id="personal") if row_id else None


class _RouterEndpointService:
    def __init__(self):
        self.endpoint = SimpleNamespace(
            id="endpoint-row-rpi",
            endpoint_id="raspberry.pi.executor",
            provider_type="rpi",
            status="online",
            workspace_scope=["personal"],
            meta={},
        )

    def get_by_endpoint_id(self, endpoint_id):
        return self.endpoint if endpoint_id == self.endpoint.endpoint_id else None

    def get_by_id(self, row_id):
        return self.endpoint if row_id == self.endpoint.id else None


class _RouterCapabilityService:
    def __init__(self, endpoint_service: _RouterEndpointService):
        self.capability = SimpleNamespace(
            id="capability-row-rpi-set",
            endpoint_id=endpoint_service.endpoint.id,
            capability_id="endpoint.raspberry.pi.executor.rpi.device.set",
            tool_key="rpi.device.set",
            enabled=True,
            requires_confirmation=True,
            risk_level="local_write",
            meta={},
        )

    def list_for_endpoint(self, *, endpoint_row_id):
        return [self.capability] if endpoint_row_id == self.capability.endpoint_id else []

    def list_enabled_for_tool(self, tool_key):
        return [self.capability] if tool_key == self.capability.tool_key else []


class _NoopRouterService:
    def get_by_session_id(self, session_id):
        del session_id
        return None

    def get_by_id(self, row_id):
        del row_id
        return None


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

    async def test_rpi_device_tool_calls_route_through_tool_router_with_confirmed_flag(self):
        tools, router, manager = self._tools()
        endpoint_service = tools._core_domain.services.endpoint
        raspberry = endpoint_service.add_raspberry_endpoint_with_membership_only_scope()
        manager.connect_endpoint(
            endpoint_id=raspberry.endpoint_id,
            provider_type=raspberry.provider_type,
            display_name="Raspberry Pi",
        )

        list_result = await tools.send_endpoint_message(
            target_type="endpoint",
            target_id="raspberry.pi.executor",
            delivery_kind="tool_call",
            tool_key="rpi.device.list",
            arguments={},
            workspace_id="personal",
        )
        set_result = await tools.send_endpoint_message(
            target_type="endpoint",
            target_id="raspberry.pi.executor",
            delivery_kind="tool_call",
            tool_key="rpi.device.set",
            arguments={"device_id": "desk_led", "value": True},
            workspace_id="personal",
            confirmed=True,
        )

        self.assertTrue(list_result["ok"])
        self.assertTrue(set_result["ok"])
        self.assertEqual(router.calls[0]["target_endpoint_id"], "raspberry.pi.executor")
        self.assertEqual(router.calls[0]["tool_key"], "rpi.device.list")
        self.assertEqual(router.calls[0]["arguments"], {})
        self.assertFalse(router.calls[0]["confirmed"])
        self.assertEqual(router.calls[1]["target_endpoint_id"], "raspberry.pi.executor")
        self.assertEqual(router.calls[1]["tool_key"], "rpi.device.set")
        self.assertEqual(router.calls[1]["arguments"], {"device_id": "desk_led", "value": True})
        self.assertTrue(router.calls[1]["confirmed"])

    async def test_rpi_device_write_without_confirmation_keeps_toolrouter_rejection(self):
        endpoint_service = _RouterEndpointService()
        workspace_service = _RouterWorkspaceService()
        capability_service = _RouterCapabilityService(endpoint_service)
        router = ToolRouterService(
            actor_service=_NoopRouterService(),
            workspace_service=workspace_service,
            endpoint_service=endpoint_service,
            endpoint_capability_service=capability_service,
            session_service=_NoopRouterService(),
            thread_service=_NoopRouterService(),
            operation_service=_NoopRouterService(),
            operation_call_service=_NoopRouterService(),
        )
        router.set_connected_endpoint_ids_getter(lambda: {"raspberry.pi.executor"})
        tools = EndpointTools()
        tools.set_core_domain(
            SimpleNamespace(
                tool_router=router,
                services=SimpleNamespace(
                    endpoint=endpoint_service,
                    endpoint_capability=capability_service,
                    workspace=workspace_service,
                    session=_NoopRouterService(),
                ),
            )
        )

        with self.assertRaises(ToolRouterError) as raised:
            await tools.send_endpoint_message(
                target_type="endpoint",
                target_id="raspberry.pi.executor",
                delivery_kind="tool_call",
                tool_key="rpi.device.set",
                arguments={"device_id": "relay_1", "value": True},
                workspace_id="personal",
                confirmed=False,
            )

        self.assertEqual(raised.exception.code, "tool_confirmation_required")
        self.assertEqual(raised.exception.details["endpoint_id"], "raspberry.pi.executor")
        self.assertEqual(raised.exception.details["tool_key"], "rpi.device.set")

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
        manager.connect_endpoint(
            endpoint_id=raspberry.endpoint_id,
            provider_type=raspberry.provider_type,
            display_name="Raspberry Pi",
        )

        payload = await tools.list_endpoint_tool_targets(workspace_id="personal", include_tools=True)
        filtered_payload = await tools.list_endpoint_tool_targets(workspace_id="personal", tool_key="rpi.device.list")

        self.assertTrue(payload["ok"])
        endpoint_ids = {item["endpoint_id"] for item in payload["endpoints"]}
        self.assertIn("desktop.main.executor", endpoint_ids)
        self.assertIn("raspberry.pi.executor", endpoint_ids)
        self.assertEqual(filtered_payload["endpoint_ids"], ["raspberry.pi.executor"])
        self.assertEqual(filtered_payload["endpoints"][0]["matched_tool_key"], "rpi.device.list")
        self.assertIn("raspberry.pi.executor", payload["endpoint_ids"])
        self.assertIn(
            (
                "raspberry.pi.executor | provider=rpi | status=online | "
                "tools=rpi.device.list, rpi.device.status, rpi.device.set, "
                "rpi.device.pulse, rpi.device.blink, rpi.button.read"
            ),
            payload["tool_target_lines"],
        )
        self.assertEqual(payload["executable_tools_by_endpoint"]["raspberry.pi.executor"], _RPI_DEVICE_TOOLS)
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertLess(rendered.index("tool_target_lines"), rendered.index("compact_endpoints"))
        self.assertLess(rendered.index("raspberry.pi.executor | provider=rpi"), 512)
        compact_raspberry = next(item for item in payload["compact_endpoints"] if item["endpoint_id"] == "raspberry.pi.executor")
        self.assertEqual(compact_raspberry["executable_tools"], _RPI_DEVICE_TOOLS)
        raspberry_payload = next(item for item in payload["endpoints"] if item["endpoint_id"] == "raspberry.pi.executor")
        self.assertEqual(raspberry_payload["workspace_ids"], ["personal", "legacy-lab"])
        self.assertEqual(raspberry_payload["status"], "online")
        self.assertEqual(raspberry_payload["tool_keys"], _RPI_DEVICE_TOOLS)
        self.assertEqual(raspberry_payload["capability_count"], len(_RPI_DEVICE_TOOLS))

        active_payload = await tools.list_active_endpoints(workspace_id="personal", include_tools=True)
        self.assertIn("raspberry.pi.executor", active_payload["endpoint_ids"])
        active_endpoint_ids = {item["endpoint_id"] for item in active_payload["endpoints"]}
        self.assertIn("raspberry.pi.executor", active_endpoint_ids)
        self.assertEqual(active_payload["executable_tools_by_endpoint"]["raspberry.pi.executor"], _RPI_DEVICE_TOOLS)
        active_compact_raspberry = next(item for item in active_payload["compact_endpoints"] if item["endpoint_id"] == "raspberry.pi.executor")
        self.assertEqual(active_compact_raspberry["executable_tools"], _RPI_DEVICE_TOOLS)

    async def test_endpoint_inventory_defaults_to_complete_compact_tool_lists(self):
        tools, _, _ = self._tools()
        endpoint_service = tools._core_domain.services.endpoint
        endpoint_service.capabilities_by_endpoint[endpoint_service.endpoint.id] = [
            SimpleNamespace(
                capability_id=f"cap-{index}",
                tool_key=f"tool.{index:02d}",
                risk_level="read",
                requires_confirmation=False,
                enabled=True,
            )
            for index in range(24)
        ]

        payload = await tools.list_active_endpoints(workspace_id="personal")

        tools_by_endpoint = payload["executable_tools_by_endpoint"]["desktop.main.executor"]
        self.assertEqual(len(tools_by_endpoint), 24)
        self.assertEqual(tools_by_endpoint[-1], "tool.23")
        self.assertIn("desktop.main.executor", payload["endpoint_ids"])
        self.assertFalse(payload["endpoints"][0]["capability_details_included"])
        self.assertEqual(payload["endpoints"][0]["capabilities"], [])
        self.assertEqual(payload["endpoints"][0]["capability_count"], 24)


if __name__ == "__main__":
    unittest.main()
