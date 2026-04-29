from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from gateway.routes.endpoint import _handle_endpoint_frame
from tools.endpoint_tools import EndpointTools


def _row(**kwargs):
    return SimpleNamespace(**kwargs)


class _EndpointAddressService:
    def __init__(self):
        self.rows = []

    def upsert_address(self, **kwargs):
        row = _row(
            id=f"address-row-{len(self.rows) + 1}",
            address_id=kwargs["address_id"],
            endpoint_id=kwargs["endpoint_row_id"],
            provider_type=kwargs["provider_type"],
            address_type=kwargs["address_type"],
            external_ref=kwargs["external_ref"],
            display_name=kwargs.get("display_name", ""),
            workspace_scope=kwargs.get("workspace_scope") or [],
            status=kwargs.get("status", "sendable"),
            capabilities=kwargs.get("capabilities") or [],
            last_seen_at=kwargs.get("last_seen_at"),
            last_verified_at=kwargs.get("last_verified_at"),
            meta=kwargs.get("metadata") or {},
        )
        for index, existing in enumerate(self.rows):
            if existing.address_id == row.address_id:
                self.rows[index] = row
                return row
        self.rows.append(row)
        return row

    def list_addresses(self, **kwargs):
        provider_type = kwargs.get("provider_type", "")
        rows = self.rows
        if provider_type:
            rows = [row for row in rows if row.provider_type == provider_type]
        return rows

    def get_by_address_id(self, address_id):
        return next((row for row in self.rows if row.address_id == address_id), None)

    def get_by_id(self, row_id):
        return next((row for row in self.rows if row.id == row_id), None)

    def delete_address(self, *, address_id):
        before = len(self.rows)
        self.rows = [row for row in self.rows if row.address_id != address_id]
        return len(self.rows) != before


class _PreferenceService:
    def __init__(self):
        self.rows = []

    def upsert_preference(self, **kwargs):
        row = _row(
            id=f"pref-row-{len(self.rows) + 1}",
            preference_id=f"pref-{len(self.rows) + 1}",
            actor_id=kwargs["actor_row_id"],
            provider_type=kwargs["provider_type"],
            address_id=kwargs["address_row_id"],
            alias=kwargs.get("alias", "me"),
            is_default=kwargs.get("is_default", True),
            verified=kwargs.get("verified", True),
            meta=kwargs.get("metadata") or {},
        )
        self.rows.append(row)
        return row

    def list_for_actor(self, **kwargs):
        return [row for row in self.rows if row.actor_id == kwargs["actor_row_id"]]

    def get_default(self, **kwargs):
        provider_type = kwargs["provider_type"]
        return next((row for row in self.rows if row.provider_type == provider_type and row.is_default), None)


class _DeliveryService:
    def __init__(self):
        self.calls = []

    async def deliver_to_address(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"sent": True, "status": "sent"}


class _FakeGateway:
    def __init__(self, domain):
        self.domain = domain
        self.sent = []

    def _require_core_domain(self):
        return self.domain

    async def _safe_send_json(self, websocket, frame):
        self.sent.append(frame)
        websocket.sent.append(frame)


class _FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.client = SimpleNamespace(host="127.0.0.1")


class EndpointAddressProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_address_snapshot_registers_provider_addresses(self):
        endpoint = _row(id="endpoint-row-1", endpoint_id="feishu.provider.ui", provider_type="feishu")
        address_service = _EndpointAddressService()
        domain = _row(
            services=_row(
                endpoint=_row(get_by_endpoint_id=lambda endpoint_id: endpoint),
                endpoint_address=address_service,
            )
        )
        gateway = _FakeGateway(domain)
        websocket = _FakeWebSocket()

        await _handle_endpoint_frame(
            gateway,
            websocket,
            {
                "schema": "meetyou.endpoint.ws.v4",
                "type": "endpoint.addresses.snapshot",
                "endpoint_id": "feishu.provider.ui",
                "payload": {
                    "addresses": [
                        {
                            "address_id": "addr.feishu.direct.chat-1",
                            "provider_type": "feishu",
                            "address_type": "direct",
                            "external_ref": "chat-1",
                            "display_name": "Feishu Chat",
                        }
                    ]
                },
            },
            {"endpoint_id": "feishu.provider.ui"},
        )

        self.assertEqual(len(address_service.rows), 1)
        self.assertEqual(address_service.rows[0].external_ref, "chat-1")
        self.assertEqual(websocket.sent[0]["type"], "endpoint.addresses.ack")

    async def test_endpoint_address_upsert_and_delete_frames(self):
        endpoint = _row(id="endpoint-row-1", endpoint_id="wechat.provider.ui", provider_type="wechat")
        address_service = _EndpointAddressService()
        domain = _row(
            services=_row(
                endpoint=_row(get_by_endpoint_id=lambda endpoint_id: endpoint),
                endpoint_address=address_service,
            )
        )
        gateway = _FakeGateway(domain)
        websocket = _FakeWebSocket()

        await _handle_endpoint_frame(
            gateway,
            websocket,
            {
                "schema": "meetyou.endpoint.ws.v4",
                "type": "endpoint.address.upsert",
                "endpoint_id": "wechat.provider.ui",
                "payload": {
                    "address": {
                        "address_id": "addr.wechat.direct.chat-1",
                        "address_type": "direct",
                        "external_ref": "chat-1",
                    }
                },
            },
            {"endpoint_id": "wechat.provider.ui"},
        )
        await _handle_endpoint_frame(
            gateway,
            websocket,
            {
                "schema": "meetyou.endpoint.ws.v4",
                "type": "endpoint.address.delete",
                "endpoint_id": "wechat.provider.ui",
                "payload": {"address_id": "addr.wechat.direct.chat-1"},
            },
            {"endpoint_id": "wechat.provider.ui"},
        )

        self.assertEqual(websocket.sent[0]["type"], "endpoint.addresses.ack")
        self.assertEqual(websocket.sent[1]["type"], "endpoint.address.delete.ack")
        self.assertTrue(websocket.sent[1]["payload"]["deleted"])
        self.assertEqual(address_service.rows, [])


class EndpointAddressToolTests(unittest.IsolatedAsyncioTestCase):
    def _tools(self):
        endpoint = _row(id="endpoint-row-1", endpoint_id="feishu.provider.ui")
        actor = _row(id="actor-row-1", actor_id="user:self")
        addresses = _EndpointAddressService()
        address = addresses.upsert_address(
            endpoint_row_id=endpoint.id,
            provider_type="feishu",
            address_type="direct",
            external_ref="chat-1",
            address_id="addr.feishu.direct.chat-1",
            display_name="Feishu Chat",
            workspace_scope=["personal"],
            status="sendable",
            capabilities=["receive_message"],
            last_seen_at=datetime.now(timezone.utc),
            last_verified_at=datetime.now(timezone.utc),
            metadata={},
        )
        preferences = _PreferenceService()
        delivery = _DeliveryService()
        domain = _row(
            principal=_row(principal_key="self", display_name="Self"),
            services=_row(
                actor=_row(
                    get_by_actor_id=lambda actor_id: actor if actor_id == "user:self" else None,
                    ensure_actor=lambda **kwargs: actor,
                ),
                endpoint=_row(
                    get_by_id=lambda row_id: endpoint if row_id == endpoint.id else None,
                    get_by_endpoint_id=lambda endpoint_id: endpoint if endpoint_id == endpoint.endpoint_id else None,
                ),
                endpoint_address=addresses,
                actor_delivery_preference=preferences,
                delivery=delivery,
            ),
        )
        tools = EndpointTools()
        tools.set_core_domain(domain)
        return tools, address, preferences, delivery

    async def test_actor_binding_and_send_delivery_message_use_endpoint_address(self):
        tools, address, preferences, delivery = self._tools()

        before = await tools.list_delivery_targets(provider_type="feishu", actor_ref="me")
        self.assertTrue(before["requires_binding"])

        bound = await tools.set_delivery_preference(provider_type="feishu", address_id=address.address_id)
        self.assertTrue(bound["ok"])
        self.assertEqual(len(preferences.rows), 1)

        sent = await tools.send_delivery_message(content="hello", actor_ref="me", provider_type="feishu")
        self.assertTrue(sent["ok"])
        self.assertTrue(sent["delivered"])
        self.assertEqual(delivery.calls[0]["target_address"].address_id, address.address_id)


if __name__ == "__main__":
    unittest.main()
