from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.runtime_context import bind_event_context, reset_event_context
from tools.endpoint_tools import EndpointTools


class _FakeEndpointWsManager:
    def __init__(self):
        self.notices: list[dict] = []

    async def publish_notice(self, *, target_endpoint_id: str, payload: dict) -> int:
        self.notices.append({"target_endpoint_id": target_endpoint_id, "payload": dict(payload)})
        return 1


class _FakeEndpointService:
    def __init__(self):
        self.endpoint = SimpleNamespace(
            id="endpoint-row-1",
            endpoint_id="desktop.main.executor",
            endpoint_type="desktop_executor",
            provider_type="desktop",
            transport_type="websocket",
            status="online",
            workspace_scope=["desktop-main"],
            meta={"display_name": "Desktop Main"},
            updated_at=None,
        )

    def get_by_endpoint_id(self, endpoint_id: str):
        return self.endpoint if endpoint_id == self.endpoint.endpoint_id else None


class _FakeToolRouter:
    def __init__(self):
        self.calls: list[dict] = []

    async def dispatch_directed_tool(self, **kwargs):
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
                    endpoint_capability=SimpleNamespace(list_for_endpoint=lambda endpoint_row_id: []),
                    workspace=SimpleNamespace(get_by_workspace_id=lambda workspace_id: None, get_by_id=lambda row_id: None),
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


if __name__ == "__main__":
    unittest.main()
