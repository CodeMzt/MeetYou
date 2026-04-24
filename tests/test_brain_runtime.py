import json
import os
import sys
import types
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeClientSession:
    async def close(self):
        return None


try:
    import aiohttp  # noqa: F401
except ImportError:
    sys.modules.setdefault("aiohttp", types.SimpleNamespace(ClientSession=_FakeClientSession))

from adapters.base import StreamEvent, ToolCallInfo
from core.assistant_modes import RouteDecision
from core.brain import Brain
from core.status import RuntimeStatus


class FakeContextManager:
    def __init__(self):
        self.proprioception_info = {"ui_info": "", "running_apps": [], "last_update_time": 0}
        self.saved = []

    async def load_context(self, session_id: str = "") -> str:
        return "persisted context"

    async def update_context(self, context: str, session_id: str = "", source=None) -> str:
        self.saved.append({"session_id": session_id, "context": context})
        return "ok"

    async def trim_history(self, chat_history, model, session, api_url, api_key, reserve_ratio: float = 0.75):
        return None

    def estimate_message_tokens(self, message: dict) -> int:
        content = message.get("content")
        text = content if isinstance(content, str) else json.dumps(content or {}, ensure_ascii=False)
        if message.get("tool_calls"):
            text += json.dumps(message["tool_calls"], ensure_ascii=False)
        if message.get("provider_items"):
            text += json.dumps(message["provider_items"], ensure_ascii=False)
        if message.get("tool_call_id"):
            text += str(message.get("tool_call_id"))
        return max(1, len(text) // 4)

    def estimate_text_tokens(self, text: str) -> int:
        return max(1, len(str(text or "")) // 4)

    def get_context_limit(self, model: str) -> int:
        return 128000


class FakeToolsManager:
    def __init__(self):
        self.calls = []
        self.schemas = {
            "lookup_profile": self._build_tool_schema("lookup_profile"),
            "normal_tool": self._build_tool_schema("normal_tool"),
            "documents_tool": self._build_tool_schema("documents_tool"),
            "research_tool": self._build_tool_schema("research_tool"),
            "office_tool": self._build_tool_schema("office_tool"),
            "study_tool": self._build_tool_schema("study_tool"),
            "research_topic": self._build_tool_schema("research_topic"),
            "inspect_page": self._build_tool_schema("inspect_page"),
            "track_source_updates": self._build_tool_schema("track_source_updates"),
        }

    @staticmethod
    def _build_tool_schema(name: str) -> dict:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": f"Fake tool schema for {name}.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        }

    def get_all_tools(self, route_context=None):
        route_context = route_context or {}
        allowed = {
            str(item).strip()
            for item in route_context.get("tool_bundle", [])
            if str(item).strip()
        }
        if not allowed:
            return list(self.schemas.values())
        return [schema for name, schema in self.schemas.items() if name in allowed]

    async def call_tool(self, tool_name, tool_args, session_id="", source=None, tool_activity_callback=None):
        self.calls.append({
            "tool_name": tool_name,
            "tool_args": dict(tool_args),
            "session_id": session_id,
        })
        if tool_name == "search_memory":
            return json.dumps({"found": False})
        if tool_name == "lookup_profile":
            return json.dumps({"name": "Alex"})
        return json.dumps({"ok": True})


class _FakeModeManager:
    def __init__(self, router_config=None):
        self._router_config = {
            "default_mode": "normal",
            "sticky_current_mode": True,
            "allow_preferred_override": True,
            "allow_in_turn_switch": True,
            "max_switches_per_round": 0,
            "max_switches_per_turn": 0,
            "max_tool_calls_per_round": 0,
            "fallback_to_heuristic": True,
        }
        self._router_config.update(router_config or {})

    def get_mode_router_config(self):
        return dict(self._router_config)

    def get_auto_router_prompt(self):
        return "[Auto Router]\nnormal/documents/research/office/study"

    def get_prompt_for_mode(self, mode: str):
        return f"[{mode}]"

    def build_route_for_mode(self, mode: str, *, requested_mode: str = "auto", reason: str = "", content: str = ""):
        del content
        source_profile = "workspace_local"
        tool_bundle = [f"{mode}_tool"]
        if mode == "normal":
            tool_bundle = ["normal_tool", "research_topic", "inspect_page"]
        if mode == "research":
            source_profile = "tech_updates"
            tool_bundle = ["research_tool", "research_topic", "inspect_page", "track_source_updates"]
        elif mode == "study":
            source_profile = "study_materials"
        return RouteDecision(
            requested_mode=requested_mode,
            current_mode=mode,
            route_reason=reason,
            source_profile=source_profile,
            tool_bundle=tool_bundle,
            mcp_servers=[],
            prompt_bundle=mode,
        )

    def route(self, input_info, *, session_metadata=None, source=None):
        del session_metadata, source
        content = str(input_info.get("content") or "")
        lowered = content.lower()
        if any(token in lowered for token in ("watchlist", "track updates", "source updates", "research report", "citations", "evidence")):
            return self.build_route_for_mode(
                "research",
                reason="Matched research signals: deep_research",
                content=content,
            )
        if "http" in content or any(token in lowered for token in ("latest", "web", "website", "url", "link")):
            return self.build_route_for_mode(
                "normal",
                reason="Matched normal signals: light_web",
                content=content,
            )
        if "quiz" in lowered:
            return self.build_route_for_mode(
                "study",
                reason="Matched study signals: quiz",
                content=content,
            )
        if "meeting" in lowered:
            return self.build_route_for_mode(
                "office",
                reason="Matched office signals: meeting",
                content=content,
            )
        if any(token in lowered for token in ("file", "folder", "repo", "workspace", "directory", "local path")):
            return self.build_route_for_mode(
                "documents",
                reason="Matched documents signals: local_path",
                content=content,
            )
        return self.build_route_for_mode(
            "normal",
            reason="Matched normal signals: default",
            content=content,
        )


class QueuedStreamAdapter:
    def __init__(self, *, rounds):
        self.rounds = list(rounds)
        self.stream_calls = []

    async def stream_chat(self, session, api_url, api_key, model, messages, tools=None, **kwargs):
        del session, api_url, api_key, model, kwargs
        self.stream_calls.append(
            {
                "messages": list(messages),
                "tool_names": [tool.get("function", {}).get("name", "") for tool in list(tools or [])],
            }
        )
        if not self.rounds:
            raise AssertionError("No stream round payload left")
        round_payload = self.rounds.pop(0)
        for event in round_payload:
            yield event


class ReasoningAdapter:
    async def stream_chat(self, session, api_url, api_key, model, messages, tools=None, **kwargs):
        yield StreamEvent(type="reasoning", reasoning_text="plan")
        yield StreamEvent(type="text", text="final answer")
        yield StreamEvent(
            type="usage",
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "reasoning_tokens": 4,
                "total_tokens": 19,
            },
        )


