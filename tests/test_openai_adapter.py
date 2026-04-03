import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.openai_adapter import OpenAIAdapter


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
        self.assertEqual(call["json"]["reasoning_effort"], "medium")
        self.assertEqual(
            [event.type for event in events],
            ["text", "usage", "done"],
        )


if __name__ == "__main__":
    unittest.main()
