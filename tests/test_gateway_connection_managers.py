from __future__ import annotations

import unittest

from gateway.agent_ws_manager import AgentConnectionManager
from gateway.client_ws import ClientWebSocketManager
from gateway.routes.client import _ensure_client_always_available_tools


class _FakeWebSocket:
    def __init__(self):
        self.frames: list[dict] = []

    async def send_json(self, frame: dict) -> None:
        self.frames.append(dict(frame))


class _FailingWebSocket:
    async def send_json(self, frame: dict) -> None:
        raise RuntimeError("closed")


class GatewayConnectionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_manager_reports_connected_snapshot(self):
        manager = AgentConnectionManager()
        websocket = _FakeWebSocket()

        await manager.connect("agent-1", websocket)

        self.assertTrue(await manager.is_connected("agent-1"))
        self.assertEqual(await manager.connected_agent_ids(), {"agent-1"})
        snapshot = await manager.snapshot()
        self.assertEqual(snapshot[0]["agent_id"], "agent-1")
        self.assertTrue(snapshot[0]["connected"])

        await manager.disconnect("agent-1", websocket)
        self.assertFalse(await manager.is_connected("agent-1"))

    async def test_agent_manager_ignores_stale_disconnect_after_reconnect(self):
        manager = AgentConnectionManager()
        stale = _FakeWebSocket()
        current = _FakeWebSocket()

        await manager.connect("agent-1", stale)
        await manager.connect("agent-1", current)

        self.assertFalse(await manager.disconnect("agent-1", stale))
        self.assertTrue(await manager.is_connected("agent-1"))

        self.assertTrue(await manager.disconnect("agent-1", current))
        self.assertFalse(await manager.is_connected("agent-1"))

    async def test_agent_manager_drops_connection_after_send_failure(self):
        manager = AgentConnectionManager()

        await manager.connect("agent-1", _FailingWebSocket())

        self.assertFalse(await manager.send_to_agent("agent-1", {"type": "notice"}))
        self.assertFalse(await manager.is_connected("agent-1"))

    async def test_client_manager_binds_identity_and_sends_targeted_event(self):
        manager = ClientWebSocketManager()
        websocket = _FakeWebSocket()

        await manager.connect("thr-1", websocket)
        await manager.bind_connection(
            websocket,
            thread_id="thr-1",
            client_id="desktop-app",
            session_id="sess-1",
            workspace_id="desktop-main",
            client_type="electron",
            display_name="Desktop App",
        )

        snapshot = await manager.snapshot(client_id="desktop-app")
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["session_id"], "sess-1")
        self.assertEqual(snapshot[0]["workspace_id"], "desktop-main")

        delivered = await manager.publish_client_event(
            "desktop-app",
            event_type="message.created",
            payload={"thread_id": "thr-1", "message": {"message_id": "msg-1"}},
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(websocket.frames[0]["event"]["type"], "message.created")

        await manager.disconnect("thr-1", websocket)
        self.assertEqual(await manager.snapshot(client_id="desktop-app"), [])

    async def test_client_manager_updates_session_workspace_for_existing_socket(self):
        manager = ClientWebSocketManager()
        websocket = _FakeWebSocket()

        await manager.connect("thr-1", websocket)
        await manager.bind_connection(
            websocket,
            thread_id="thr-1",
            client_id="desktop-app",
            session_id="sess-1",
            workspace_id="personal",
        )

        updated = await manager.update_session_metadata("sess-1", workspace_id="desktop-main")

        self.assertEqual(updated, 1)
        self.assertEqual(await manager.snapshot(workspace_id="personal"), [])
        refreshed = await manager.snapshot(workspace_id="desktop-main")
        self.assertEqual(len(refreshed), 1)
        self.assertEqual(refreshed[0]["client_id"], "desktop-app")

    async def test_client_manager_filters_targeted_event_by_session(self):
        manager = ClientWebSocketManager()
        first = _FakeWebSocket()
        second = _FakeWebSocket()

        await manager.connect("thr-1", first)
        await manager.bind_connection(
            first,
            thread_id="thr-1",
            client_id="desktop-app",
            session_id="sess-1",
            workspace_id="desktop-main",
        )
        await manager.connect("thr-2", second)
        await manager.bind_connection(
            second,
            thread_id="thr-2",
            client_id="desktop-app",
            session_id="sess-2",
            workspace_id="desktop-main",
        )

        delivered = await manager.publish_client_event(
            "desktop-app",
            event_type="message.created",
            payload={"thread_id": "thr-1", "message": {"message_id": "msg-1"}},
            session_id="sess-1",
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(len(first.frames), 1)
        self.assertEqual(second.frames, [])


class ClientToolExposureTests(unittest.TestCase):
    def test_client_allowed_bundle_keeps_endpoint_and_short_reply_tools(self):
        metadata = _ensure_client_always_available_tools(
            {
                "allowed_tool_bundle": ["search_web", "send_endpoint_message"],
                "tool_scope": "custom",
            }
        )

        self.assertEqual(
            metadata["allowed_tool_bundle"],
            ["search_web", "send_endpoint_message", "emit_short_reply"],
        )


if __name__ == "__main__":
    unittest.main()
