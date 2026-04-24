import unittest

from adapters.base import ToolCallInfo
from core.background_agent import BackgroundAgentRunner
from core.tool_runtime import ToolCallResult, ToolSourceType


class _FakeAdapter:
    def __init__(self):
        self.calls = []

    async def chat(self, session, api_url, api_key, model, messages, tools=None, **kwargs):
        self.calls.append([dict(message) for message in messages])
        if len(self.calls) == 1:
            return {
                "content": "",
                "reasoning_content": "Need both command results before answering.",
                "tool_calls": [
                    ToolCallInfo(id="call_a", name="exec_sys_cmd", arguments_str='{"cmd":"whoami"}'),
                    ToolCallInfo(id="call_b", name="exec_sys_cmd", arguments_str='{"cmd":"pwd"}'),
                ],
            }
        return {"content": "done", "tool_calls": []}


class _FakeToolsManager:
    async def call_tool(self, tool_name, args, **kwargs):
        return ToolCallResult.success(
            tool_name=tool_name,
            source=ToolSourceType.UNKNOWN,
            action_risk="read",
            raw_output={"ok": True, "args": args},
        )


class BackgroundAgentRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_reasoning_content_for_parallel_tool_follow_up(self):
        adapter = _FakeAdapter()
        runner = BackgroundAgentRunner(adapter, _FakeToolsManager())

        result = await runner.run(
            session=None,
            api_url="https://api.deepseek.com/chat/completions",
            api_key="key",
            model="deepseek-reasoner",
            messages=[{"role": "user", "content": "Run both commands"}],
            tools=[],
            adapter_options={"thinking": True},
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(adapter.calls), 2)
        assistant = adapter.calls[1][1]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual(assistant["reasoning_content"], "Need both command results before answering.")
        self.assertEqual([tool_call["id"] for tool_call in assistant["tool_calls"]], ["call_a", "call_b"])
        self.assertEqual([message["tool_call_id"] for message in adapter.calls[1][2:]], ["call_a", "call_b"])


if __name__ == "__main__":
    unittest.main()
