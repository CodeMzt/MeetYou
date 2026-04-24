import json
import os
import unittest

import aiohttp


def _deepseek_key() -> str:
    return str(os.environ.get("MEETYOU_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()


@unittest.skipUnless(
    os.environ.get("MEETYOU_LIVE_DEEPSEEK_TESTS") == "1" and _deepseek_key(),
    "set MEETYOU_LIVE_DEEPSEEK_TESTS=1 and MEETYOU_API_KEY/DEEPSEEK_API_KEY to run live DeepSeek contract tests",
)
class LiveDeepSeekThinkingContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_thinking_tool_follow_up_requires_reasoning_content_field(self):
        api_url = "https://api.deepseek.com/chat/completions"
        model = os.environ.get("MEETYOU_LIVE_DEEPSEEK_MODEL", "deepseek-chat")
        headers = {
            "Authorization": f"Bearer {_deepseek_key()}",
            "Content-Type": "application/json",
        }
        tool = {
            "type": "function",
            "function": {
                "name": "get_test_weather",
                "description": "Return test weather for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
        base_messages = [
            {"role": "system", "content": "You are a tool-use contract test assistant."},
            {"role": "user", "content": "Call get_test_weather for Shanghai, then answer."},
        ]

        async def post(payload):
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, headers=headers, json=payload) as response:
                    data = await response.json(content_type=None)
                    return response.status, data

        first_status, first_data = await post(
            {
                "model": model,
                "messages": base_messages,
                "tools": [tool],
                "stream": False,
                "thinking": {"type": "enabled"},
                "reasoning_effort": "low",
                "max_tokens": 512,
            }
        )
        self.assertEqual(first_status, 200, first_data)
        first_message = (first_data.get("choices") or [{}])[0].get("message") or {}
        tool_calls = first_message.get("tool_calls") or []
        self.assertTrue(tool_calls, first_data)
        reasoning_content = first_message.get("reasoning_content")
        self.assertIsInstance(reasoning_content, str)

        tool_message = {
            "role": "tool",
            "tool_call_id": tool_calls[0]["id"],
            "content": json.dumps({"weather": "sunny-test"}),
        }
        assistant_without_reasoning = {
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls,
        }
        missing_status, missing_data = await post(
            {
                "model": model,
                "messages": base_messages + [assistant_without_reasoning, tool_message],
                "tools": [tool],
                "stream": False,
                "thinking": {"type": "enabled"},
                "reasoning_effort": "low",
                "max_tokens": 512,
            }
        )
        self.assertEqual(missing_status, 400, missing_data)
        self.assertIn("reasoning_content", str(missing_data))

        assistant_with_empty_reasoning = dict(assistant_without_reasoning)
        assistant_with_empty_reasoning["reasoning_content"] = ""
        empty_status, empty_data = await post(
            {
                "model": model,
                "messages": base_messages + [assistant_with_empty_reasoning, tool_message],
                "tools": [tool],
                "stream": False,
                "thinking": {"type": "enabled"},
                "reasoning_effort": "low",
                "max_tokens": 512,
            }
        )
        self.assertEqual(empty_status, 200, empty_data)


if __name__ == "__main__":
    unittest.main()
