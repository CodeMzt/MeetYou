from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlsplit

import aiohttp

from endpoint_providers.runtime_connection import EndpointRuntimeConnection, EndpointRuntimeConnectionError
from endpoint_tool_sdk.protocol import ENDPOINT_TOOL_PROTOCOL_SCHEMA


class EndpointRuntimeConnectionTests(unittest.TestCase):
    def test_endpoint_ws_url_includes_stable_endpoint_identity(self):
        connection = EndpointRuntimeConnection(
            base_url="http://127.0.0.1:8000",
            provider_id="feishu-oc-test",
            provider_type="feishu",
            display_name="Feishu OC Test",
            workspace_id="personal",
            thread_id="thr-1",
        )
        connection.session_id = "sess-1"

        parsed = urlsplit(connection._build_endpoint_ws_url())
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


class EndpointRuntimeConnectionAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_only_endpoint_does_not_create_thread_binding(self):
        calls = []

        class _ContextConnection(EndpointRuntimeConnection):
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

        connection = _ContextConnection(
            base_url="http://127.0.0.1:8000",
            provider_id="feishu-provider",
            provider_type="feishu",
            display_name="Feishu Provider",
            workspace_id="personal",
            thread_title="Feishu Provider",
            bind_thread=False,
        )

        await connection.ensure_context()

        self.assertEqual(connection.thread_id, "")
        self.assertEqual(connection.session_id, "")
        self.assertEqual(calls, [])

    async def test_thread_bound_endpoint_resolves_endpoint_owned_session(self):
        calls = []

        class _ContextConnection(EndpointRuntimeConnection):
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

        connection = _ContextConnection(
            base_url="http://127.0.0.1:8000",
            provider_id="feishu-chat-oc-test",
            provider_type="feishu",
            display_name="Feishu OC Test",
            workspace_id="personal",
            thread_title="Feishu Chat oc_test",
            conversation_key="feishu:chat:oc_test",
            thread_strategy="per_conversation",
        )

        await connection.ensure_context()

        self.assertEqual(connection.thread_id, "thr-chat")
        self.assertEqual(connection.session_id, "sess-chat")
        self.assertEqual([item[1] for item in calls], ["/runtime/workspaces", "/runtime/endpoint-sessions/resolve"])
        self.assertEqual(calls[1][3]["endpoint_id"], "feishu.feishu-chat-oc-test.ui")
        self.assertEqual(calls[1][3]["conversation_key"], "feishu:chat:oc_test")
        self.assertEqual(calls[1][3]["thread_strategy"], "per_conversation")
        self.assertEqual(calls[1][3]["title"], "Feishu Chat oc_test")

    async def test_send_message_rebinds_after_deleted_thread_context(self):
        calls = []
        resolve_count = 0

        class _ContextConnection(EndpointRuntimeConnection):
            async def start(self):
                await self.ensure_context()

            async def request_json(self, method, path, *, params=None, json_body=None):
                nonlocal resolve_count
                calls.append((method, path, dict(params or {}), dict(json_body or {})))
                if path == "/runtime/workspaces":
                    return [{"workspace_id": "personal"}]
                if path == "/runtime/endpoint-sessions/resolve":
                    resolve_count += 1
                    if resolve_count == 1:
                        return {
                            "thread": {"thread_id": "thr-old"},
                            "session": {"session_id": "sess-old", "thread_id": "thr-old"},
                            "binding": {"binding_id": "etb.1"},
                        }
                    return {
                        "thread": {"thread_id": "thr-new"},
                        "session": {"session_id": "sess-new", "thread_id": "thr-new"},
                        "binding": {"binding_id": "etb.1"},
                    }
                if path == "/runtime/messages":
                    if json_body.get("thread_id") == "thr-old":
                        raise EndpointRuntimeConnectionError(
                            "404 Unknown thread: thr-old",
                            status_code=404,
                            code="thread_not_found",
                        )
                    return {
                        "message_id": "msg-new",
                        "thread_id": json_body.get("thread_id"),
                        "session_id": json_body.get("session_id"),
                    }
                raise AssertionError(path)

        connection = _ContextConnection(
            base_url="http://127.0.0.1:8000",
            provider_id="meetwechat-chat-test",
            provider_type="wechat",
            display_name="MeetWeChat private test",
            workspace_id="personal",
            conversation_key="wechat:meetwechat:chat:chat-1",
            thread_strategy="per_conversation",
        )

        response = await connection.send_message("hello", endpoint_message_id="evt-1")

        message_calls = [item for item in calls if item[1] == "/runtime/messages"]
        self.assertEqual(resolve_count, 2)
        self.assertEqual([item[3]["thread_id"] for item in message_calls], ["thr-old", "thr-new"])
        self.assertEqual(response["thread_id"], "thr-new")
        self.assertEqual(connection.thread_id, "thr-new")
        self.assertEqual(connection.session_id, "sess-new")

    async def test_endpoint_subscription_disables_replay_for_external_side_effect_providers(self):
        connection = EndpointRuntimeConnection(
            base_url="http://127.0.0.1:8000",
            provider_id="feishu-oc-test",
            provider_type="feishu",
            display_name="Feishu OC Test",
            workspace_id="personal",
            thread_id="thr-1",
        )
        connection.session_id = "sess-1"
        ws = _FakeWs()
        connection._http_session = _FakeHttpSession(ws)  # noqa: SLF001

        async def _noop():
            return None

        connection.ensure_context = _noop  # type: ignore[method-assign]
        connection._ensure_http_session = _noop  # type: ignore[method-assign]  # noqa: SLF001

        await connection._connect_ws()  # noqa: SLF001

        self.assertEqual(ws.sent[0]["type"], "endpoint.hello")
        self.assertEqual(ws.sent[0]["payload"]["protocol"]["schema"], ENDPOINT_TOOL_PROTOCOL_SCHEMA)
        self.assertEqual(ws.sent[0]["payload"]["protocol"]["version"], 4)
        self.assertEqual(ws.sent[1]["type"], "subscription.start")
        self.assertFalse(ws.sent[1]["payload"]["replay"])

    async def test_provider_only_endpoint_connects_without_thread_subscription(self):
        connection = EndpointRuntimeConnection(
            base_url="http://127.0.0.1:8000",
            provider_id="meetwechat-provider",
            provider_type="wechat",
            display_name="MeetWeChat Provider",
            workspace_id="personal",
            endpoint_id="wechat.provider.ui",
            bind_thread=False,
        )
        ws = _FakeWs()
        connection._http_session = _FakeHttpSession(ws)  # noqa: SLF001

        async def _noop():
            return None

        connection._ensure_http_session = _noop  # type: ignore[method-assign]  # noqa: SLF001

        await connection._connect_ws()  # noqa: SLF001

        self.assertEqual([item["type"] for item in ws.sent], ["endpoint.hello"])
        self.assertEqual(ws.sent[0]["endpoint_id"], "wechat.provider.ui")
        self.assertEqual(ws.sent[0]["payload"]["protocol"]["schema"], ENDPOINT_TOOL_PROTOCOL_SCHEMA)

    async def test_start_readiness_waits_for_subscription_ack_not_hello_ack(self):
        observed = []
        connection = EndpointRuntimeConnection(
            base_url="http://127.0.0.1:8000",
            provider_id="feishu-oc-test",
            provider_type="feishu",
            display_name="Feishu OC Test",
            workspace_id="personal",
            thread_id="thr-1",
            event_handler=lambda payload: observed.append(
                (
                    payload.get("type"),
                    connection._ws_connected.is_set(),  # noqa: SLF001
                    connection._subscription_acknowledged.is_set(),  # noqa: SLF001
                )
            ),
        )
        connection._ws = _FakeIncomingWs(  # noqa: SLF001
            [
                {"type": "endpoint.hello.ack"},
                {"type": "subscription.ack"},
            ]
        )

        await connection._read_ws()  # noqa: SLF001

        self.assertEqual(observed[0], ("endpoint.hello.ack", False, False))
        self.assertEqual(observed[1], ("subscription.ack", True, True))

    async def test_provider_only_start_readiness_waits_for_hello_ack(self):
        observed = []
        connection = EndpointRuntimeConnection(
            base_url="http://127.0.0.1:8000",
            provider_id="meetwechat-provider",
            provider_type="wechat",
            display_name="MeetWeChat Provider",
            workspace_id="personal",
            bind_thread=False,
            event_handler=lambda payload: observed.append(
                (
                    payload.get("type"),
                    connection._ws_connected.is_set(),  # noqa: SLF001
                    connection._subscription_acknowledged.is_set(),  # noqa: SLF001
                )
            ),
        )
        connection._ws = _FakeIncomingWs(  # noqa: SLF001
            [
                {"type": "endpoint.hello.ack"},
            ]
        )

        await connection._read_ws()  # noqa: SLF001

        self.assertEqual(observed[0], ("endpoint.hello.ack", True, True))


if __name__ == "__main__":
    unittest.main()