class ToolCallingAdapter:
    def __init__(self):
        self.call_count = 0

    async def stream_chat(self, session, api_url, api_key, model, messages, tools=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            yield StreamEvent(
                type="tool_calls",
                tool_calls=[
                    ToolCallInfo(
                        id="tool-1",
                        name="lookup_profile",
                        arguments_str='{"name":"Alex"}',
                    )
                ],
            )
            yield StreamEvent(
                type="usage",
                usage={
                    "prompt_tokens": 8,
                    "completion_tokens": 1,
                    "reasoning_tokens": 0,
                    "total_tokens": 9,
                },
            )
            return

        yield StreamEvent(type="reasoning", reasoning_text="checking tool result")
        yield StreamEvent(type="text", text="done")
        yield StreamEvent(
            type="usage",
            usage={
                "prompt_tokens": 9,
                "completion_tokens": 3,
                "reasoning_tokens": 2,
                "total_tokens": 14,
            },
        )


class ProviderItemsToolAdapter:
    def __init__(self):
        self.call_count = 0
        self.second_call_provider_items = []

    async def stream_chat(self, session, api_url, api_key, model, messages, tools=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            yield StreamEvent(
                type="provider_items",
                provider_items=[
                    {
                        "type": "reasoning",
                        "id": "rs_1",
                        "encrypted_content": "opaque",
                    },
                    {
                        "type": "function_call",
                        "id": "fc_1",
                        "call_id": "call_1",
                        "name": "lookup_profile",
                        "arguments": '{"name":"Alex"}',
                    },
                ],
            )
            yield StreamEvent(
                type="tool_calls",
                tool_calls=[
                    ToolCallInfo(
                        id="call_1",
                        name="lookup_profile",
                        arguments_str='{"name":"Alex"}',
                    )
                ],
            )
            yield StreamEvent(
                type="usage",
                usage={
                    "prompt_tokens": 8,
                    "completion_tokens": 1,
                    "reasoning_tokens": 2,
                    "total_tokens": 11,
                },
            )
            return

        for message in messages:
            if message.get("role") == "assistant" and message.get("tool_calls"):
                self.second_call_provider_items = list(message.get("provider_items") or [])

        yield StreamEvent(type="text", text="done")
        yield StreamEvent(
            type="usage",
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 3,
                "reasoning_tokens": 0,
                "total_tokens": 13,
            },
        )


class SilentAnswerAdapter:
    async def stream_chat(self, session, api_url, api_key, model, messages, tools=None, **kwargs):
        yield StreamEvent(type="text", text="done")


class FailingSecondRoundAdapter:
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
                        id="tool-1",
                        name="lookup_profile",
                        arguments_str='{"name":"Alex"}',
                    )
                ],
            )
            yield StreamEvent(
                type="usage",
                usage={
                    "prompt_tokens": 8,
                    "completion_tokens": 1,
                    "reasoning_tokens": 0,
                    "total_tokens": 9,
                },
            )
            return
        raise RuntimeError("tool follow-up failed")


class SummaryUsageContextManager(FakeContextManager):
    async def trim_history(self, chat_history, model, session, api_url, api_key, reserve_ratio: float = 0.75):
        return {
            "summary_usage": {
                "prompt_tokens": 5,
                "completion_tokens": 2,
                "reasoning_tokens": 0,
                "total_tokens": 7,
            },
            "current_tokens": 0,
        }


class BudgetPressureContextManager(FakeContextManager):
    def __init__(self):
        super().__init__()
        self.trim_calls = 0

    async def trim_history(self, chat_history, model, session, api_url, api_key, reserve_ratio: float = 0.75, **kwargs):
        del model, session, api_url, api_key, reserve_ratio, kwargs
        self.trim_calls += 1
        if len(chat_history) > 3:
            del chat_history[1:-2]
        return {
            "conversation_summary": "compressed summary",
            "current_tokens": sum(self.estimate_message_tokens(message) for message in chat_history),
            "compression": {"triggered": True, "level": "history_summary", "trimmed_messages": 2},
        }

    def get_context_limit(self, model: str) -> int:
        del model
        return 320


class ProviderContextRetryAdapter:
    def __init__(self):
        self.calls = 0

    async def stream_chat(self, session, api_url, api_key, model, messages, tools=None, **kwargs):
        del session, api_url, api_key, model, messages, tools, kwargs
        self.calls += 1
        if self.calls == 1:
            error = RuntimeError("provider context limit")
            error.runtime_error_payload = {
                "code": "provider_context_limit_exceeded",
                "category": "validation",
                "message": "Maximum context length exceeded.",
                "retryable": False,
                "details": {},
            }
            raise error
        yield StreamEvent(type="text", text="retry-ok")
        yield StreamEvent(type="usage", usage={"prompt_tokens": 1, "completion_tokens": 1, "reasoning_tokens": 0, "total_tokens": 2})


class BrainRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_brain_injects_structured_time_context_into_turn(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(type="text", text="done"),
                ]
            ]
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-time",
                {"role": "user", "content": "现在几点"},
                "key",
                "url",
                "gpt-4o",
            ):
                pass

            messages = adapter.stream_calls[0]["messages"]
            time_messages = [
                message["content"]
                for message in messages
                if message.get("role") == "system" and "当前时间上下文：" in str(message.get("content") or "")
            ]
            self.assertEqual(len(time_messages), 1)
            self.assertIn("current_time_local", time_messages[0])
            self.assertIn("timezone", time_messages[0])
            self.assertIn("weekday", time_messages[0])
        finally:
            await brain.close_brain()

    async def test_brain_emits_reasoning_usage_and_snapshot(self):
        brain = Brain(
            ReasoningAdapter(),
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        try:
            events = []
            async for event in brain.input_brain(
                "session-1",
                {"role": "user", "content": "ok"},
                "key",
                "url",
                "gpt-4o",
            ):
                events.append(event)

            self.assertEqual(
                [event.type for event in events],
                ["reasoning_text", "answer_text", "reasoning_end", "usage", "done"],
            )
            self.assertEqual(
                "".join(event.text or "" for event in events if event.type == "reasoning_text"),
                "plan",
            )
            self.assertEqual(
                "".join(event.text or "" for event in events if event.type == "answer_text"),
                "final answer",
            )

            usage_payload = next(event.usage for event in events if event.type == "usage")
            self.assertEqual(usage_payload["usage_source"], "provider")
            self.assertEqual(usage_payload["last_turn_usage"]["reasoning_tokens"], 4)
            self.assertEqual(usage_payload["session_totals"]["turn_count"], 1)
            self.assertGreater(usage_payload["context_breakdown"]["total"], 0)
            debug_snapshot = brain.get_session_debug_snapshot("session-1")
            self.assertEqual(debug_snapshot["request"]["transport_mode"], "reasoningadapter")
            self.assertFalse(debug_snapshot["compression"]["triggered"])
        finally:
            await brain.close_brain()

    async def test_phase_callback_tracks_tool_calling_and_answering(self):
        tools_manager = FakeToolsManager()
        brain = Brain(
            ToolCallingAdapter(),
            tools_manager,
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        phases = []
        events = []

        async def phase_callback(status: str, detail: str = "", active_tools=None):
            phases.append((status, detail, list(active_tools or [])))

        try:
            async for event in brain.input_brain(
                "session-2",
                {"role": "user", "content": "ok"},
                "key",
                "url",
                "gpt-4o",
                phase_callback=phase_callback,
            ):
                events.append(event)

            self.assertEqual(
                [status for status, _, _ in phases],
                [
                    RuntimeStatus.THINKING.value,
                    RuntimeStatus.TOOL_CALLING.value,
                    RuntimeStatus.THINKING.value,
                    RuntimeStatus.ANSWERING.value,
                ],
            )
            self.assertEqual(phases[1][2], ["lookup_profile"])
            self.assertEqual(len([event for event in events if event.type == "usage"]), 2)
            self.assertEqual(
                "".join(event.text or "" for event in events if event.type == "answer_text"),
                "done",
            )
            self.assertEqual(
                [call["tool_name"] for call in tools_manager.calls],
                ["lookup_profile"],
            )

            usage_snapshot = brain.get_session_usage_snapshot("session-2")
            self.assertEqual(usage_snapshot["last_turn_usage"]["total_tokens"], 23)
            self.assertEqual(usage_snapshot["session_totals"]["turn_count"], 1)
        finally:
            await brain.close_brain()

    async def test_brain_preserves_provider_items_for_tool_follow_up(self):
        tools_manager = FakeToolsManager()
        adapter = ProviderItemsToolAdapter()
        brain = Brain(
            adapter,
            tools_manager,
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        try:
            events = []
            async for event in brain.input_brain(
                "session-3",
                {"role": "user", "content": "ok"},
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4-nano",
            ):
                events.append(event)

            self.assertEqual(
                "".join(event.text or "" for event in events if event.type == "answer_text"),
                "done",
            )
            self.assertEqual(len(adapter.second_call_provider_items), 2)
            self.assertEqual(adapter.second_call_provider_items[0]["type"], "reasoning")
            self.assertEqual(adapter.second_call_provider_items[1]["call_id"], "call_1")
        finally:
            await brain.close_brain()

    async def test_brain_preserves_reasoning_content_for_tool_follow_up(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(type="reasoning", reasoning_text="Need the profile before answering."),
                    StreamEvent(type="text", text="Let me check the profile."),
                    StreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            ToolCallInfo(
                                id="call_1",
                                name="lookup_profile",
                                arguments_str='{"name":"Alex"}',
                            )
                        ],
                    ),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 8,
                            "completion_tokens": 2,
                            "reasoning_tokens": 3,
                            "total_tokens": 13,
                        },
                    ),
                ],
                [
                    StreamEvent(type="text", text="done"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 10,
                            "completion_tokens": 1,
                            "reasoning_tokens": 0,
                            "total_tokens": 11,
                        },
                    ),
                ],
            ],
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        try:
            events = []
            async for event in brain.input_brain(
                "session-deepseek-tool",
                {"role": "user", "content": "Who is Alex?"},
                "key",
                "https://api.deepseek.com/v1/chat/completions",
                "deepseek-v4-pro",
            ):
                events.append(event)

            self.assertEqual("".join(event.text or "" for event in events if event.type == "answer_text"), "Let me check the profile.done")
            second_call_messages = adapter.stream_calls[1]["messages"]
            assistant_tool_messages = [
                message
                for message in second_call_messages
                if message.get("role") == "assistant" and message.get("tool_calls")
            ]
            self.assertEqual(len(assistant_tool_messages), 1)
            self.assertEqual(
                assistant_tool_messages[0]["reasoning_content"],
                "Need the profile before answering.",
            )
            self.assertEqual(assistant_tool_messages[0]["content"], "Let me check the profile.")
            self.assertFalse(
                any(
                    message.get("role") == "assistant"
                    and not message.get("tool_calls")
                    and message.get("content") == "Let me check the profile."
                    for message in second_call_messages
                )
            )
        finally:
            await brain.close_brain()

    async def test_brain_preserves_reasoning_content_after_parallel_tool_follow_up(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(type="reasoning", reasoning_text="Need both command results before answering."),
                    StreamEvent(type="text", text="I will run both checks."),
                    StreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            ToolCallInfo(
                                id="call_a",
                                name="research_topic",
                                arguments_str='{"topic":"workspace"}',
                            ),
                            ToolCallInfo(
                                id="call_b",
                                name="inspect_page",
                                arguments_str='{"url":"https://example.com"}',
                            ),
                        ],
                    ),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 8,
                            "completion_tokens": 2,
                            "reasoning_tokens": 3,
                            "total_tokens": 13,
                        },
                    ),
                ],
                [
                    StreamEvent(type="text", text="done"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 10,
                            "completion_tokens": 1,
                            "reasoning_tokens": 0,
                            "total_tokens": 11,
                        },
                    ),
                ],
            ],
        )
        tools_manager = FakeToolsManager()
        brain = Brain(
            adapter,
            tools_manager,
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-deepseek-parallel-tools",
                {"role": "user", "content": "Run web checks for https://example.com"},
                "key",
                "https://llm-proxy.example.com/v1/chat/completions",
                "deepseek/deepseek-v4-pro",
            ):
                pass

            non_memory_tool_calls = [
                call["tool_name"]
                for call in tools_manager.calls
                if call["tool_name"] != "search_memory"
            ]
            self.assertEqual(
                non_memory_tool_calls,
                ["research_topic", "inspect_page"],
            )
            second_call_messages = adapter.stream_calls[1]["messages"]
            assistant_tool_messages = [
                message
                for message in second_call_messages
                if message.get("role") == "assistant" and message.get("tool_calls")
            ]
            self.assertEqual(len(assistant_tool_messages), 1)
            assistant = assistant_tool_messages[0]
            self.assertEqual(assistant["reasoning_content"], "Need both command results before answering.")
            self.assertEqual([tool_call["id"] for tool_call in assistant["tool_calls"]], ["call_a", "call_b"])
            tool_messages = [
                message
                for message in second_call_messages
                if message.get("role") == "tool"
            ]
            self.assertEqual([message.get("tool_call_id") for message in tool_messages], ["call_a", "call_b"])
        finally:
            await brain.close_brain()

    async def test_estimate_call_usage_counts_provider_items(self):
        brain = Brain(
            SilentAnswerAdapter(),
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        try:
            without_provider_items = brain._estimate_call_usage(
                context_breakdown={"total": 10},
                assistant_content="done",
                reasoning_text="",
                tool_calls=[],
                provider_items=[],
            )
            with_provider_items = brain._estimate_call_usage(
                context_breakdown={"total": 10},
                assistant_content="done",
                reasoning_text="",
                tool_calls=[],
                provider_items=[
                    {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque"},
                    {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "lookup_profile"},
                ],
            )
            self.assertGreater(with_provider_items.completion_tokens, without_provider_items.completion_tokens)
        finally:
            await brain.close_brain()

    async def test_brain_keeps_estimated_usage_source_when_only_summary_has_provider_usage(self):
        brain = Brain(
            SilentAnswerAdapter(),
            FakeToolsManager(),
            SummaryUsageContextManager(),
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        try:
            events = []
            async for event in brain.input_brain(
                "session-summary-usage",
                {"role": "user", "content": "ok"},
                "key",
                "url",
                "gpt-4o",
            ):
                events.append(event)

            usage_payload = next(event.usage for event in events if event.type == "usage")
            self.assertEqual(usage_payload["usage_source"], "estimated")
            self.assertGreater(usage_payload["last_turn_usage"]["total_tokens"], 7)
        finally:
            await brain.close_brain()

    async def test_brain_preflights_budget_and_records_context_budget_breakdown(self):
        context_manager = BudgetPressureContextManager()
        adapter = QueuedStreamAdapter(rounds=[[StreamEvent(type="text", text="ok")]])
        brain = Brain(adapter, FakeToolsManager(), context_manager, event_bus=None, exception_router=None)
        await brain.init_brain("system prompt")
        try:
            for i in range(12):
                brain.get_or_create_session("session-budget").chat_history.append({"role": "user", "content": f"old message {i}"})
            events = []
            async for event in brain.input_brain(
                "session-budget",
                {"role": "user", "content": "new request"},
                "key",
                "url",
                "gpt-4o",
            ):
                events.append(event)
            usage_payload = next(event.usage for event in events if event.type == "usage")
            self.assertGreaterEqual(context_manager.trim_calls, 1)
            self.assertIn("input_budget", usage_payload["context_budget_breakdown"])
            self.assertGreater(usage_payload["context_budget_breakdown"]["context_window"], 0)
        finally:
            await brain.close_brain()

    async def test_brain_retries_once_after_provider_context_limit_exceeded(self):
        context_manager = BudgetPressureContextManager()
        brain = Brain(ProviderContextRetryAdapter(), FakeToolsManager(), context_manager, event_bus=None, exception_router=None)
        await brain.init_brain("system prompt")
        try:
            events = []
            async for event in brain.input_brain(
                "session-retry",
                {"role": "user", "content": "hello"},
                "key",
                "url",
                "gpt-4o",
            ):
                events.append(event)
            self.assertEqual("".join(event.text or "" for event in events if event.type == "answer_text"), "retry-ok")
            self.assertGreaterEqual(context_manager.trim_calls, 1)
        finally:
            await brain.close_brain()

    async def test_auto_mode_exposes_internal_switch_tool_and_switches_between_rounds(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            ToolCallInfo(
                                id="switch-1",
                                name="switch_assistant_mode",
                                arguments_str='{"mode":"research","reason":"Need latest external verification"}',
                            )
                        ],
                    ),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 5,
                            "completion_tokens": 1,
                            "reasoning_tokens": 0,
                            "total_tokens": 6,
                        },
                    ),
                ],
                [
                    StreamEvent(type="text", text="done"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 6,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 8,
                        },
                    ),
                ],
            ]
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager(),
        )
        await brain.init_brain("system prompt")

        try:
            events = []
            phases = []

            async def phase_callback(status: str, detail: str = "", active_tools=None):
                phases.append((status, detail, list(active_tools or [])))

            async for event in brain.input_brain(
                "session-auto-switch",
                {
                    "role": "user",
                    "content": "Check local files first, then verify the docs online.",
                    "metadata": {"preferred_mode": "auto"},
                },
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
                phase_callback=phase_callback,
            ):
                events.append(event)

            session = brain.get_or_create_session("session-auto-switch")
            self.assertEqual("".join(event.text or "" for event in events if event.type == "answer_text"), "done")
            self.assertEqual(
                [status for status, _, _ in phases],
                [
                    RuntimeStatus.THINKING.value,
                    RuntimeStatus.THINKING.value,
                    RuntimeStatus.ANSWERING.value,
                ],
            )
            self.assertIn("documents_tool", adapter.stream_calls[0]["tool_names"])
            self.assertIn("switch_assistant_mode", adapter.stream_calls[0]["tool_names"])
            self.assertNotIn("research_tool", adapter.stream_calls[0]["tool_names"])
            self.assertIn("research_tool", adapter.stream_calls[1]["tool_names"])
            self.assertIn("switch_assistant_mode", adapter.stream_calls[1]["tool_names"])
            self.assertNotIn("documents_tool", adapter.stream_calls[1]["tool_names"])
            self.assertIn("[documents]", [m["content"] for m in adapter.stream_calls[0]["messages"] if m.get("role") == "system"])
            self.assertIn("[research]", [m["content"] for m in adapter.stream_calls[1]["messages"] if m.get("role") == "system"])
            self.assertEqual(
                [entry["mode"] for entry in session.metadata["route_history"]],
                ["documents", "research"],
            )
            self.assertEqual(session.metadata["current_mode"], "research")
            self.assertEqual(session.metadata["route_history"][1]["origin"], "switch_tool")
            self.assertEqual(session.metadata["route_history"][1]["from_mode"], "documents")
            self.assertEqual(session.metadata["route_history"][1]["to_mode"], "research")
            self.assertEqual(session.metadata["route_history"][1]["switch_count"], 1)
        finally:
            await brain.close_brain()

    async def test_preferred_normal_starts_in_normal_mode_with_light_web_tools(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(type="text", text="normal"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 5,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 7,
                        },
                    ),
                ]
            ]
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager(),
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-normal-start",
                {
                    "role": "user",
                    "content": "Can you help me look this up online and summarize it simply?",
                    "metadata": {"preferred_mode": "normal"},
                },
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                pass

            session = brain.get_or_create_session("session-normal-start")
            self.assertEqual(session.metadata["current_mode"], "normal")
            self.assertEqual(session.metadata["route_history"][0]["origin"], "preferred_normal")
            self.assertIn("normal_tool", adapter.stream_calls[0]["tool_names"])
            self.assertIn("research_topic", adapter.stream_calls[0]["tool_names"])
            self.assertIn("inspect_page", adapter.stream_calls[0]["tool_names"])
            self.assertIn("switch_assistant_mode", adapter.stream_calls[0]["tool_names"])
            self.assertNotIn("track_source_updates", adapter.stream_calls[0]["tool_names"])
            self.assertIn("[normal]", [m["content"] for m in adapter.stream_calls[0]["messages"] if m.get("role") == "system"])
        finally:
            await brain.close_brain()

    async def test_preferred_normal_can_escalate_to_research_for_deep_research(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            ToolCallInfo(
                                id="switch-1",
                                name="switch_assistant_mode",
                                arguments_str='{"mode":"research","reason":"Need citations and source tracking"}',
                            )
                        ],
                    ),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 5,
                            "completion_tokens": 1,
                            "reasoning_tokens": 0,
                            "total_tokens": 6,
                        },
                    ),
                ],
                [
                    StreamEvent(type="text", text="deep research"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 6,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 8,
                        },
                    ),
                ],
            ]
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager(),
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-normal-escalate",
                {
                    "role": "user",
                    "content": "Please do a research report with citations and track updates on this topic.",
                    "metadata": {"preferred_mode": "normal"},
                },
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                pass

            session = brain.get_or_create_session("session-normal-escalate")
            self.assertEqual(
                [entry["mode"] for entry in session.metadata["route_history"]],
                ["normal", "research"],
            )
            self.assertEqual(session.metadata["current_mode"], "research")
            self.assertEqual(session.metadata["route_history"][1]["origin"], "switch_tool")
            self.assertIn("normal_tool", adapter.stream_calls[0]["tool_names"])
            self.assertNotIn("track_source_updates", adapter.stream_calls[0]["tool_names"])
            self.assertIn("research_tool", adapter.stream_calls[1]["tool_names"])
            self.assertIn("track_source_updates", adapter.stream_calls[1]["tool_names"])
        finally:
            await brain.close_brain()

    async def test_mode_switch_executes_follow_up_tools_in_same_round(self):
        tools_manager = FakeToolsManager()
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            ToolCallInfo(
                                id="switch-1",
                                name="switch_assistant_mode",
                                arguments_str='{"mode":"research","reason":"Need citations and source tracking"}',
                            ),
                            ToolCallInfo(
                                id="tool-1",
                                name="research_topic",
                                arguments_str='{"query":"official release notes"}',
                            ),
                        ],
                    ),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 6,
                            "completion_tokens": 1,
                            "reasoning_tokens": 0,
                            "total_tokens": 7,
                        },
                    ),
                ],
                [
                    StreamEvent(type="text", text="done"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 7,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 9,
                        },
                    ),
                ],
            ]
        )
        brain = Brain(
            adapter,
            tools_manager,
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager(),
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-switch-same-round",
                {
                    "role": "user",
                    "content": "Review local files, then verify official release notes with citations.",
                    "metadata": {"preferred_mode": "normal"},
                },
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                pass

            session = brain.get_or_create_session("session-switch-same-round")
            self.assertEqual(session.metadata["current_mode"], "research")
            self.assertEqual(
                [entry["mode"] for entry in session.metadata["route_history"]],
                ["normal", "research"],
            )
            self.assertEqual(
                [call["tool_name"] for call in tools_manager.calls],
                ["search_memory", "research_topic"],
            )
            self.assertTrue(
                any(
                    message.get("tool_call_id") == "tool-1"
                    and '"tool_name": "research_topic"' in str(message.get("content") or "")
                    for message in session.chat_history
                    if message.get("role") == "tool"
                )
            )
            self.assertIn("[research]", [m["content"] for m in adapter.stream_calls[1]["messages"] if m.get("role") == "system"])
        finally:
            await brain.close_brain()

    async def test_preferred_mode_lock_hides_internal_switch_tool(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(type="text", text="locked"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 4,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 6,
                        },
                    ),
                ]
            ]
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager(),
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-mode-lock",
                {
                    "role": "user",
                    "content": "Please research this topic.",
                    "metadata": {"preferred_mode": "research"},
                },
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                pass

            session = brain.get_or_create_session("session-mode-lock")
            self.assertIn("research_tool", adapter.stream_calls[0]["tool_names"])
            self.assertNotIn("switch_assistant_mode", adapter.stream_calls[0]["tool_names"])
            self.assertEqual(session.metadata["current_mode"], "research")
            self.assertEqual(session.metadata["route_history"][0]["origin"], "manual_lock")
        finally:
            await brain.close_brain()

    async def test_workspace_source_profile_preference_overrides_mode_default(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(type="text", text="workspace policy applied"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 4,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 6,
                        },
                    ),
                ]
            ]
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager(),
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-workspace-source-profile",
                {
                    "role": "user",
                    "content": "Please summarize this simply.",
                    "metadata": {
                        "preferred_mode": "normal",
                        "workspace_id": "study",
                        "workspace_title": "Study",
                        "workspace_base_mode": "study",
                        "workspace_prompt_overlay": "Prefer teaching-oriented explanations.",
                        "workspace_default_execution_target": "core_only",
                        "workspace_preferred_source_profiles": ["policy_global"],
                        "workspace_memory_ranking_policy": "workspace_first",
                    },
                },
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                pass

            session = brain.get_or_create_session("session-workspace-source-profile")
            self.assertEqual(session.metadata["source_profile"], "policy_global")
            self.assertEqual(
                session.metadata["current_route"]["workspace"]["preferred_source_profiles"],
                ["policy_global"],
            )
            self.assertEqual(
                session.metadata["current_route"]["workspace"]["memory_ranking_policy"],
                "workspace_first",
            )
            self.assertIn("Workspace source profile preference: policy_global", session.metadata["route_reason"])
        finally:
            await brain.close_brain()

    async def test_workspace_source_profile_preference_does_not_override_specific_research_profile(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(type="text", text="research policy kept"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 4,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 6,
                        },
                    ),
                ]
            ]
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager(),
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-research-source-profile",
                {
                    "role": "user",
                    "content": "Create a research report with citations.",
                    "metadata": {
                        "workspace_id": "personal",
                        "workspace_title": "Personal",
                        "workspace_base_mode": "general",
                        "workspace_prompt_overlay": "Prefer local grounding when possible.",
                        "workspace_default_execution_target": "core_only",
                        "workspace_preferred_source_profiles": ["workspace_local"],
                        "workspace_memory_ranking_policy": "workspace_first",
                    },
                },
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                pass

            session = brain.get_or_create_session("session-research-source-profile")
            self.assertEqual(session.metadata["source_profile"], "tech_updates")
            self.assertNotIn("Workspace source profile preference", session.metadata["route_reason"])
        finally:
            await brain.close_brain()

    async def test_max_switches_per_turn_blocks_additional_mode_changes(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            ToolCallInfo(
                                id="switch-1",
                                name="switch_assistant_mode",
                                arguments_str='{"mode":"research","reason":"Need external verification"}',
                            )
                        ],
                    ),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 4,
                            "completion_tokens": 1,
                            "reasoning_tokens": 0,
                            "total_tokens": 5,
                        },
                    ),
                ],
                [
                    StreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            ToolCallInfo(
                                id="switch-2",
                                name="switch_assistant_mode",
                                arguments_str='{"mode":"study","reason":"Turn the verified material into study notes"}',
                            )
                        ],
                    ),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 5,
                            "completion_tokens": 1,
                            "reasoning_tokens": 0,
                            "total_tokens": 6,
                        },
                    ),
                ],
                [
                    StreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            ToolCallInfo(
                                id="switch-3",
                                name="switch_assistant_mode",
                                arguments_str='{"mode":"office","reason":"Draft a meeting follow-up"}',
                            )
                        ],
                    ),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 5,
                            "completion_tokens": 1,
                            "reasoning_tokens": 0,
                            "total_tokens": 6,
                        },
                    ),
                ],
                [
                    StreamEvent(type="text", text="done"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 6,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 8,
                        },
                    ),
                ],
            ]
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager({"max_switches_per_turn": 2}),
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-switch-limit",
                {"role": "user", "content": "Need local review, then web verification, then study notes."},
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                pass

            session = brain.get_or_create_session("session-switch-limit")
            self.assertEqual(session.metadata["current_mode"], "study")
            self.assertEqual(
                [entry["origin"] for entry in session.metadata["route_history"]],
                ["heuristic", "switch_tool", "switch_tool", "switch_tool_limit"],
            )
            self.assertEqual(session.metadata["route_history"][-1]["switch_count"], 2)
            self.assertIn("study_tool", adapter.stream_calls[3]["tool_names"])
            self.assertNotIn("office_tool", adapter.stream_calls[3]["tool_names"])
            self.assertTrue(
                any(
                    "max_switches_per_turn=2 reached" in str(message.get("content") or "")
                    for message in session.chat_history
                    if message.get("role") == "tool"
                )
            )
        finally:
            await brain.close_brain()

    async def test_multiple_mode_switch_calls_in_one_round_are_allowed_by_default(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            ToolCallInfo(
                                id="switch-1",
                                name="switch_assistant_mode",
                                arguments_str='{"mode":"research","reason":"Need web verification"}',
                            ),
                            ToolCallInfo(
                                id="switch-2",
                                name="switch_assistant_mode",
                                arguments_str='{"mode":"study","reason":"Turn findings into notes"}',
                            ),
                        ],
                    ),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 5,
                            "completion_tokens": 1,
                            "reasoning_tokens": 0,
                            "total_tokens": 6,
                        },
                    ),
                ],
                [
                    StreamEvent(type="text", text="done"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 6,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 8,
                        },
                    ),
                ],
            ]
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager(),
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-multi-switch-round",
                {"role": "user", "content": "Research this quickly, then convert it into study notes."},
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                pass

            session = brain.get_or_create_session("session-multi-switch-round")
            self.assertEqual(session.metadata["current_mode"], "study")
            self.assertEqual(
                [entry["origin"] for entry in session.metadata["route_history"]],
                ["heuristic", "switch_tool", "switch_tool"],
            )
            self.assertFalse(
                any(
                    "max_switches_per_round" in str(message.get("content") or "")
                    for message in session.chat_history
                    if message.get("role") == "tool"
                )
            )
        finally:
            await brain.close_brain()

    async def test_max_switches_per_round_is_configurable(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            ToolCallInfo(
                                id="switch-1",
                                name="switch_assistant_mode",
                                arguments_str='{"mode":"research","reason":"Need web verification"}',
                            ),
                            ToolCallInfo(
                                id="switch-2",
                                name="switch_assistant_mode",
                                arguments_str='{"mode":"study","reason":"Turn findings into notes"}',
                            ),
                        ],
                    ),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 5,
                            "completion_tokens": 1,
                            "reasoning_tokens": 0,
                            "total_tokens": 6,
                        },
                    ),
                ],
                [
                    StreamEvent(type="text", text="done"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 6,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 8,
                        },
                    ),
                ],
            ]
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager({"max_switches_per_round": 1}),
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-switch-round-limit",
                {"role": "user", "content": "Research this quickly, then convert it into study notes."},
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                pass

            session = brain.get_or_create_session("session-switch-round-limit")
            self.assertEqual(session.metadata["current_mode"], "research")
            self.assertTrue(
                any(
                    "max_switches_per_round=1 reached" in str(message.get("content") or "")
                    for message in session.chat_history
                    if message.get("role") == "tool"
                )
            )
        finally:
            await brain.close_brain()

    async def test_max_tool_calls_per_round_is_configurable(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            ToolCallInfo(
                                id="tool-1",
                                name="research_topic",
                                arguments_str='{"topic":"A"}',
                            ),
                            ToolCallInfo(
                                id="tool-2",
                                name="inspect_page",
                                arguments_str='{"url":"https://example.com"}',
                            ),
                        ],
                    ),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 5,
                            "completion_tokens": 1,
                            "reasoning_tokens": 0,
                            "total_tokens": 6,
                        },
                    ),
                ],
                [
                    StreamEvent(type="text", text="done"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 6,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 8,
                        },
                    ),
                ],
            ]
        )
        tools_manager = FakeToolsManager()
        brain = Brain(
            adapter,
            tools_manager,
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager({"max_tool_calls_per_round": 1}),
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-tool-round-limit",
                {"role": "user", "content": "Please research this topic with web checks."},
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                pass

            session = brain.get_or_create_session("session-tool-round-limit")
            executed_tool_names = [call["tool_name"] for call in tools_manager.calls]
            self.assertIn("research_topic", executed_tool_names)
            self.assertNotIn("inspect_page", executed_tool_names)
            self.assertTrue(
                any(
                    "max_tool_calls_per_round=1 reached" in str(message.get("content") or "")
                    for message in session.chat_history
                    if message.get("role") == "tool"
                )
            )
        finally:
            await brain.close_brain()

    async def test_same_mode_switch_is_noop_and_does_not_increment(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            ToolCallInfo(
                                id="switch-1",
                                name="switch_assistant_mode",
                                arguments_str='{"mode":"documents","reason":"Stay on local files"}',
                            )
                        ],
                    ),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 4,
                            "completion_tokens": 1,
                            "reasoning_tokens": 0,
                            "total_tokens": 5,
                        },
                    ),
                ],
                [
                    StreamEvent(type="text", text="done"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 6,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 8,
                        },
                    ),
                ],
            ]
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager(),
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-switch-noop",
                {"role": "user", "content": "Review the local project files."},
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                pass

            session = brain.get_or_create_session("session-switch-noop")
            self.assertEqual(session.metadata["current_mode"], "documents")
            self.assertEqual(
                [entry["origin"] for entry in session.metadata["route_history"]],
                ["heuristic", "switch_tool_noop"],
            )
            self.assertEqual(session.metadata["route_history"][1]["switch_count"], 0)
            self.assertIn("documents_tool", adapter.stream_calls[1]["tool_names"])
            self.assertTrue(
                any(
                    "Already in documents" in str(message.get("content") or "")
                    for message in session.chat_history
                    if message.get("role") == "tool"
                )
            )
        finally:
            await brain.close_brain()

    async def test_disable_tools_clips_route_tools_but_keeps_internal_switch_tool(self):
        adapter = QueuedStreamAdapter(
            rounds=[
                [
                    StreamEvent(type="text", text="done"),
                    StreamEvent(
                        type="usage",
                        usage={
                            "prompt_tokens": 4,
                            "completion_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 6,
                        },
                    ),
                ]
            ]
        )
        brain = Brain(
            adapter,
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager(),
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-disable-tools",
                {"role": "user", "content": "Analyze the repo.", "metadata": {"disable_tools": True}},
                "key",
                "https://api.openai.com/v1/responses",
                "gpt-5.4",
            ):
                pass

            session = brain.get_or_create_session("session-disable-tools")
            self.assertEqual(adapter.stream_calls[0]["tool_names"], ["switch_assistant_mode"])
            self.assertEqual(session.metadata["current_mode"], "documents")
            self.assertIn("Tools disabled for transient internal signal.", session.metadata["route_reason"])
        finally:
            await brain.close_brain()

    async def test_transient_signal_turn_does_not_persist_context_or_history(self):
        context_manager = FakeContextManager()
        brain = Brain(
            ReasoningAdapter(),
            FakeToolsManager(),
            context_manager,
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        try:
            events = []
            async for event in brain.input_brain(
                "session-transient",
                {
                    "role": "system",
                    "content": "heartbeat ping",
                    "metadata": {"transient": True, "disable_tools": True},
                },
                "key",
                "url",
                "gpt-4o",
            ):
                events.append(event)

            session = brain.get_or_create_session("session-transient")
            self.assertEqual([event.type for event in events], ["reasoning_text", "answer_text", "reasoning_end", "usage", "done"])
            self.assertEqual(len(session.chat_history), 1)
            self.assertEqual(context_manager.saved, [])
        finally:
            await brain.close_brain()

    async def test_regenerate_restores_checkpoint_and_cleans_previous_reply_artifacts(self):
        brain = Brain(
            ToolCallingAdapter(),
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        try:
            async for _ in brain.input_brain(
                "session-regenerate",
                {"role": "user", "content": "介绍一下 Alex"},
                "key",
                "url",
                "gpt-4o",
            ):
                pass

            session = brain.get_or_create_session("session-regenerate")
            self.assertTrue(any(message.get("role") == "tool" for message in session.chat_history))
            self.assertTrue(any(message.get("role") == "assistant" for message in session.chat_history[1:]))

            result = brain.request_reply_control(
                "session-regenerate",
                action="regenerate",
                request_id="req-regenerate-1",
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["replay_input"]["content"], "介绍一下 Alex")
            self.assertEqual(len(session.chat_history), 1)
            self.assertEqual(session.chat_history[0]["role"], "system")
            self.assertFalse(any(message.get("role") == "tool" for message in session.chat_history))
            self.assertEqual(
                brain.get_reply_control_snapshot("session-regenerate")["last_completed_command"]["action"],
                "regenerate",
            )
        finally:
            await brain.close_brain()

    async def test_mark_reply_turn_failed_restores_checkpoint_after_tool_round_error(self):
        brain = Brain(
            FailingSecondRoundAdapter(),
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        try:
            with self.assertRaises(RuntimeError):
                async for _ in brain.input_brain(
                    "session-turn-failure",
                    {"role": "user", "content": "介绍一下 Alex"},
                    "key",
                    "url",
                    "gpt-4o",
                ):
                    pass

            session = brain.get_or_create_session("session-turn-failure")
            self.assertTrue(any(message.get("tool_calls") for message in session.chat_history))
            self.assertTrue(any(message.get("role") == "tool" for message in session.chat_history))

            brain.mark_reply_turn_failed("session-turn-failure", turn_id=str(session.runtime_state.turn_id or ""))

            self.assertEqual(len(session.chat_history), 1)
            self.assertEqual(session.chat_history[0]["role"], "system")
            self.assertEqual(
                brain.get_reply_control_snapshot("session-turn-failure")["last_finish_reason"],
                "failed",
            )
        finally:
            await brain.close_brain()

    async def test_rollback_rejects_unknown_checkpoint_with_explicit_status(self):
        brain = Brain(
            ReasoningAdapter(),
            FakeToolsManager(),
            FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        await brain.init_brain("system prompt")

        try:
            result = brain.request_reply_control(
                "session-missing-checkpoint",
                action="rollback",
                request_id="req-rollback-1",
                checkpoint_id="missing-checkpoint",
            )

            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["reason"], "检查点不存在或已失效。")
        finally:
            await brain.close_brain()


if __name__ == "__main__":
    unittest.main()
