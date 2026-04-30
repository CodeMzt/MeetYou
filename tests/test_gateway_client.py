from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlsplit

import aiohttp

from clients.gateway_client import GatewayConversationClient


class GatewayConversationClientTests(unittest.TestCase):
    def test_endpoint_ws_url_includes_stable_endpoint_identity(self):
        client = GatewayConversationClient(
            base_url="http://127.0.0.1:8000",
            provider_id="feishu-oc-test",
            provider_type="feishu",
            display_name="Feishu OC Test",
            workspace_id="personal",
            thread_id="thr-1",
        )
        client.session_id = "sess-1"

        parsed = urlsplit(client._build_endpoint_ws_url())
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.path, "/endpoint/ws")
        self.assertEqual(query["thread_id"], ["thr-1"])
        self.assertEqual(query["session_id"], ["sess-1"])
        self.assertEqual(query["endpoint_id"], ["feishu.feishu-oc-test.ui"])
        self.assertEqual(query["provider_id"], ["feishu-oc-test"])
        self.assertEqual(query["provider_type"], ["feishu"])
        self.assertEqual(query["display_name"], ["Feishu OC Test"])
        self.assertEqual(query["workspace_id"], ["personal"])


class _FakeWs:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(dict(payload))


class _FakeHttpSession:
    def __init__(self, ws):
        self.ws = ws

    async def ws_connect(self, *args, **kwargs):
        del args, kwargs
        return self.ws


class _FakeWsMessage:
    def __init__(self, payload):
        self.type = aiohttp.WSMsgType.TEXT
        self._payload = payload

    def json(self, loads=None):
        del loads
        return dict(self._payload)


