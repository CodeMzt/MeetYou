from __future__ import annotations

import unittest

from gateway.endpoint_ws import ENDPOINT_WS_SCHEMA, EndpointWebSocketManager


class _FakeWebSocket:
    def __init__(self):
        self.frames: list[dict] = []

    async def send_json(self, frame: dict) -> None:
        self.frames.append(dict(frame))


class _FailingWebSocket:
    async def send_json(self, frame: dict) -> None:
        raise RuntimeError("closed")


class GatewayEndpointConnectionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_manager_binds_identity_and_sends_notice(self):
        manager = EndpointWebSocketManager()
        websocket = _FakeWebSocket()

        await manager.connect(websocket)
        await manager.bind_endpoint(
            websocket,
            endpoint_id="desktop.main",
            connection_id="conn-1",
            provider={"provider_type": "desktop", "display_name": "Desktop"},
        )

        snapshot = await manager.snapshot(endpoint_id="desktop.main")
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["connection_id"], "conn-1")
        self.assertTrue(snapshot[0]["connected"])

        delivered = await manager.publish_notice(
            target_endpoint_id="desktop.main",
            payload={"notice_id": "notice-1", "content": "hello"},
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(websocket.frames[0]["schema"], ENDPOINT_WS_SCHEMA)
        self.assertEqual(websocket.frames[0]["type"], "delivery.notice")

        await manager.disconnect(websocket)
        self.assertEqual(await manager.snapshot(endpoint_id="desktop.main"), [])

    async def test_endpoint_manager_publishes_thread_and_operation_subscriptions(self):
        manager = EndpointWebSocketManager()
        first = _FakeWebSocket()
        second = _FakeWebSocket()

        await manager.connect(first)
        await manager.bind_endpoint(first, endpoint_id="desktop.main", connection_id="conn-1")
        await manager.subscribe(first, target_type="thread", target_id="thr-1", subscription_id="sub-thread")

        await manager.connect(second)
        await manager.bind_endpoint(second, endpoint_id="feishu.chat", connection_id="conn-2")
        await manager.subscribe(second, target_type="operation", target_id="op-1", subscription_id="sub-op")

        run_count = await manager.publish_run_event(
            thread_id="thr-1",
            event={"event_id": "evt-1", "type": "message.delta", "payload": {"delta": "hi"}},
        )
        operation_count = await manager.publish_operation_update(
            operation_id="op-1",
            payload={"operation_id": "op-1", "status": "running"},
        )

        self.assertEqual(run_count, 1)
        self.assertEqual(operation_count, 1)
        self.assertEqual(first.frames[0]["type"], "delivery.run_event")
        self.assertEqual(second.frames[0]["type"], "delivery.operation_update")
        self.assertTrue(manager.has_subscription(target_type="thread", target_id="thr-1"))

    async def test_endpoint_manager_drops_connection_after_send_failure(self):
        manager = EndpointWebSocketManager()
        websocket = _FailingWebSocket()

        await manager.connect(websocket)
        await manager.bind_endpoint(websocket, endpoint_id="desktop.main", connection_id="conn-1")

        delivered = await manager.publish_notice(
            target_endpoint_id="desktop.main",
            payload={"notice_id": "notice-1", "content": "hello"},
        )

        self.assertEqual(delivered, 0)
        self.assertEqual(await manager.connected_endpoint_ids(), set())


if __name__ == "__main__":
    unittest.main()
