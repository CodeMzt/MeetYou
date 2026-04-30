from __future__ import annotations

import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.models import Endpoint
from core.services.endpoint_service import EndpointCapabilityService
from gateway.endpoint_frame_handlers import build_default_endpoint_frame_registry
from gateway.endpoint_ws import ENDPOINT_WS_SCHEMA, EndpointWebSocketManager
from gateway.routes.endpoint import _handle_endpoint_frame


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.client = SimpleNamespace(host="127.0.0.1")

    async def send_json(self, frame):
        self.sent.append(frame)


class EndpointProtocolV4Tests(unittest.IsolatedAsyncioTestCase):
    def test_default_endpoint_frame_registry_maps_v4_frame_groups_to_handlers(self):
        names = build_default_endpoint_frame_registry().handler_names()

        self.assertEqual(names["endpoint.hello"], "EndpointHelloHandler")
        self.assertEqual(names["endpoint.capabilities.snapshot"], "CapabilitySnapshotHandler")
        self.assertEqual(names["endpoint.addresses.snapshot"], "AddressHandler")
        self.assertEqual(names["subscription.start"], "SubscriptionHandler")
        self.assertEqual(names["tool.call.result"], "ToolResultHandler")
        self.assertEqual(names["endpoint.heartbeat"], "EndpointLifecycleHandler")

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

    async def test_tool_result_frame_updates_through_tool_router_once(self):
        call_row = SimpleNamespace(call_id="call_1", operation_id="operation-row", status="succeeded")
        operation = SimpleNamespace(
            id="operation-row",
            operation_id="op_1",
            thread_id="thread-row",
            operation_type="tool_call",
            execution_target="desktop.local.executor",
            execution_target_id="desktop.local.executor",
            status="succeeded",
            title="Tool",
            meta={"tool_key": "utility.echo"},
        )
        thread = SimpleNamespace(id="thread-row", thread_id="thr_1")

        class ToolRouter:
            def __init__(self):
                self.result_calls = 0

            async def notify_call_result(self, call_id, result):
                self.result_calls += 1
                self.call_id = call_id
                self.result = dict(result)
                return call_row

        class OperationCall:
            def mark_succeeded(self, **kwargs):
                raise AssertionError(f"tool.call.result should not update operation_call directly: {kwargs}")

        tool_router = ToolRouter()
        published = []
        domain = SimpleNamespace(
            services=SimpleNamespace(
                tool_router=tool_router,
                operation_call=OperationCall(),
                operation=SimpleNamespace(get_by_id=lambda row_id: operation if row_id == "operation-row" else None),
                thread=SimpleNamespace(get_by_id=lambda row_id: thread if row_id == "thread-row" else None),
            )
        )

        class Gateway:
            def _require_core_domain(self):
                return domain

            async def _safe_send_json(self, websocket, frame):
                websocket.sent.append(frame)

            async def publish_endpoint_operation_update(self, **kwargs):
                published.append(dict(kwargs))

        await _handle_endpoint_frame(
            Gateway(),
            FakeWebSocket(),
            {
                "schema": ENDPOINT_WS_SCHEMA,
                "type": "tool.call.result",
                "payload": {"call_id": "call_1", "result": {"echo": "ok"}},
            },
            {},
        )

        self.assertEqual(tool_router.result_calls, 1)
        self.assertEqual(tool_router.call_id, "call_1")
        self.assertEqual(tool_router.result, {"echo": "ok"})
        self.assertEqual(published[0]["operation_id"], "op_1")
        self.assertEqual(published[0]["payload"]["phase"], "completed")

    def test_capability_snapshot_disables_removed_tools(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        try:
            with Session() as session:
                endpoint = Endpoint(
                    endpoint_id="desktop.local.executor",
                    endpoint_type="desktop_executor",
                    provider_type="desktop",
                    transport_type="websocket",
                )
                session.add(endpoint)
                session.commit()
                endpoint_row_id = endpoint.id

            service = EndpointCapabilityService(Session)
            service.replace_snapshot(
                endpoint_row_id=endpoint_row_id,
                endpoint_public_id="desktop.local.executor",
                capabilities=[
                    {"tool_key": "utility.echo"},
                    {"tool_key": "file.read"},
                ],
            )
            service.replace_snapshot(
                endpoint_row_id=endpoint_row_id,
                endpoint_public_id="desktop.local.executor",
                capabilities=[
                    {"tool_key": "utility.echo"},
                ],
            )
            capabilities = {row.tool_key: row for row in service.list_for_endpoint(endpoint_row_id=endpoint_row_id)}

            self.assertTrue(capabilities["utility.echo"].enabled)
            self.assertFalse(capabilities["file.read"].enabled)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
