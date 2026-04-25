from __future__ import annotations

import unittest

from gateway.agent_ws_manager import AgentConnectionManager
from gateway.client_ws import ClientWebSocketManager


class _FakeWebSocket:
    def __init__(self):
        self.frames: list[dict] = []

    async def send_json(self, frame: dict) -> None:
        self.frames.append(dict(frame))


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


if __name__ == "__main__":
    unittest.main()
