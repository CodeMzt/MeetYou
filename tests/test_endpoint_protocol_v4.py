from __future__ import annotations

import unittest

from gateway.endpoint_ws import ENDPOINT_WS_SCHEMA, EndpointWebSocketManager


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, frame):
        self.sent.append(frame)


class EndpointProtocolV4Tests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_manager_routes_delivery_by_subscription(self):
        manager = EndpointWebSocketManager()
        websocket = FakeWebSocket()
        await manager.connect(websocket)
        await manager.bind_endpoint(
            websocket,
            endpoint_id="desktop.home.executor",
            connection_id="conn_1",
            provider={"provider_type": "desktop", "provider_id": "home"},
        )
        await manager.subscribe(websocket, target_type="thread", target_id="thr_1", subscription_id="sub_1")

        delivered = await manager.publish_run_event(
            thread_id="thr_1",
            run_id="run_1",
            event={"event_id": "evt_1", "seq": 1, "type": "assistant.progress_notice"},
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(websocket.sent[0]["schema"], ENDPOINT_WS_SCHEMA)
        self.assertEqual(websocket.sent[0]["type"], "delivery.run_event")
        self.assertEqual(websocket.sent[0]["payload"]["type"], "assistant.progress_notice")

    async def test_endpoint_manager_fans_out_persisted_message_by_thread_subscription(self):
        manager = EndpointWebSocketManager()
        websocket = FakeWebSocket()
        await manager.connect(websocket)
        await manager.bind_endpoint(
            websocket,
            endpoint_id="desktop.home.ui",
            connection_id="conn_1",
            provider={"provider_type": "desktop", "provider_id": "home"},
        )
        await manager.subscribe(websocket, target_type="thread", target_id="thr_1", subscription_id="sub_1")

        delivered = await manager.publish_message(
            thread_id="thr_1",
            payload={"message_id": "msg_1", "thread_id": "thr_1", "role": "assistant", "content": "ok"},
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(websocket.sent[0]["schema"], ENDPOINT_WS_SCHEMA)
        self.assertEqual(websocket.sent[0]["type"], "delivery.message")
        self.assertEqual(websocket.sent[0]["payload"]["role"], "assistant")


if __name__ == "__main__":
    unittest.main()