class _FakeIncomingWs:
    def __init__(self, payloads):
        self._messages = [_FakeWsMessage(payload) for payload in payloads]

    def __aiter__(self):
        self._iter = iter(self._messages)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class GatewayConversationClientAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_only_endpoint_does_not_create_thread_binding(self):
        calls = []

        class _ContextClient(GatewayConversationClient):
            async def request_json(self, method, path, *, params=None, json_body=None):
                calls.append((method, path, dict(params or {}), dict(json_body or {})))
                if path == "/runtime/workspaces":
                    return [{"workspace_id": "personal"}]
                if path == "/runtime/endpoint-sessions/resolve":
                    return {
                        "thread": {"thread_id": "thr-provider"},
                        "session": {"session_id": "sess-provider", "thread_id": "thr-provider"},
                        "binding": {"binding_id": "etb.1"},
                    }
                raise AssertionError(path)

        client = _ContextClient(
            base_url="http://127.0.0.1:8000",
            provider_id="feishu-provider",
            provider_type="feishu",
            display_name="Feishu Provider",
            workspace_id="personal",
            thread_title="Feishu Provider",
            bind_thread=False,
        )

        await client.ensure_context()

        self.assertEqual(client.thread_id, "")
        self.assertEqual(client.session_id, "")
        self.assertEqual(calls, [])

    async def test_thread_bound_endpoint_resolves_endpoint_owned_session(self):
        calls = []

        class _ContextClient(GatewayConversationClient):
            async def request_json(self, method, path, *, params=None, json_body=None):
                calls.append((method, path, dict(params or {}), dict(json_body or {})))
                if path == "/runtime/workspaces":
                    return [{"workspace_id": "personal"}]
                if path == "/runtime/endpoint-sessions/resolve":
                    return {
                        "thread": {"thread_id": "thr-chat"},
                        "session": {"session_id": "sess-chat", "thread_id": "thr-chat"},
                        "binding": {"binding_id": "etb.1"},
                    }
                raise AssertionError(path)

        client = _ContextClient(
            base_url="http://127.0.0.1:8000",
            provider_id="feishu-chat-oc-test",
            provider_type="feishu",
            display_name="Feishu OC Test",
            workspace_id="personal",
            thread_title="Feishu Chat oc_test",
            conversation_key="feishu:chat:oc_test",
            thread_strategy="per_conversation",
        )

        await client.ensure_context()

        self.assertEqual(client.thread_id, "thr-chat")
        self.assertEqual(client.session_id, "sess-chat")
        self.assertEqual([item[1] for item in calls], ["/runtime/workspaces", "/runtime/endpoint-sessions/resolve"])
        self.assertEqual(calls[1][3]["endpoint_id"], "feishu.feishu-chat-oc-test.ui")
        self.assertEqual(calls[1][3]["conversation_key"], "feishu:chat:oc_test")
        self.assertEqual(calls[1][3]["thread_strategy"], "per_conversation")
        self.assertEqual(calls[1][3]["title"], "Feishu Chat oc_test")

    async def test_endpoint_subscription_disables_replay_for_external_side_effect_clients(self):
        client = GatewayConversationClient(
            base_url="http://127.0.0.1:8000",
            provider_id="feishu-oc-test",
            provider_type="feishu",
            display_name="Feishu OC Test",
            workspace_id="personal",
            thread_id="thr-1",
        )
        client.session_id = "sess-1"
        ws = _FakeWs()
        client._http_session = _FakeHttpSession(ws)  # noqa: SLF001

        async def _noop():
            return None

        client.ensure_context = _noop  # type: ignore[method-assign]
        client._ensure_http_session = _noop  # type: ignore[method-assign]  # noqa: SLF001

        await client._connect_ws()  # noqa: SLF001

        self.assertEqual(ws.sent[1]["type"], "subscription.start")
        self.assertFalse(ws.sent[1]["payload"]["replay"])

    async def test_provider_only_endpoint_connects_without_thread_subscription(self):
        client = GatewayConversationClient(
            base_url="http://127.0.0.1:8000",
            provider_id="meetwechat-provider",
            provider_type="wechat",
            display_name="MeetWeChat Provider",
            workspace_id="personal",
            endpoint_id="wechat.provider.ui",
            bind_thread=False,
        )
        ws = _FakeWs()
        client._http_session = _FakeHttpSession(ws)  # noqa: SLF001

        async def _noop():
            return None

        client._ensure_http_session = _noop  # type: ignore[method-assign]  # noqa: SLF001

        await client._connect_ws()  # noqa: SLF001

        self.assertEqual([item["type"] for item in ws.sent], ["endpoint.hello"])
        self.assertEqual(ws.sent[0]["endpoint_id"], "wechat.provider.ui")

    async def test_start_readiness_waits_for_subscription_ack_not_hello_ack(self):
        observed = []
        client = GatewayConversationClient(
            base_url="http://127.0.0.1:8000",
            provider_id="feishu-oc-test",
            provider_type="feishu",
            display_name="Feishu OC Test",
            workspace_id="personal",
            thread_id="thr-1",
            event_handler=lambda payload: observed.append(
                (
                    payload.get("type"),
                    client._ws_connected.is_set(),  # noqa: SLF001
                    client._subscription_acknowledged.is_set(),  # noqa: SLF001
                )
            ),
        )
        client._ws = _FakeIncomingWs(  # noqa: SLF001
            [
                {"type": "endpoint.hello.ack"},
                {"type": "subscription.ack"},
            ]
        )

        await client._read_ws()  # noqa: SLF001

        self.assertEqual(observed[0], ("endpoint.hello.ack", False, False))
        self.assertEqual(observed[1], ("subscription.ack", True, True))

    async def test_provider_only_start_readiness_waits_for_hello_ack(self):
        observed = []
        client = GatewayConversationClient(
            base_url="http://127.0.0.1:8000",
            provider_id="meetwechat-provider",
            provider_type="wechat",
            display_name="MeetWeChat Provider",
            workspace_id="personal",
            bind_thread=False,
            event_handler=lambda payload: observed.append(
                (
                    payload.get("type"),
                    client._ws_connected.is_set(),  # noqa: SLF001
                    client._subscription_acknowledged.is_set(),  # noqa: SLF001
                )
            ),
        )
        client._ws = _FakeIncomingWs(  # noqa: SLF001
            [
                {"type": "endpoint.hello.ack"},
            ]
        )

        await client._read_ws()  # noqa: SLF001

        self.assertEqual(observed[0], ("endpoint.hello.ack", True, True))


if __name__ == "__main__":
    unittest.main()
