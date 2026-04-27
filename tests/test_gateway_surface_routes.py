from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway
from gateway.endpoint_ws import ENDPOINT_WS_SCHEMA


class _EndpointService:
    def __init__(self):
        self.rows: dict[str, SimpleNamespace] = {}
        self.statuses: list[tuple[str, str]] = []

    def ensure_endpoint(self, **kwargs):
        endpoint_id = kwargs["endpoint_id"]
        row = self.rows.get(endpoint_id)
        if row is None:
            row = SimpleNamespace(id=f"row-{len(self.rows) + 1}", **kwargs)
            self.rows[endpoint_id] = row
        else:
            for key, value in kwargs.items():
                setattr(row, key, value)
        return row

    def get_by_endpoint_id(self, endpoint_id: str):
        return self.rows.get(endpoint_id)

    def list_all(self):
        return list(self.rows.values())

    def set_status(self, *, endpoint_id: str, status: str):
        self.statuses.append((endpoint_id, status))
        row = self.rows.get(endpoint_id)
        if row is not None:
            row.status = status
        return row


class _EndpointConnectionService:
    def __init__(self):
        self.connections: list[dict] = []
        self.heartbeats: list[dict] = []
        self.disconnected: list[str] = []

    def upsert_connection(self, **kwargs):
        self.connections.append(dict(kwargs))
        return SimpleNamespace(connection_id=kwargs["connection_id"])

    def heartbeat(self, **kwargs):
        self.heartbeats.append(dict(kwargs))

    def mark_disconnected(self, *, connection_id: str):
        self.disconnected.append(connection_id)


class _EndpointCapabilityService:
    def __init__(self):
        self.snapshots: list[dict] = []

    def replace_snapshot(self, **kwargs):
        self.snapshots.append(dict(kwargs))
        return len(kwargs.get("capabilities") or [])

    def list_for_endpoint(self, *, endpoint_row_id):
        for snapshot in self.snapshots:
            if snapshot.get("endpoint_row_id") == endpoint_row_id:
                return list(snapshot.get("capabilities") or [])
        return []


class _FakeDomain:
    def __init__(self):
        self.services = SimpleNamespace(
            endpoint=_EndpointService(),
            endpoint_connection=_EndpointConnectionService(),
            endpoint_capability=_EndpointCapabilityService(),
            thread=SimpleNamespace(get_by_thread_id=lambda thread_id: None),
            run_event=SimpleNamespace(list_for_thread_after=lambda **kwargs: []),
            operation_call=SimpleNamespace(
                mark_succeeded=lambda **kwargs: None,
                mark_accepted=lambda **kwargs: None,
                mark_progress=lambda **kwargs: None,
                mark_failed=lambda **kwargs: None,
            ),
            tool_router=SimpleNamespace(
                notify_call_result=lambda call_id, result: None,
                notify_call_error=lambda call_id, error: None,
            ),
        )


class GatewaySurfaceRouteTests(unittest.TestCase):
    def test_endpoint_ws_hello_capability_and_subscription_flow(self):
        domain = _FakeDomain()
        gateway = FastAPIGateway(EventBus(), SessionManager(), core_domain=domain, access_token="surface-token")

        with TestClient(gateway.app) as client:
            with client.websocket_connect(
                "/endpoint/ws",
                headers={"Authorization": "Bearer surface-token"},
            ) as websocket:
                websocket.send_json(
                    {
                        "schema": ENDPOINT_WS_SCHEMA,
                        "type": "endpoint.hello",
                        "correlation_id": "hello-1",
                        "payload": {
                            "connection_id": "conn-1",
                            "provider": {"provider_type": "desktop", "provider_id": "desktop-main"},
                            "endpoints": [
                                {
                                    "endpoint_id": "desktop.main.ui",
                                    "endpoint_type": "desktop_ui",
                                    "workspace_ids": ["desktop-main"],
                                },
                                {
                                    "endpoint_id": "desktop.main.executor",
                                    "endpoint_type": "desktop_executor",
                                    "workspace_ids": ["desktop-main"],
                                }
                            ],
                        },
                    }
                )
                hello_ack = websocket.receive_json()
                self.assertEqual(hello_ack["schema"], ENDPOINT_WS_SCHEMA)
                self.assertEqual(hello_ack["type"], "endpoint.hello.ack")
                self.assertEqual(hello_ack["endpoint_id"], "desktop.main.ui")
                self.assertTrue(hello_ack["payload"]["accepted"])

                websocket.send_json(
                    {
                        "schema": ENDPOINT_WS_SCHEMA,
                        "type": "endpoint.capabilities.snapshot",
                        "endpoint_id": "desktop.main.executor",
                        "payload": {
                            "capabilities": [
                                {
                                    "capability_id": "endpoint.desktop.main.executor.file.read",
                                    "tool_key": "file.read",
                                    "risk_level": "read",
                                    "enabled": True,
                                }
                            ]
                        },
                    }
                )
                ready = websocket.receive_json()
                self.assertEqual(ready["type"], "endpoint.ready")
                self.assertEqual(ready["payload"]["registered_capability_count"], 1)

                websocket.send_json(
                    {
                        "schema": ENDPOINT_WS_SCHEMA,
                        "type": "subscription.start",
                        "payload": {
                            "subscription_id": "sub-1",
                            "target_type": "thread",
                            "target_id": "thr-1",
                        },
                    }
                )
                subscription_ack = websocket.receive_json()
                self.assertEqual(subscription_ack["type"], "subscription.ack")
                self.assertEqual(subscription_ack["payload"]["target_type"], "thread")
                self.assertTrue(gateway.endpoint_ws_manager.has_subscription(target_type="thread", target_id="thr-1"))

                endpoints_resp = client.get(
                    "/operator/endpoints",
                    headers={"Authorization": "Bearer surface-token"},
                )
                self.assertEqual(endpoints_resp.status_code, 200)
                endpoints = {item["endpoint_id"]: item for item in endpoints_resp.json()}
                self.assertTrue(endpoints["desktop.main.executor"]["connected"])
                self.assertEqual(endpoints["desktop.main.executor"]["connection_count"], 1)
                self.assertTrue(endpoints["desktop.main.ui"]["connected"])
                self.assertEqual(endpoints["desktop.main.ui"]["connection_count"], 1)

        self.assertIn("desktop.main.ui", domain.services.endpoint.rows)
        self.assertIn("desktop.main.executor", domain.services.endpoint.rows)
        self.assertEqual(domain.services.endpoint_connection.connections[0]["connection_id"], "conn-1")
        self.assertEqual(domain.services.endpoint_capability.snapshots[0]["endpoint_public_id"], "desktop.main.executor")


if __name__ == "__main__":
    unittest.main()
