import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


try:
    import aiohttp  # noqa: F401
except ImportError:
    class _FakeRuntimeSession:
        async def close(self):
            return None

    sys.modules.setdefault(
        "aiohttp",
        types.SimpleNamespace(
            RuntimeSession=_FakeRuntimeSession,
            ClientTimeout=lambda **_kwargs: None,
        ),
    )

from adapters.base import StreamEvent, ToolCallInfo
from core.brain import Brain
from core.event_bus import EventBus
from core.io_protocol import EventTarget, EventType, HumanInputRequestEvent, SourceKind, TargetKind, make_source
from core.session_manager import SessionManager
from core.speaker import Speaker
from core.tools_manager import ToolsManager
from gateway.api import FastAPIGateway
from gateway.ws_manager import WebSocketManager, WebSocketOutputAdapter
from sensors.feishu_input_adapter import FeishuInputAdapter


class _FakeContextManager:
    def __init__(self):
        self.proprioception_info = {"ui_info": "", "running_apps": [], "last_update_time": 0}

    async def load_context(self, session_id: str = "") -> str:
        return "persisted context"

    async def update_context(self, context: str, session_id: str = "", source=None) -> str:
        return "ok"

    async def trim_history(self, chat_history, model, session, api_url, api_key, reserve_ratio: float = 0.75):
        return None

    def estimate_message_tokens(self, message: dict) -> int:
        content = message.get("content")
        text = content if isinstance(content, str) else json.dumps(content or {}, ensure_ascii=False)
        if message.get("tool_calls"):
            text += json.dumps(message["tool_calls"], ensure_ascii=False)
        return max(1, len(text) // 4)

    def estimate_text_tokens(self, text: str) -> int:
        return max(1, len(str(text or "")) // 4)

    def get_context_limit(self, model: str) -> int:
        return 128000


class _HumanInputToolsManager:
    def __init__(self):
        self.calls = []
        self._responses = [
            {
                "answered": True,
                "timed_out": False,
                "selected_option": "B",
                "answer_text": "B",
                "request_id": "req-1",
            },
            {
                "answered": True,
                "timed_out": False,
                "selected_option": "fast",
                "answer_text": "fast",
                "request_id": "req-2",
            },
        ]

    def get_all_tools(self, route_context=None):
        del route_context
        return []

    def get_action_risk_for_tools(self, tool_names):
        del tool_names
        return "read"

    async def call_tool(self, tool_name, tool_args, session_id="", source=None, tool_activity_callback=None, route_context=None):
        del tool_args, session_id, source, tool_activity_callback, route_context
        self.calls.append(tool_name)
        if tool_name == "ask_human":
            return json.dumps(self._responses.pop(0), ensure_ascii=False)
        return json.dumps({"ok": True}, ensure_ascii=False)


class _MultiAskHumanAdapter:
    def __init__(self):
        self.call_count = 0

    async def stream_chat(self, session, api_url, api_key, model, messages, tools=None, **kwargs):
        del session, api_url, api_key, model, messages, tools, kwargs
        self.call_count += 1
        if self.call_count == 1:
            yield StreamEvent(
                type="tool_calls",
                tool_calls=[
                    ToolCallInfo(
                        id="ask-1",
                        name="ask_human",
                        arguments_str='{"question":"Pick one","options":["A","B"]}',
                    )
                ],
            )
            yield StreamEvent(type="usage", usage={"prompt_tokens": 5, "completion_tokens": 1, "reasoning_tokens": 0, "total_tokens": 6})
            return
        if self.call_count == 2:
            yield StreamEvent(
                type="tool_calls",
                tool_calls=[
                    ToolCallInfo(
                        id="ask-2",
                        name="ask_human",
                        arguments_str='{"question":"Why?","options":["fast","slow"]}',
                    )
                ],
            )
            yield StreamEvent(type="usage", usage={"prompt_tokens": 4, "completion_tokens": 1, "reasoning_tokens": 0, "total_tokens": 5})
            return

        yield StreamEvent(type="text", text="done")
        yield StreamEvent(type="usage", usage={"prompt_tokens": 6, "completion_tokens": 2, "reasoning_tokens": 0, "total_tokens": 8})


class _GatewayHumanInputEventBus:
    def __init__(self):
        self.inbound_queue = asyncio.Queue()
        self.calls: list[tuple[str, str, str, str | None]] = []

    def submit_human_input_response(
        self,
        answer_text: str = "",
        *,
        request_id: str = "",
        session_id: str = "",
        selected_option: str | None = None,
    ) -> bool:
        self.calls.append((answer_text, request_id, session_id, selected_option))
        return True


class _FakeWebSocket:
    def __init__(self):
        self.payloads = []

    async def send_json(self, payload):
        self.payloads.append(payload)


class _FakeConfig:
    def __init__(self, values):
        self._values = values

    def get(self, key):
        return self._values.get(key)


class HumanInputFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_human_input_unblocks_and_returns_payload(self):
        bus = EventBus()

        wait_task = asyncio.create_task(
            bus.request_human_input(
                "Choose one",
                options=["A", "B"],
                session_id="web:test-session",
            )
        )

        await asyncio.sleep(0)

        resolved = bus.submit_human_input_response(
            "B",
            request_id=bus.get_pending_human_input_request("web:test-session").request_id,
            session_id="web:test-session",
            selected_option="B",
        )

        self.assertTrue(resolved)
        payload = await wait_task
        self.assertTrue(payload["answered"])
        self.assertFalse(payload["timed_out"])
        self.assertEqual(payload["selected_option"], "B")
        self.assertEqual(payload["answer_text"], "B")

    async def test_request_human_input_rejects_wrong_session_or_request(self):
        bus = EventBus()
        wait_task = asyncio.create_task(
            bus.request_human_input(
                "Choose one",
                options=["A", "B"],
                session_id="web:test-session",
            )
        )
        await asyncio.sleep(0)
        pending = bus.get_pending_human_input_request("web:test-session")

        self.assertFalse(
            bus.submit_human_input_response(
                "B",
                request_id="wrong-request",
                session_id="web:test-session",
            )
        )
        self.assertFalse(
            bus.submit_human_input_response(
                "B",
                request_id=pending.request_id,
                session_id="web:other-session",
            )
        )

        self.assertTrue(
            bus.submit_human_input_response(
                "B",
                request_id=pending.request_id,
                session_id="web:test-session",
            )
        )
        await wait_task

    async def test_request_human_input_timeout_returns_timed_out_payload_and_cleans_up(self):
        bus = EventBus()
        payload = await bus.request_human_input(
            "Choose one",
            options=["A", "B"],
            timeout=0.01,
            session_id="web:test-session",
        )

        self.assertFalse(payload["answered"])
        self.assertTrue(payload["timed_out"])
        self.assertIsNone(bus.get_pending_human_input_request("web:test-session"))

    async def test_brain_can_continue_same_turn_across_multiple_ask_human_calls(self):
        brain = Brain(
            _MultiAskHumanAdapter(),
            _HumanInputToolsManager(),
            _FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        try:
            events = []
            async for event in brain.input_brain(
                "session-human-input",
                {"role": "user", "content": "Need clarification first."},
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                events.append(event)

            answer = "".join(event.text or "" for event in events if event.type == "answer_text")
            self.assertEqual(answer, "done")
            usage_snapshot = brain.get_session_usage_snapshot("session-human-input")
            self.assertEqual(usage_snapshot["session_totals"]["turn_count"], 1)
        finally:
            await brain.close_brain()

    async def test_feishu_input_adapter_submits_pending_human_input_over_endpoint_chain(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        registry_path = Path(tmpdir.name) / "feishu_chat_ids.json"
        event_bus = EventBus()
        session_manager = SessionManager()
        case = self

        class _FakeOutput:
            def get_pending_confirm_request(self, chat_id: str):
                return None

            def resolve_human_input(self, chat_id: str, raw_text: str):
                case.assertEqual(chat_id, "oc_test")
                case.assertEqual(raw_text, "2")
                return {
                    "request_id": "req-human",
                    "answer_text": "B",
                    "selected_option": "B",
                }

            async def send_runtime_event(self, chat_id: str, payload: dict):
                return None

        class _FakeGatewayClient:
            def __init__(self):
                self.human_input_responses = []

            async def start(self):
                return None

            async def submit_human_input_response(self, *, request_id: str, answer_text: str, selected_option: str | None = None):
                self.human_input_responses.append(
                    {
                        "request_id": request_id,
                        "answer_text": answer_text,
                        "selected_option": selected_option,
                    }
                )
                return {"request_id": request_id, "answer_text": answer_text, "selected_option": selected_option}

            async def send_command(self, action: str, **kwargs):
                raise AssertionError("send_command should not be used")

        fake_output = _FakeOutput()
        fake_client = _FakeGatewayClient()
        adapter = FeishuInputAdapter(
            event_bus,
            session_manager,
            _FakeConfig(
                {
                    "feishu_chat_registry_path": str(registry_path),
                    "feishu_app_id": "",
                    "feishu_app_secret": "",
                }
            ),
            output_adapter=fake_output,
        )

        async def _fake_get_gateway_client(chat_id: str):
            return fake_client

        adapter._get_gateway_client = _fake_get_gateway_client  # type: ignore[assignment]

        await adapter.handle_event(
            {
                "event": {
                    "message": {
                        "chat_id": "oc_test",
                        "content": json.dumps({"text": "2"}, ensure_ascii=False),
                        "message_id": "msg-1",
                        "chat_type": "p2p",
                    },
                    "sender": {
                        "sender_id": {
                            "user_id": "user-1",
                        }
                    },
                }
            }
        )

        self.assertEqual(
            fake_client.human_input_responses,
            [{"request_id": "req-human", "answer_text": "B", "selected_option": "B"}],
        )
        self.assertTrue(event_bus.inbound_queue.empty())


class HumanInputGatewayTests(unittest.TestCase):
    def test_http_input_response_resolves_immediately(self):
        bus = _GatewayHumanInputEventBus()
        gateway = FastAPIGateway(bus, SessionManager(), access_token="ws-token")
        with TestClient(gateway.app) as client:
            response = client.post(
                "/runtime/sessions/web:test/human-input-response",
                headers={"Authorization": "Bearer ws-token"},
                json={
                    "action": "input_response",
                    "endpoint_id": "desktop",
                    "request_id": "req-123",
                    "answer_text": "B",
                    "selected_option": "B",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["session_id"], "web:test")
        self.assertEqual(bus.calls, [("B", "req-123", "web:test", "B")])
        self.assertTrue(bus.inbound_queue.empty())


class HumanInputSerializationTests(unittest.IsolatedAsyncioTestCase):
    async def test_human_input_request_is_serialized_for_websocket(self):
        ws_manager = WebSocketManager()
        websocket = _FakeWebSocket()
        session_manager = SessionManager()
        source = make_source(SourceKind.WEB.value, "browser-tab-a")
        session_manager.get_or_create_session(source, "session-1")
        speaker = Speaker(session_manager)
        speaker.register_adapter(TargetKind.WEB.value, WebSocketOutputAdapter(ws_manager))

        await ws_manager.connect("session-1", websocket)
        await speaker.emit(
            HumanInputRequestEvent(
                session_id="session-1",
                type=EventType.HUMAN_INPUT_REQUEST.value,
                role="system",
                content="Choose one",
                source=make_source(SourceKind.SYSTEM.value, "human_input"),
                target=EventTarget(kind=TargetKind.WEB.value, id="browser-tab-a"),
                question="Choose one",
                options=["A", "B"],
                placeholder="Select or type",
                timeout=60.0,
            )
        )

        payload = websocket.payloads[0]
        self.assertEqual(payload["event"]["type"], "human_input_request")
        self.assertEqual(payload["input_request"]["question"], "Choose one")
        self.assertEqual(payload["input_request"]["options"], ["A", "B"])
        self.assertEqual(payload["input_request"]["placeholder"], "Select or type")


class AskHumanVisibilityTests(unittest.TestCase):
    def test_ask_human_is_visible_to_main_llm(self):
        async def _stub(*args, **kwargs):
            return ""

        memory = SimpleNamespace(
            save_memory=None,
            recall_memory=None,
            recall_memory_structured=None,
        )
        context_manager = SimpleNamespace(update_context=None)
        mcp_manager = SimpleNamespace(tool_map={})
        system_tools = SimpleNamespace(
            exec_sys_cmd=None,
            ask_human=_stub,
            get_current_system_time=None,
            get_sys_vitals=None,
        )
        manager = ToolsManager(memory, context_manager, mcp_manager, system_tools)
        with open(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user", "tools.json"),
            "r",
            encoding="utf-8",
        ) as fh:
            manager.tools_schema_dict = json.load(fh)

        visible_names = {tool["function"]["name"] for tool in manager.get_all_tools()}
        self.assertIn("ask_human", visible_names)


if __name__ == "__main__":
    unittest.main()
