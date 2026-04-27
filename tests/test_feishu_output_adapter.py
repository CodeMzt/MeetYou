import json
import os
import sys
import types
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _FakeClientSession:
    async def close(self):
        return None


sys.modules.setdefault("aiohttp", types.SimpleNamespace(ClientSession=_FakeClientSession))

from core.io_protocol import EventTarget, EventType, StreamEventType, make_source
from sensors.feishu_output_adapter import FeishuOutputAdapter


def _run_event(event: dict) -> dict:
    return {
        "schema": "meetyou.endpoint.ws.v4",
        "type": "delivery.run_event",
        "payload": {
            "type": event.get("type"),
            "stream_id": event.get("stream_id", ""),
            "turn_id": event.get("turn_id", ""),
            "payload": dict(event),
        },
    }


def _notice(content: str) -> dict:
    return {
        "schema": "meetyou.endpoint.ws.v4",
        "type": "delivery.notice",
        "payload": {"content": content},
    }


class FakeConfig:
    def __init__(self, values):
        self._values = values

    def get(self, key):
        return self._values.get(key)


class FakeResponse:
    def __init__(self, status=200, json_data=None, text_data=""):
        self.status = status
        self._json_data = json_data
        self._text_data = text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        if self._json_data is not None:
            return self._json_data
        return json.loads(self._text_data)

    async def text(self):
        if self._text_data:
            return self._text_data
        return json.dumps(self._json_data or {}, ensure_ascii=False)


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self._responses:
            raise AssertionError("No fake response left for POST request")
        return self._responses.pop(0)

    async def close(self):
        self.closed = True


