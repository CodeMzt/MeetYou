import asyncio
import json
import os
import sys
import time
import unittest
from dataclasses import dataclass

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import Brain
from core.tool_runtime import ToolCallResult, ToolSourceType


class _FakeClientSession:
    async def close(self):
        return None


@dataclass
class _ToolCall:
    id: str
    name: str
    arguments: dict


class _FakeContextManager:
    async def load_context(self, session_id: str = "") -> str:
        return "ctx"

    async def update_context(self, context: str, session_id: str = "", source=None) -> str:
        del context, session_id, source
        return "ok"


class _FakeAdapter:
    async def stream_chat(self, *args, **kwargs):
        yield None


class _ParallelAwareToolsManager:
    def __init__(self):
        self.running = 0
        self.max_running = 0
        self.started = []
        self.finished = []

    async def call_tool(self, tool_name, tool_args, session_id="", source=None, tool_activity_callback=None, route_context=None):
        del session_id, source, tool_activity_callback, route_context
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        self.started.append(tool_name)
        try:
            await asyncio.sleep(float(tool_args.get("delay", 0.01)))
            if tool_args.get("fail"):
                raise RuntimeError("expected failure")
            return ToolCallResult.success(
                tool_name=tool_name,
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                raw_output={"ok": True, "tool": tool_name},
            )
        finally:
            self.finished.append(tool_name)
            self.running -= 1

    def get_action_risk_for_tools(self, tool_names):
        if any(name in {"write_local_document", "exec_sys_cmd"} for name in tool_names):
            return "local_write"
        return "read"

    def get_tool_parallel_metadata(self, tool_name, tool_args, *, route_context=None):
        del route_context
        if tool_name in {"write_local_document", "exec_sys_cmd", "ask_human"}:
            return {
                "safe_parallel": False,
                "parallel_group": "blocked",
                "resource_key": f"tool:{tool_name}",
                "mutates_state": True,
                "requires_order": True,
                "max_concurrency": 1,
            }
        resource = str(tool_args.get("resource") or f"tool:{tool_name}")
        return {
            "safe_parallel": True,
            "parallel_group": "read",
            "resource_key": resource,
            "mutates_state": False,
            "requires_order": False,
            "max_concurrency": 3,
        }


class ToolParallelExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tools_manager = _ParallelAwareToolsManager()
        self.brain = Brain(_FakeAdapter(), self.tools_manager, _FakeContextManager(), event_bus=None, exception_router=None)
        await self.brain.init_brain("system")
        self.session = self.brain.get_or_create_session("s")

    async def asyncTearDown(self):
        await self.brain.close_brain()

    async def test_read_only_tools_run_in_parallel_and_preserve_result_order(self):
        calls = [
            _ToolCall(id="tool-1", name="read_a", arguments={"delay": 0.2, "resource": "a"}),
            _ToolCall(id="tool-2", name="read_b", arguments={"delay": 0.2, "resource": "b"}),
        ]
        started_at = time.perf_counter()
        await self.brain._execute_visible_tool_calls(
            visible_tool_calls=calls,
            session=self.session,
            session_id="s",
            route_context={"max_parallel_tool_calls": 3},
            tool_activity_callback=None,
        )
        elapsed = time.perf_counter() - started_at

        self.assertLess(elapsed, 0.34)
        self.assertGreaterEqual(self.tools_manager.max_running, 2)
        tool_messages = [m for m in self.session.chat_history if m.get("role") == "tool"]
        self.assertEqual([m.get("tool_call_id") for m in tool_messages[-2:]], ["tool-1", "tool-2"])

    async def test_one_parallel_failure_does_not_cancel_other(self):
        calls = [
            _ToolCall(id="tool-1", name="read_fail", arguments={"delay": 0.05, "fail": True, "resource": "a"}),
            _ToolCall(id="tool-2", name="read_ok", arguments={"delay": 0.08, "resource": "b"}),
        ]
        await self.brain._execute_visible_tool_calls(
            visible_tool_calls=calls,
            session=self.session,
            session_id="s",
            route_context={"max_parallel_tool_calls": 3},
            tool_activity_callback=None,
        )
        tool_messages = [m for m in self.session.chat_history if m.get("role") == "tool"][-2:]
        payloads = [json.loads(m["content"]) for m in tool_messages]
        self.assertFalse(payloads[0]["ok"])
        self.assertTrue(payloads[1]["ok"])

    async def test_mutating_tools_are_serialized_by_default(self):
        calls = [
            _ToolCall(id="tool-1", name="write_local_document", arguments={"delay": 0.1}),
            _ToolCall(id="tool-2", name="exec_sys_cmd", arguments={"delay": 0.1}),
        ]
        await self.brain._execute_visible_tool_calls(
            visible_tool_calls=calls,
            session=self.session,
            session_id="s",
            route_context={"max_parallel_tool_calls": 3},
            tool_activity_callback=None,
        )
        self.assertEqual(self.tools_manager.max_running, 1)

    async def test_approval_tools_do_not_parallel_bypass(self):
        calls = [
            _ToolCall(id="tool-1", name="ask_human", arguments={"delay": 0.1}),
            _ToolCall(id="tool-2", name="read_after", arguments={"delay": 0.1, "resource": "after"}),
        ]
        await self.brain._execute_visible_tool_calls(
            visible_tool_calls=calls,
            session=self.session,
            session_id="s",
            route_context={"max_parallel_tool_calls": 3},
            tool_activity_callback=None,
        )
        self.assertEqual(self.tools_manager.started[:2], ["ask_human", "read_after"])
        self.assertEqual(self.tools_manager.max_running, 1)


if __name__ == "__main__":
    unittest.main()
