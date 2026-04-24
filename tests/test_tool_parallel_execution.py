import asyncio
import time
import unittest

from adapters.base import ToolCallInfo
from core.brain import Brain
from core.tool_runtime import ToolExecutionCapability
from core.tool_runtime.executor import ToolExecutor


class _NoopContextManager:
    async def load_context(self, session_id: str = "") -> str:
        return ""

    async def update_context(self, context: str, session_id: str = "", source=None) -> str:
        return "ok"


class _FakeToolsManager:
    def __init__(self):
        self.behaviors: dict[str, dict] = {}
        self.call_log: list[str] = []

    def add_tool(self, tool_name: str, *, delay: float, ok: bool = True, capability: ToolExecutionCapability):
        self.behaviors[tool_name] = {
            "delay": delay,
            "ok": ok,
            "capability": capability,
        }

    async def call_tool(self, tool_name, tool_args, session_id="", source=None, tool_activity_callback=None, route_context=None):
        del tool_args, session_id, source, tool_activity_callback, route_context
        behavior = self.behaviors[tool_name]
        await asyncio.sleep(behavior["delay"])
        self.call_log.append(tool_name)
        if behavior["ok"]:
            return {"tool_name": tool_name, "ok": True, "source": "builtin", "action_risk": "read", "content": {"kind": "json", "text": "{}", "data": {}}, "metadata": {}}
        raise RuntimeError(f"{tool_name} failed")

    def get_action_risk_for_tools(self, tool_names):
        for tool_name in tool_names:
            capability = self.behaviors.get(tool_name, {}).get("capability")
            if capability and capability.action_risk != "read":
                return capability.action_risk
        return "read"

    def get_tool_execution_capability(self, tool_name: str, tool_args=None):
        del tool_args
        return self.behaviors[tool_name]["capability"]


class _FakeModeManager:
    def __init__(self, max_parallel_tool_calls: int = 3):
        self._config = {"max_parallel_tool_calls": max_parallel_tool_calls}

    def get_mode_router_config(self):
        return dict(self._config)


class ParallelToolExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tools = _FakeToolsManager()
        self.brain = Brain(
            adapter=None,
            tools_manager=self.tools,
            context_manager=_NoopContextManager(),
            event_bus=None,
            exception_router=None,
            mode_manager=_FakeModeManager(),
        )

    async def test_read_only_tools_run_in_parallel_and_preserve_order(self):
        self.tools.add_tool(
            "read_a",
            delay=0.12,
            capability=ToolExecutionCapability(
                tool_name="read_a",
                source="builtin",
                action_risk="read",
                safe_parallel=True,
                parallel_group="builtin:read",
                resource_key="resource:a",
                mutates_state=False,
                requires_order=False,
                max_concurrency=3,
            ),
        )
        self.tools.add_tool(
            "read_b",
            delay=0.12,
            capability=ToolExecutionCapability(
                tool_name="read_b",
                source="builtin",
                action_risk="read",
                safe_parallel=True,
                parallel_group="builtin:read",
                resource_key="resource:b",
                mutates_state=False,
                requires_order=False,
                max_concurrency=3,
            ),
        )

        session = self.brain.get_or_create_session("s-parallel")
        calls = [
            ToolCallInfo(id="tool-1", name="read_a", arguments_str="{}"),
            ToolCallInfo(id="tool-2", name="read_b", arguments_str="{}"),
        ]
        started_at = time.perf_counter()
        await self.brain._execute_visible_tool_calls(
            visible_tool_calls=calls,
            session=session,
            session_id="s-parallel",
            route_context={},
            tool_activity_callback=None,
        )
        elapsed = time.perf_counter() - started_at

        self.assertLess(elapsed, 0.22)
        tool_messages = [message for message in session.chat_history if message.get("role") == "tool"]
        self.assertEqual([message.get("tool_call_id") for message in tool_messages], ["tool-1", "tool-2"])

    async def test_failure_does_not_cancel_other_parallel_tools(self):
        self.tools.add_tool(
            "read_ok",
            delay=0.08,
            ok=True,
            capability=ToolExecutionCapability(
                tool_name="read_ok",
                source="builtin",
                action_risk="read",
                safe_parallel=True,
                parallel_group="builtin:read",
                resource_key="resource:ok",
                mutates_state=False,
                requires_order=False,
                max_concurrency=3,
            ),
        )
        self.tools.add_tool(
            "read_fail",
            delay=0.08,
            ok=False,
            capability=ToolExecutionCapability(
                tool_name="read_fail",
                source="builtin",
                action_risk="read",
                safe_parallel=True,
                parallel_group="builtin:read",
                resource_key="resource:fail",
                mutates_state=False,
                requires_order=False,
                max_concurrency=3,
            ),
        )

        session = self.brain.get_or_create_session("s-fail")
        await self.brain._execute_visible_tool_calls(
            visible_tool_calls=[
                ToolCallInfo(id="tool-1", name="read_ok", arguments_str="{}"),
                ToolCallInfo(id="tool-2", name="read_fail", arguments_str="{}"),
            ],
            session=session,
            session_id="s-fail",
            route_context={},
            tool_activity_callback=None,
        )

        payloads = [message.get("content") for message in session.chat_history if message.get("role") == "tool"]
        self.assertTrue('"ok": true' in payloads[0])
        self.assertTrue('"ok": false' in payloads[1])

    async def test_local_write_and_destructive_tools_are_serial_by_default(self):
        self.tools.add_tool(
            "write_local_document",
            delay=0.09,
            capability=ToolExecutionCapability(
                tool_name="write_local_document",
                source="builtin",
                action_risk="local_write",
                safe_parallel=False,
                parallel_group="agent_local_file",
                resource_key="agent_local:/tmp/a.txt",
                mutates_state=True,
                requires_order=True,
                max_concurrency=1,
            ),
        )
        self.tools.add_tool(
            "exec_sys_cmd",
            delay=0.09,
            capability=ToolExecutionCapability(
                tool_name="exec_sys_cmd",
                source="builtin",
                action_risk="destructive",
                safe_parallel=False,
                parallel_group="builtin:mutating",
                resource_key="builtin:exec_sys_cmd",
                mutates_state=True,
                requires_order=True,
                max_concurrency=1,
                requires_approval=True,
            ),
        )

        session = self.brain.get_or_create_session("s-serial")
        started_at = time.perf_counter()
        await self.brain._execute_visible_tool_calls(
            visible_tool_calls=[
                ToolCallInfo(id="tool-1", name="write_local_document", arguments_str='{"path":"/tmp/a.txt"}'),
                ToolCallInfo(id="tool-2", name="exec_sys_cmd", arguments_str='{"cmd":"rm -rf /tmp/a"}'),
            ],
            session=session,
            session_id="s-serial",
            route_context={},
            tool_activity_callback=None,
        )
        elapsed = time.perf_counter() - started_at
        self.assertGreater(elapsed, 0.17)


class CapabilityPolicyTests(unittest.TestCase):
    def test_agent_local_file_unknown_path_is_serial_and_boundary_preserved(self):
        class _Registry:
            def has_builtin(self, tool_name: str) -> bool:
                return tool_name == "read_local_documents"

            def has_mcp(self, tool_name: str) -> bool:
                return False

        class _Risk:
            def get_tool_action_risk(self, tool_name: str) -> str:
                return "read"

        executor = ToolExecutor(_Registry(), permission_policy=None, risk_classifier=_Risk(), mcp_manager=None)
        capability = executor.get_tool_execution_capability("read_local_documents", {"paths": []})

        self.assertEqual(capability.parallel_group, "agent_local_file")
        self.assertFalse(capability.safe_parallel)
        self.assertTrue(capability.requires_order)
        self.assertEqual(capability.source, "builtin")


if __name__ == "__main__":
    unittest.main()
