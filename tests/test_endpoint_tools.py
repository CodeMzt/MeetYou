from __future__ import annotations

import unittest
raise unittest.SkipTest("Legacy endpoint Agent tool tests were replaced by Client tool target coverage.")
from types import SimpleNamespace

from tools.endpoint_tools import EndpointTools


class _FakeAgentWsManager:
    def __init__(self, online_agent_ids: set[str] | None = None):
        self.online_agent_ids = set(online_agent_ids or set())
        self.sent: list[tuple[str, dict]] = []

    async def connected_agent_ids(self):
        return set(self.online_agent_ids)

    async def snapshot(self):
        return [{"agent_id": agent_id, "connected_at": "2026-04-25T00:00:00Z"} for agent_id in sorted(self.online_agent_ids)]

    async def send_to_agent(self, agent_id: str, payload: dict) -> bool:
        if agent_id not in self.online_agent_ids:
            return False
        self.sent.append((agent_id, payload))
        return True


class _FakeClientWsManager:
    def __init__(self, snapshots: list[dict]):
        self._snapshots = [dict(item) for item in snapshots]
        self.published: list[dict] = []

    async def snapshot(self, **filters):
        rows = [dict(item) for item in self._snapshots]
        for key, value in filters.items():
            normalized = str(value or "").strip()
            if normalized:
                rows = [item for item in rows if str(item.get(key) or "").strip() == normalized]
        return rows

    async def publish_client_event(self, client_id: str, *, event_type: str, payload: dict, thread_id: str = "", session_id: str = "", workspace_id: str = "") -> int:
        matches = [
            item
            for item in self._snapshots
            if str(item.get("client_id") or "") == client_id
            and (not thread_id or str(item.get("thread_id") or "") == thread_id)
            and (not session_id or str(item.get("session_id") or "") == session_id)
            and (not workspace_id or str(item.get("workspace_id") or "") == workspace_id)
        ]
        if matches:
            self.published.append(
                {
                    "client_id": client_id,
                    "event_type": event_type,
                    "payload": dict(payload or {}),
                    "thread_id": thread_id,
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "count": len(matches),
                }
            )
        return len(matches)


class _FakeGateway:
    def __init__(self, *, online_agent_ids: set[str] | None = None, client_snapshots: list[dict] | None = None):
        self.agent_ws_manager = _FakeAgentWsManager(online_agent_ids)
        self.client_ws_manager = _FakeClientWsManager(client_snapshots or [])


class _FakeDomain:
    def __init__(self):
        self.agent = SimpleNamespace(agent_id="desktop-main-agent", owner_client_id="client-row-1", status="online")
        self.client = SimpleNamespace(id="client-row-1", client_id="desktop-app")
        self.agent_dispatch = _FakeAgentDispatch()
        self.services = SimpleNamespace(
            agent=SimpleNamespace(
                get_by_agent_id=self._get_agent_by_id,
                list_agents=lambda: [self.agent],
                is_bound_to_workspace=lambda **kwargs: True,
            ),
            client=SimpleNamespace(
                get_by_id=self._get_client_by_id,
                get_by_client_id=self._get_client_by_client_id,
            ),
        )

    def _get_agent_by_id(self, agent_id: str):
        return self.agent if agent_id == self.agent.agent_id else None

    def _get_client_by_id(self, row_id: str):
        return self.client if row_id == self.agent.owner_client_id else None

    def _get_client_by_client_id(self, client_id: str):
        return self.client if client_id == self.client.client_id else None


class _FakeAgentDispatch:
    def __init__(self):
        self.calls: list[dict] = []

    def resolve_specific_capability(self, *, agent_id: str, capability_ref: str, workspace_id: str = ""):
        if agent_id == "desktop-main-agent" and capability_ref == "file.read":
            return SimpleNamespace(capability_id="agent.desktop-main-agent.file.read")
        return None

    async def dispatch_specific_agent_capability(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"summary": "read ok"}


class EndpointToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_notice_delivers_to_agent_and_owner_client(self):
        gateway = _FakeGateway(
            online_agent_ids={"desktop-main-agent"},
            client_snapshots=[
                {
                    "client_id": "desktop-app",
                    "thread_id": "thr-1",
                    "session_id": "sess-1",
                    "workspace_id": "desktop-main",
                }
            ],
        )
        tools = EndpointTools()
        tools.set_core_domain(_FakeDomain())
        tools.set_runtime(gateway_getter=lambda: gateway)

        result = await tools.send_endpoint_message(
            target_type="agent",
            target_id="desktop-main-agent",
            delivery_kind="notice",
            content="desktop notice",
            session_id="sess-1",
            workspace_id="desktop-main",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["owner_client_id"], "desktop-app")
        self.assertEqual(result["owner_client_connection_count"], 1)
        self.assertEqual(gateway.agent_ws_manager.sent[0][0], "desktop-main-agent")
        self.assertEqual(gateway.agent_ws_manager.sent[0][1]["type"], "agent.message")
        self.assertEqual(gateway.agent_ws_manager.sent[0][1]["payload"]["event_type"], "notice")
        self.assertEqual(gateway.client_ws_manager.published[0]["event_type"], "message.created")
        owner_message = gateway.client_ws_manager.published[0]["payload"]["message"]
        self.assertEqual(owner_message["channel"], "notice")
        self.assertEqual(owner_message["metadata"]["target_type"], "agent")
        self.assertEqual(owner_message["metadata"]["target_id"], "desktop-main-agent")

    async def test_client_notice_delivers_to_all_matching_client_connections(self):
        gateway = _FakeGateway(
            client_snapshots=[
                {
                    "client_id": "feishu-oc-test",
                    "thread_id": "thr-1",
                    "session_id": "sess-1",
                    "workspace_id": "personal",
                },
                {
                    "client_id": "feishu-oc-test",
                    "thread_id": "thr-2",
                    "session_id": "sess-2",
                    "workspace_id": "personal",
                },
            ],
        )
        tools = EndpointTools()
        tools.set_core_domain(_FakeDomain())
        tools.set_runtime(gateway_getter=lambda: gateway)

        result = await tools.send_endpoint_message(
            target_type="client",
            target_id="feishu-oc-test",
            delivery_kind="notice",
            content="client notice",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["connection_count"], 2)
        self.assertEqual(len(result["message_ids"]), 2)
        self.assertEqual(len(gateway.client_ws_manager.published), 2)
        self.assertEqual(
            {item["session_id"] for item in gateway.client_ws_manager.published},
            {"sess-1", "sess-2"},
        )

    async def test_client_capability_call_routes_to_online_owned_agent(self):
        gateway = _FakeGateway(
            online_agent_ids={"desktop-main-agent"},
            client_snapshots=[
                {
                    "client_id": "desktop-app",
                    "thread_id": "thr-1",
                    "session_id": "sess-1",
                    "workspace_id": "desktop-main",
                }
            ],
        )
        domain = _FakeDomain()
        tools = EndpointTools()
        tools.set_core_domain(domain)
        tools.set_runtime(gateway_getter=lambda: gateway)

        result = await tools.send_endpoint_message(
            target_type="client",
            target_id="desktop-app",
            delivery_kind="capability_call",
            capability_ref="file.read",
            arguments={"path": "demo.txt"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["agent_id"], "desktop-main-agent")
        self.assertEqual(result["result"], {"summary": "read ok"})
        self.assertEqual(domain.agent_dispatch.calls[0]["capability_ref"], "file.read")
        self.assertEqual(domain.agent_dispatch.calls[0]["session_id"], "sess-1")
        self.assertEqual(domain.agent_dispatch.calls[0]["workspace_id"], "desktop-main")


if __name__ == "__main__":
    unittest.main()