class FeishuOutputAdapterTests(unittest.IsolatedAsyncioTestCase):
    def _build_adapter(self, responses):
        adapter = FeishuOutputAdapter(
            FakeConfig(
                {
                    "feishu_app_id": "cli_test",
                    "feishu_app_secret": "secret_test",
                }
            )
        )
        adapter._session = FakeSession(responses)
        return adapter

    async def test_refreshes_token_when_cached_token_has_expired(self):
        adapter = self._build_adapter(
            [
                FakeResponse(json_data={"code": 0, "tenant_access_token": "token-1", "expire": 120}),
                FakeResponse(status=200, text_data='{"code":0,"msg":"ok"}'),
                FakeResponse(json_data={"code": 0, "tenant_access_token": "token-2", "expire": 120}),
                FakeResponse(status=200, text_data='{"code":0,"msg":"ok"}'),
            ]
        )

        await adapter._send_text("oc_test", "hello")
        adapter._tenant_access_token_expire_at = 0
        await adapter._send_text("oc_test", "hello again")

        message_calls = [
            call for call in adapter._session.calls if "im/v1/messages" in call["url"]
        ]
        auth_calls = [
            call
            for call in adapter._session.calls
            if "tenant_access_token/internal" in call["url"]
        ]

        self.assertEqual(len(auth_calls), 2)
        self.assertEqual(len(message_calls), 2)
        self.assertEqual(message_calls[0]["headers"]["Authorization"], "Bearer token-1")
        self.assertEqual(message_calls[1]["headers"]["Authorization"], "Bearer token-2")

    async def test_retries_once_after_invalid_token_response(self):
        adapter = self._build_adapter(
            [
                FakeResponse(json_data={"code": 0, "tenant_access_token": "token-old", "expire": 120}),
                FakeResponse(
                    status=400,
                    text_data='{"code":99991663,"msg":"Invalid access token for authorization. Please make a request with token attached."}',
                ),
                FakeResponse(json_data={"code": 0, "tenant_access_token": "token-new", "expire": 120}),
                FakeResponse(status=200, text_data='{"code":0,"msg":"ok"}'),
            ]
        )

        await adapter._send_text("oc_test", "hello")

        message_calls = [
            call for call in adapter._session.calls if "im/v1/messages" in call["url"]
        ]
        auth_calls = [
            call
            for call in adapter._session.calls
            if "tenant_access_token/internal" in call["url"]
        ]

        self.assertEqual(len(auth_calls), 2)
        self.assertEqual(len(message_calls), 2)
        self.assertEqual(message_calls[0]["headers"]["Authorization"], "Bearer token-old")
        self.assertEqual(message_calls[1]["headers"]["Authorization"], "Bearer token-new")
        self.assertEqual(adapter._tenant_access_token, "token-new")

    async def test_ignores_ephemeral_tool_chain_status_messages(self):
        adapter = self._build_adapter([])

        event = type(
            "Evt",
            (),
            {
                "type": EventType.STATUS.value,
                "target": EventTarget(kind="feishu", id="oc_test"),
                "source": make_source("system", "search"),
                "metadata": {"activity_kind": "tool_chain"},
                "stream_id": "",
                "content": "Routing request to knowledge search",
            },
        )()

        await adapter.send(event)

        self.assertEqual(adapter._session.calls, [])

    async def test_suppresses_plain_status_messages(self):
        adapter = self._build_adapter([])

        event = type(
            "Evt",
            (),
            {
                "type": EventType.STATUS.value,
                "target": EventTarget(kind="feishu", id="oc_test"),
                "source": make_source("system", "runtime"),
                "metadata": {},
                "stream_id": "",
                "content": "[系统] 正在路由",
            },
        )()

        await adapter.send(event)

        self.assertEqual(adapter._session.calls, [])

    async def test_keeps_streaming_end_delivery_for_real_assistant_reply(self):
        adapter = self._build_adapter(
            [
                FakeResponse(json_data={"code": 0, "tenant_access_token": "token-1", "expire": 120}),
                FakeResponse(status=200, text_data='{"code":0,"msg":"ok"}'),
            ]
        )

        start_event = type(
            "Evt",
            (),
            {
                "type": EventType.STATUS.value,
                "target": EventTarget(kind="feishu", id="oc_test"),
                "source": make_source("system", "brain"),
                "metadata": {"stream_event": StreamEventType.START.value},
                "stream_id": "stream-1",
                "content": "",
            },
        )()
        chunk_event = type(
            "Evt",
            (),
            {
                "type": EventType.MESSAGE.value,
                "target": EventTarget(kind="feishu", id="oc_test"),
                "source": make_source("system", "brain"),
                "metadata": {"stream_event": StreamEventType.CHUNK.value},
                "stream_id": "stream-1",
                "content": "hello",
            },
        )()
        end_event = type(
            "Evt",
            (),
            {
                "type": EventType.STATUS.value,
                "target": EventTarget(kind="feishu", id="oc_test"),
                "source": make_source("system", "brain"),
                "metadata": {"stream_event": StreamEventType.END.value},
                "stream_id": "stream-1",
                "content": "",
            },
        )()

        await adapter.send(start_event)
        await adapter.send(chunk_event)
        await adapter.send(end_event)

        message_calls = [
            call for call in adapter._session.calls if "im/v1/messages" in call["url"]
        ]
        self.assertEqual(len(message_calls), 1)

    async def test_delivery_notice_is_sent_as_independent_message(self):
        adapter = self._build_adapter(
            [
                FakeResponse(json_data={"code": 0, "tenant_access_token": "token-1", "expire": 120}),
                FakeResponse(status=200, text_data='{"code":0,"msg":"ok"}'),
            ]
        )

        await adapter.send_client_event(
            "oc_test",
            _notice("desktop notice"),
        )

        message_calls = [call for call in adapter._session.calls if "im/v1/messages" in call["url"]]
        self.assertEqual(len(message_calls), 1)
        self.assertIn("desktop notice", message_calls[0]["json"]["content"])

    async def test_human_input_request_renders_numbered_options(self):
        adapter = self._build_adapter(
            [
                FakeResponse(json_data={"code": 0, "tenant_access_token": "token-1", "expire": 120}),
                FakeResponse(status=200, text_data='{"code":0,"msg":"ok"}'),
            ]
        )

        event = type(
            "Evt",
            (),
            {
                "type": EventType.HUMAN_INPUT_REQUEST.value,
                "target": EventTarget(kind="feishu", id="oc_test"),
                "source": make_source("system", "human_input"),
                "metadata": {},
                "stream_id": "",
                "content": "Choose one",
                "request_id": "req-1",
                "question": "Choose one",
                "options": ["A", "B"],
            },
        )()

        await adapter.send(event)

        message_calls = [call for call in adapter._session.calls if "im/v1/messages" in call["url"]]
        self.assertEqual(len(message_calls), 1)
        self.assertIn("1. A", message_calls[0]["json"]["content"])
        self.assertIn("2. B", message_calls[0]["json"]["content"])

    async def test_client_event_confirm_request_prompts_user(self):
        adapter = self._build_adapter(
            [
                FakeResponse(json_data={"code": 0, "tenant_access_token": "token-1", "expire": 120}),
                FakeResponse(status=200, text_data='{"code":0,"msg":"ok"}'),
            ]
        )

        await adapter.send_client_event(
            "oc_test",
            _run_event({"type": "confirm.requested", "request_id": "req-1", "content": "需要确认执行。"}),
        )

        message_calls = [call for call in adapter._session.calls if "im/v1/messages" in call["url"]]
        self.assertEqual(len(message_calls), 1)
        self.assertIn("确认编号: req-1", message_calls[0]["json"]["content"])
        self.assertEqual(adapter.get_pending_confirm_request("oc_test"), "req-1")

    async def test_client_event_operation_update_is_suppressed(self):
        adapter = self._build_adapter(
            []
        )

        await adapter.send_client_event(
            "oc_test",
            _run_event({"type": "operation.updated", "operation_id": "op-1", "status": "running", "detail": "desktop endpoint accepted"}),
        )

        message_calls = [call for call in adapter._session.calls if "im/v1/messages" in call["url"]]
        self.assertEqual(message_calls, [])

    async def test_client_event_activity_status_is_suppressed(self):
        adapter = self._build_adapter([])

        await adapter.send_client_event(
            "oc_test",
            _run_event({"type": "activity.status", "content": "正在路由到桌面端"}),
        )

        message_calls = [call for call in adapter._session.calls if "im/v1/messages" in call["url"]]
        self.assertEqual(message_calls, [])

    async def test_client_event_stream_renders_completed_answer(self):
        adapter = self._build_adapter(
            [
                FakeResponse(json_data={"code": 0, "tenant_access_token": "token-1", "expire": 120}),
                FakeResponse(status=200, text_data='{"code":0,"msg":"ok"}'),
            ]
        )

        await adapter.send_client_event(
            "oc_test",
            _run_event({"type": "message.delta", "stream_id": "stream-1", "channel": "answer", "delta": "hello"}),
        )
        await adapter.send_client_event(
            "oc_test",
            _run_event({"type": "message.completed", "stream_id": "stream-1", "message": {"content": "hello"}}),
        )

        message_calls = [call for call in adapter._session.calls if "im/v1/messages" in call["url"]]
        self.assertEqual(len(message_calls), 1)


if __name__ == "__main__":
    unittest.main()
