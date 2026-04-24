import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.openai_adapter import OpenAIAdapter, ProviderRequestError


class FakeStreamContent:
    def __init__(self, lines):
        self._lines = [line.encode("utf-8") for line in lines]

    def __aiter__(self):
        self._iter = iter(self._lines)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeResponse:
    def __init__(self, status=200, lines=None, json_data=None):
        self.status = status
        self.content = FakeStreamContent(lines or [])
        self._json_data = json_data or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def json(self):
        return self._json_data


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self._responses:
            raise AssertionError("No fake response left for POST request")
        return self._responses.pop(0)


class OpenAIAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_get_context_limit_uses_registry_for_gpt_5_4_family(self):
        adapter = OpenAIAdapter()
        self.assertEqual(adapter.get_context_limit("gpt-5.4"), 400000)
        self.assertEqual(adapter.get_context_limit("gpt-5.4-mini"), 400000)
        self.assertEqual(adapter.get_context_limit("gpt-5.4-nano"), 400000)

    def test_format_messages_drops_dangling_tool_call_sequences(self):
        adapter = OpenAIAdapter()

        formatted = adapter.format_messages(
            [
                {"role": "user", "content": "What's the weather?"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call_1",
                            "function": {
                                "name": "search_web",
                                "arguments": '{"query":"weather"}',
                            },
                        }
                    ],
                    "provider_items": [
                        {
                            "type": "function_call",
                            "id": "fc_1",
                            "call_id": "call_1",
                            "name": "search_web",
                            "arguments": '{"query":"weather"}',
                        }
                    ],
                },
                {"role": "assistant", "content": "Let me try again."},
                {"role": "tool", "content": "orphan", "tool_call_id": "call_orphan"},
            ]
        )

        self.assertEqual(
            formatted,
            [
                {"role": "user", "content": "What's the weather?"},
                {"role": "assistant", "content": "Let me try again."},
            ],
        )

    def test_responses_input_preserves_complete_tool_exchange(self):
        adapter = OpenAIAdapter()

        payload = adapter._format_responses_input(
            [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "What's the weather?"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call_1",
                            "function": {
                                "name": "search_web",
                                "arguments": '{"query":"weather"}',
                            },
                        }
                    ],
                    "provider_items": [
                        {
                            "type": "function_call",
                            "id": "fc_1",
                            "call_id": "call_1",
                            "name": "search_web",
                            "arguments": '{"query":"weather"}',
                        }
                    ],
                },
                {
                    "role": "tool",
                    "content": '{"temperature":"20C"}',
                    "tool_call_id": "call_1",
                },
            ]
        )

        self.assertEqual(payload["instructions"], "You are helpful.")
        self.assertEqual(
            payload["input"],
            [
                {"role": "user", "content": "What's the weather?"},
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "search_web",
                    "arguments": '{"query":"weather"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": '{"temperature":"20C"}',
                },
            ],
        )

    async def test_official_openai_stream_uses_responses_api_and_summary_mode(self):
        adapter = OpenAIAdapter()
        session = FakeSession(
            [
                FakeResponse(
                    lines=[
                        'data: {"type":"response.reasoning_summary_text.delta","delta":"plan "}',
                        'data: {"type":"response.output_text.delta","delta":"answer"}',
                        'data: {"type":"response.completed","response":{"usage":{"input_tokens":11,"output_tokens":7,"output_tokens_details":{"reasoning_tokens":3},"total_tokens":21},"output":[]}}',
                        "data: [DONE]",
                    ]
                )
            ]
        )

        events = []
        async for event in adapter.stream_chat(
            session,
            "https://api.openai.com/v1/chat/completions",
            "key",
            "gpt-5.4-nano",
            [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "lookup_profile",
                        "description": "Look up a profile",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            thinking=True,
            thinking_effort="high",
        ):
            events.append(event)

        call = session.calls[0]
        self.assertEqual(call["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(
            call["json"]["reasoning"],
            {"effort": "high", "summary": "concise"},
        )
        self.assertIn("reasoning.encrypted_content", call["json"]["include"])
        self.assertEqual(call["json"]["instructions"], "You are helpful.")
        self.assertEqual(call["json"]["input"], [{"role": "user", "content": "Hello"}])
        self.assertEqual(
            call["json"]["tools"],
            [
                {
                    "type": "function",
                    "name": "lookup_profile",
                    "description": "Look up a profile",
                    "parameters": {"type": "object"},
                }
            ],
        )

        self.assertEqual(
            [event.type for event in events],
            ["reasoning", "text", "usage", "done"],
        )
        self.assertEqual(events[0].reasoning_text, "plan ")
        self.assertEqual(events[1].text, "answer")
        self.assertEqual(events[2].usage["reasoning_tokens"], 3)

    async def test_official_openai_stream_emits_provider_items_and_tool_calls(self):
        adapter = OpenAIAdapter()
        session = FakeSession(
            [
                FakeResponse(
                    lines=[
                        'data: {"type":"response.output_item.added","item":{"type":"function_call","id":"fc_1","call_id":"call_1","name":"lookup_profile","arguments":""}}',
                        'data: {"type":"response.function_call_arguments.delta","item_id":"fc_1","delta":"{\\"name\\":\\"Alex\\"}"}',
                        'data: {"type":"response.output_item.done","item":{"type":"reasoning","id":"rs_1","encrypted_content":"opaque"}}',
                        'data: {"type":"response.output_item.done","item":{"type":"function_call","id":"fc_1","call_id":"call_1","name":"lookup_profile","arguments":"{\\"name\\":\\"Alex\\"}"}}',
                        'data: {"type":"response.completed","response":{"usage":{"input_tokens":8,"output_tokens":4,"total_tokens":12},"output":[]}}',
                        "data: [DONE]",
                    ]
                )
            ]
        )

        events = []
        async for event in adapter.stream_chat(
            session,
            "https://api.openai.com/v1/responses",
            "key",
            "gpt-5.4-nano",
            [{"role": "user", "content": "Hello"}],
            thinking=True,
            thinking_effort="medium",
        ):
            events.append(event)

        provider_items_event = next(event for event in events if event.type == "provider_items")
        tool_calls_event = next(event for event in events if event.type == "tool_calls")

        self.assertEqual(
            [item["type"] for item in provider_items_event.provider_items],
            ["reasoning", "function_call"],
        )
        self.assertEqual(len(tool_calls_event.tool_calls), 1)
        self.assertEqual(tool_calls_event.tool_calls[0].id, "call_1")
        self.assertEqual(tool_calls_event.tool_calls[0].name, "lookup_profile")
        self.assertEqual(tool_calls_event.tool_calls[0].arguments_str, '{"name":"Alex"}')

    async def test_compatible_host_keeps_chat_completions_payload(self):
        adapter = OpenAIAdapter()
        session = FakeSession(
            [
                FakeResponse(
                    lines=[
                        'data: {"choices":[{"delta":{"content":"hello"}}]}',
                        'data: {"usage":{"prompt_tokens":9,"completion_tokens":3,"completion_tokens_details":{"reasoning_tokens":1},"total_tokens":13},"choices":[]}',
                        "data: [DONE]",
                    ]
                )
            ]
        )

        events = []
        async for event in adapter.stream_chat(
            session,
            "https://api.deepseek.com/v1/chat/completions",
            "key",
            "deepseek-reasoner",
            [{"role": "user", "content": "Hello"}],
            thinking=True,
            thinking_effort="medium",
        ):
            events.append(event)

        call = session.calls[0]
        self.assertEqual(call["url"], "https://api.deepseek.com/v1/chat/completions")
        self.assertIn("messages", call["json"])
        self.assertNotIn("input", call["json"])
        self.assertEqual(call["json"]["stream_options"], {"include_usage": True})
        self.assertEqual(call["json"]["reasoning_effort"], "medium")
        self.assertEqual(call["json"]["thinking"], {"type": "enabled"})
        self.assertEqual(
            [event.type for event in events],
            ["text", "usage", "done"],
        )

    async def test_compatible_host_retries_without_optional_fields_after_invalid_field_400(self):
        adapter = OpenAIAdapter()
        session = FakeSession(
            [
                FakeResponse(
                    status=400,
                    json_data={
                        "error": {
                            "message": "Unsupported parameter: reasoning_effort",
                            "type": "invalid_request_error",
                            "param": "reasoning_effort",
                        }
                    },
                ),
                FakeResponse(
                    lines=[
                        'data: {"choices":[{"delta":{"content":"hello"}}]}',
                        "data: [DONE]",
                    ]
                ),
            ]
        )

        events = []
        async for event in adapter.stream_chat(
            session,
            "https://api.deepseek.com/chat/completions",
            "key",
            "deepseek-reasoner",
            [{"role": "user", "content": "Hello"}],
            thinking=True,
            thinking_effort="medium",
        ):
            events.append(event)

        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0]["json"]["reasoning_effort"], "medium")
        self.assertEqual(session.calls[0]["json"]["stream_options"], {"include_usage": True})
        self.assertEqual(session.calls[0]["json"]["thinking"], {"type": "enabled"})
        self.assertNotIn("reasoning_effort", session.calls[1]["json"])
        self.assertNotIn("stream_options", session.calls[1]["json"])
        self.assertNotIn("thinking", session.calls[1]["json"])
        self.assertEqual([event.type for event in events], ["text", "done"])

    def test_deepseek_thinking_tool_call_preserves_reasoning_content(self):
        adapter = OpenAIAdapter()

        formatted = adapter._format_chat_messages(
            [
                {"role": "user", "content": "Need weather"},
                {
                    "role": "assistant",
                    "content": "Let me check the date first.",
                    "reasoning_content": "I need the date before calling weather.",
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call_1",
                            "function": {"name": "get_date", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "2026-04-24"},
            ],
            url="https://api.deepseek.com/v1/chat/completions",
            model="deepseek-v4-pro",
        )

        assistant = formatted[1]
        self.assertEqual(assistant["reasoning_content"], "I need the date before calling weather.")
        self.assertEqual(assistant["content"], "Let me check the date first.")
        self.assertEqual(assistant["tool_calls"][0]["id"], "call_1")

    def test_deepseek_thinking_tool_call_preserves_empty_reasoning_content_field(self):
        adapter = OpenAIAdapter()

        formatted = adapter._format_chat_messages(
            [
                {"role": "user", "content": "Need weather"},
                {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "",
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call_1",
                            "function": {"name": "get_date", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "2026-04-24"},
            ],
            url="https://api.deepseek.com/chat/completions",
            model="deepseek-v4-pro",
        )

        assistant = formatted[1]
        self.assertIn("reasoning_content", assistant)
        self.assertEqual(assistant["reasoning_content"], "")
        self.assertEqual(assistant["tool_calls"][0]["id"], "call_1")

    def test_deepseek_thinking_tool_call_backfills_missing_reasoning_content_field(self):
        adapter = OpenAIAdapter()

        formatted = adapter._format_chat_messages(
            [
                {"role": "user", "content": "Need weather"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call_1",
                            "function": {"name": "get_date", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "2026-04-24"},
            ],
            url="https://api.deepseek.com/chat/completions",
            model="deepseek-v4-pro",
        )

        assistant = formatted[1]
        self.assertIn("reasoning_content", assistant)
        self.assertEqual(assistant["reasoning_content"], "")
        self.assertEqual(assistant["tool_calls"][0]["id"], "call_1")

    def test_deepseek_thinking_tool_calls_preserve_reasoning_content_on_compatible_proxy(self):
        adapter = OpenAIAdapter()

        formatted = adapter._format_chat_messages(
            [
                {"role": "user", "content": "Run both checks"},
                {
                    "role": "assistant",
                    "content": "I will run the checks.",
                    "reasoning_content": "Both read-only checks can run before I answer.",
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call_a",
                            "function": {"name": "exec_sys_cmd", "arguments": '{"cmd":"whoami"}'},
                        },
                        {
                            "type": "function",
                            "id": "call_b",
                            "function": {"name": "exec_sys_cmd", "arguments": '{"cmd":"pwd"}'},
                        },
                    ],
                },
                {"role": "tool", "tool_call_id": "call_a", "content": "user"},
                {"role": "tool", "tool_call_id": "call_b", "content": "repo"},
            ],
            url="https://llm-proxy.example.com/v1/chat/completions",
            model="deepseek/deepseek-v4-pro",
        )

        assistant = formatted[1]
        self.assertEqual(assistant["reasoning_content"], "Both read-only checks can run before I answer.")
        self.assertEqual([tool_call["id"] for tool_call in assistant["tool_calls"]], ["call_a", "call_b"])

    async def test_deepseek_proxy_stream_payload_roundtrips_reasoning_content_for_parallel_tool_calls(self):
        adapter = OpenAIAdapter()
        session = FakeSession([FakeResponse(lines=["data: [DONE]"])])

        async for _ in adapter.stream_chat(
            session,
            "https://llm-proxy.example.com/v1/chat/completions",
            "key",
            "deepseek-v4-pro",
            [
                {"role": "user", "content": "Run both checks"},
                {
                    "role": "assistant",
                    "content": "I will run the checks.",
                    "reasoning_content": "Both checks are needed before answering.",
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call_a",
                            "function": {"name": "exec_sys_cmd", "arguments": '{"cmd":"whoami"}'},
                        },
                        {
                            "type": "function",
                            "id": "call_b",
                            "function": {"name": "exec_sys_cmd", "arguments": '{"cmd":"pwd"}'},
                        },
                    ],
                },
                {"role": "tool", "tool_call_id": "call_a", "content": "user"},
                {"role": "tool", "tool_call_id": "call_b", "content": "repo"},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "exec_sys_cmd",
                        "description": "Execute command",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            thinking=True,
            thinking_effort="high",
        ):
            pass

        payload_messages = session.calls[0]["json"]["messages"]
        assistant = payload_messages[1]
        self.assertEqual(assistant["reasoning_content"], "Both checks are needed before answering.")
        self.assertEqual([tool_call["id"] for tool_call in assistant["tool_calls"]], ["call_a", "call_b"])

    async def test_deepseek_reasoner_stream_payload_roundtrips_reasoning_content_for_parallel_tool_calls(self):
        adapter = OpenAIAdapter()
        session = FakeSession([FakeResponse(lines=["data: [DONE]"])])

        async for _ in adapter.stream_chat(
            session,
            "https://api.deepseek.com/chat/completions",
            "key",
            "deepseek-reasoner",
            [
                {"role": "user", "content": "Run both checks"},
                {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "Need both command results before answering.",
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call_a",
                            "function": {"name": "exec_sys_cmd", "arguments": '{"cmd":"whoami"}'},
                        },
                        {
                            "type": "function",
                            "id": "call_b",
                            "function": {"name": "exec_sys_cmd", "arguments": '{"cmd":"pwd"}'},
                        },
                    ],
                },
                {"role": "tool", "tool_call_id": "call_a", "content": "user"},
                {"role": "tool", "tool_call_id": "call_b", "content": "repo"},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "exec_sys_cmd",
                        "description": "Execute command",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            thinking=True,
            thinking_effort="high",
        ):
            pass

        payload = session.calls[0]["json"]
        assistant = payload["messages"][1]
        self.assertEqual(assistant["reasoning_content"], "Need both command results before answering.")
        self.assertEqual([tool_call["id"] for tool_call in assistant["tool_calls"]], ["call_a", "call_b"])
        self.assertEqual(payload["thinking"], {"type": "enabled"})

    async def test_deepseek_chat_result_exposes_reasoning_content_for_tool_calls(self):
        adapter = OpenAIAdapter()
        session = FakeSession(
            [
                FakeResponse(
                    json_data={
                        "choices": [
                            {
                                "message": {
                                    "content": "",
                                    "reasoning_content": "Need to run the command before answering.",
                                    "tool_calls": [
                                        {
                                            "type": "function",
                                            "id": "call_a",
                                            "function": {"name": "exec_sys_cmd", "arguments": '{"cmd":"whoami"}'},
                                        }
                                    ],
                                }
                            }
                        ],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    }
                )
            ]
        )

        result = await adapter.chat(
            session,
            "https://api.deepseek.com/chat/completions",
            "key",
            "deepseek-reasoner",
            [{"role": "user", "content": "Run command"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "exec_sys_cmd",
                        "description": "Execute command",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            thinking=True,
            thinking_effort="high",
        )

        self.assertEqual(result["reasoning_content"], "Need to run the command before answering.")
        self.assertEqual(result["tool_calls"][0].id, "call_a")
        self.assertEqual(session.calls[0]["json"]["thinking"], {"type": "enabled"})

    def test_deepseek_reasoner_preserves_reasoning_content_for_tool_calls(self):
        adapter = OpenAIAdapter()

        formatted = adapter._format_chat_messages(
            [
                {"role": "user", "content": "Need weather"},
                {
                    "role": "assistant",
                    "content": "Let me check.",
                    "reasoning_content": "Need the date before calling weather.",
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call_1",
                            "function": {"name": "get_date", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "2026-04-24"},
            ],
            url="https://api.deepseek.com/v1/chat/completions",
            model="deepseek-reasoner",
        )

        self.assertEqual(formatted[1]["reasoning_content"], "Need the date before calling weather.")

    def test_deepseek_reasoner_does_not_send_reasoning_content_without_tool_calls(self):
        adapter = OpenAIAdapter()

        formatted = adapter._format_chat_messages(
            [
                {"role": "user", "content": "Need weather"},
                {
                    "role": "assistant",
                    "content": "Answer without tools.",
                    "reasoning_content": "No tool call, do not keep this in context.",
                },
                {"role": "user", "content": "Thanks"},
            ],
            url="https://api.deepseek.com/v1/chat/completions",
            model="deepseek-reasoner",
        )

        self.assertNotIn("reasoning_content", formatted[1])

    async def test_deepseek_stream_emits_reasoning_and_tool_calls(self):
        adapter = OpenAIAdapter()
        session = FakeSession(
            [
                FakeResponse(
                    lines=[
                        'data: {"choices":[{"delta":{"reasoning_content":"plan "}}]}',
                        'data: {"choices":[{"delta":{"content":"Let me check."}}]}',
                        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"get_date","arguments":"{}"}}]}}]}',
                        "data: [DONE]",
                    ]
                )
            ]
        )

        events = []
        async for event in adapter.stream_chat(
            session,
            "https://api.deepseek.com/v1/chat/completions",
            "key",
            "deepseek-v4-pro",
            [{"role": "user", "content": "Need weather"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "get_date",
                        "description": "Get date",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            thinking=True,
            thinking_effort="high",
        ):
            events.append(event)

        self.assertEqual([event.type for event in events], ["reasoning", "text", "tool_calls", "done"])
        self.assertEqual(events[0].reasoning_text, "plan ")
        self.assertEqual(events[2].tool_calls[0].id, "call_1")

    async def test_compatible_host_400_raises_structured_provider_error(self):
        adapter = OpenAIAdapter()
        session = FakeSession(
            [
                FakeResponse(
                    status=400,
                    json_data={
                        "error": {
                            "message": "Maximum context length exceeded.",
                            "type": "invalid_request_error",
                        }
                    },
                )
            ]
        )

        with self.assertRaises(ProviderRequestError) as ctx:
            async for _ in adapter.stream_chat(
                session,
                "https://api.deepseek.com/chat/completions",
                "key",
                "deepseek-reasoner",
                [{"role": "user", "content": "Hello"}],
            ):
                pass

        payload = ctx.exception.runtime_error_payload
        self.assertEqual(payload["code"], "provider_context_limit_exceeded")
        self.assertEqual(payload["category"], "validation")
        self.assertEqual(payload["details"]["provider_mode"], "openai_compatible_chat")
        self.assertEqual(payload["details"]["status_code"], 400)


if __name__ == "__main__":
    unittest.main()
