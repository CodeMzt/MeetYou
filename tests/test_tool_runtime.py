import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import Brain
from core.tool_runtime import ToolCallResult
import core.tool_runtime.executor as tool_executor_module
from core.tools_manager import ToolsManager
from tools import system_tools as real_system_tools


class _FakeClientSession:
    async def close(self):
        return None


class _FakeContextManager:
    def __init__(self):
        self.proprioception_info = {"ui_info": "", "running_apps": [], "last_update_time": 0}

    async def load_context(self, session_id: str = "") -> str:
        return "persisted context"

    async def update_context(self, context: str, session_id: str = "", source=None) -> str:
        return "ok"

    async def trim_history(self, chat_history, model, session, api_url, api_key, reserve_ratio: float = 0.75):
        return None


class _StructuredToolsManager:
    async def call_tool(self, tool_name, tool_args, session_id="", source=None, tool_activity_callback=None, route_context=None):
        del tool_args, session_id, source, tool_activity_callback, route_context
        return ToolCallResult.success(
            tool_name=tool_name,
            source="builtin",
            action_risk="read",
            raw_output={"ok": True},
        )


class _FakeModeManager:
    def __init__(self, trusted_roots):
        self._trusted_roots = [str(Path(root).resolve()) for root in trusted_roots]

    def get_document_parser_config(self):
        return {
            "max_file_bytes": 2_000_000,
            "max_total_chars": 24_000,
            "max_chunks_per_document": 12,
            "enable_ocr": False,
        }

    def get_trusted_write_roots(self):
        return list(self._trusted_roots)

    def is_trusted_write_path(self, path_value: str) -> bool:
        candidate = str(Path(path_value).resolve())
        for root in self._trusted_roots:
            if candidate == root or candidate.startswith(f"{root}{os.sep}"):
                return True
        return False


class _FakeAgentDispatcher:
    async def dispatch_local_capability(
        self,
        *,
        capability_suffix: str,
        arguments: dict,
        session_id: str = "",
        title: str = "",
        operation_type: str = "",
        timeout_seconds: int = 120,
    ):
        del session_id, title, operation_type, timeout_seconds
        if capability_suffix == "file.write":
            path = Path(arguments["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = str(arguments.get("mode") or "overwrite")
            content = str(arguments.get("content") or "")
            if mode == "append":
                path.write_text(path.read_text(encoding="utf-8") + content if path.exists() else content, encoding="utf-8")
            else:
                path.write_text(content, encoding="utf-8")
            return {"bytes_written": len(content.encode("utf-8"))}
        raise AssertionError(f"Unexpected capability: {capability_suffix}")


class ToolRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def _build_manager(self, *, call_mcp_tool=None, exec_sys_cmd=None, command_safety_checker=None, mode_manager=None):
        async def builtin_time():
            return {"now": "2026-04-05T00:00:00Z"}

        memory = SimpleNamespace(
            save_memory=None,
            recall_memory=None,
            recall_memory_structured=None,
        )
        context_manager = SimpleNamespace(update_context=None)
        mcp_manager = SimpleNamespace(
            tool_map={},
            mcp_servers_list=[],
            mcp_tools={},
            init_mcp_servers=self._noop_async,
            call_mcp_tool=call_mcp_tool or self._noop_async,
        )
        system_tools = SimpleNamespace(
            exec_sys_cmd=exec_sys_cmd,
            get_current_system_time=builtin_time,
            get_sys_vitals=None,
            assess_command_safety=command_safety_checker,
        )
        return ToolsManager(memory, context_manager, mcp_manager, system_tools, mode_manager=mode_manager)

    async def _noop_async(self, *args, **kwargs):
        del args, kwargs
        return None

    def _build_manager_with_real_system_tools(self, *, mode_manager):
        memory = SimpleNamespace(
            save_memory=None,
            recall_memory=None,
            recall_memory_structured=None,
        )
        context_manager = SimpleNamespace(update_context=None)
        mcp_manager = SimpleNamespace(
            tool_map={},
            mcp_servers_list=[],
            mcp_tools={},
            init_mcp_servers=self._noop_async,
            call_mcp_tool=self._noop_async,
        )
        return ToolsManager(memory, context_manager, mcp_manager, real_system_tools, mode_manager=mode_manager)

    async def test_permission_denied_returns_structured_error(self):
        manager = self._build_manager()

        result = await manager.call_tool(
            "get_current_system_time",
            {},
            route_context={"tool_bundle": ["search_memory"], "mcp_servers": []},
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "tool_not_allowed")
        self.assertEqual(result.error.category, "permission")
        self.assertEqual(result.error.details["tool_name"], "get_current_system_time")

    async def test_builtin_argument_mismatch_returns_structured_error(self):
        manager = self._build_manager()

        result = await manager.call_tool("get_current_system_time", {"unexpected": True})

        self.assertFalse(result.ok)
        self.assertEqual(result.source, "builtin")
        self.assertEqual(result.error.code, "tool_argument_mismatch")
        self.assertEqual(result.error.category, "validation")
        self.assertIn("unexpected", result.error.details["exception_message"])

    async def test_mcp_timeout_returns_structured_error(self):
        async def slow_tool(tool_name, tool_args):
            del tool_name, tool_args
            await asyncio.sleep(0.05)
            return None

        manager = self._build_manager(call_mcp_tool=slow_tool)
        manager._mcp_manager.tool_map["read_file"] = "filesystem"
        original_timeout_getter = tool_executor_module.get_mcp_timeout_seconds
        tool_executor_module.get_mcp_timeout_seconds = lambda tool_name: 0.01
        try:
            result = await manager.call_tool("read_file", {"path": "demo.txt"})
        finally:
            tool_executor_module.get_mcp_timeout_seconds = original_timeout_getter

        self.assertFalse(result.ok)
        self.assertEqual(result.source, "mcp")
        self.assertEqual(result.error.code, "tool_timeout")
        self.assertTrue(result.error.retryable)

    async def test_authorization_gateway_requires_command_confirmation(self):
        async def exec_sys_cmd(cmd, confirmed=False, session_id="", source=None):
            del session_id, source
            return {"command": cmd, "confirmed": confirmed}

        manager = self._build_manager(
            exec_sys_cmd=exec_sys_cmd,
            command_safety_checker=lambda cmd: {
                "status": "needs_confirm",
                "reason": f"dangerous: {cmd}",
            },
        )

        result = await manager.call_tool(
            "exec_sys_cmd",
            {"cmd": "git reset --hard HEAD"},
            route_context={"tool_bundle": ["exec_sys_cmd"], "mcp_servers": [], "current_mode": "documents"},
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "tool_confirmation_required")
        self.assertTrue(result.metadata["authorization"]["requires_confirmation"])

        confirmed_result = await manager.call_tool(
            "exec_sys_cmd",
            {"cmd": "git reset --hard HEAD", "confirmed": True},
            route_context={"tool_bundle": ["exec_sys_cmd"], "mcp_servers": [], "current_mode": "documents"},
        )

        self.assertTrue(confirmed_result.ok)
        self.assertEqual(confirmed_result.content.data["confirmed"], True)
        self.assertEqual(
            confirmed_result.metadata["authorization"]["confirmation_kind"],
            "command_policy",
        )

    async def test_authorization_gateway_enforces_document_confirmation_and_write_boundary(self):
        with tempfile.TemporaryDirectory() as trusted_dir, tempfile.TemporaryDirectory() as other_dir:
            manager = self._build_manager(mode_manager=_FakeModeManager([trusted_dir]))
            manager.set_agent_dispatcher(_FakeAgentDispatcher())
            trusted_path = str(Path(trusted_dir) / "report.md")
            outside_path = str(Path(other_dir) / "report.md")
            route_context = {
                "tool_bundle": ["write_local_document"],
                "mcp_servers": [],
                "current_mode": "documents",
            }

            previewless = await manager.call_tool(
                "write_local_document",
                {"path": trusted_path, "content": "# Final\n", "preview": False},
                route_context=route_context,
            )
            self.assertFalse(previewless.ok)
            self.assertEqual(previewless.error.code, "tool_confirmation_required")

            blocked = await manager.call_tool(
                "write_local_document",
                {"path": outside_path, "content": "# Final\n", "preview": False, "confirmed": True},
                route_context=route_context,
            )
            self.assertFalse(blocked.ok)
            self.assertEqual(blocked.error.code, "tool_write_boundary_violation")

            written = await manager.call_tool(
                "write_local_document",
                {"path": trusted_path, "content": "# Final\n", "preview": False, "confirmed": True},
                route_context=route_context,
            )
            self.assertTrue(written.ok)
            self.assertEqual(Path(trusted_path).read_text(encoding="utf-8"), "# Final\n")
            self.assertEqual(
                written.metadata["authorization"]["write_boundary"],
                "trusted_root",
            )

    async def test_readonly_authorization_hides_write_tools_and_blocks_write_calls(self):
        with tempfile.TemporaryDirectory() as trusted_dir:
            manager = self._build_manager(mode_manager=_FakeModeManager([trusted_dir]))
            tools_path = Path(__file__).resolve().parent.parent / "user" / "tools.json"
            manager.tools_schema_dict = json.loads(tools_path.read_text(encoding="utf-8"))
            route_context = {
                "tool_bundle": ["search_memory", "remember_knowledge", "create_skill"],
                "mcp_servers": [],
                "current_mode": "research",
                "authorization_policy": {"read_only": True, "policy_sources": ["mode:research"]},
            }

            visible_names = {
                tool["function"]["name"]
                for tool in manager.get_all_tools(route_context=route_context)
            }
            self.assertIn("search_memory", visible_names)
            self.assertNotIn("remember_knowledge", visible_names)
            self.assertNotIn("create_skill", visible_names)

            result = await manager.call_tool(
                "remember_knowledge",
                {"content": "store this"},
                route_context=route_context,
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.error.code, "tool_readonly_violation")
            self.assertTrue(result.metadata["authorization"]["read_only"])

    async def test_core_local_tools_fail_without_agent_dispatcher(self):
        with tempfile.TemporaryDirectory() as trusted_dir:
            manager = self._build_manager_with_real_system_tools(mode_manager=_FakeModeManager([trusted_dir]))
            real_system_tools.init_system_tools(None, None, "missing.json", allow_local_fallback=False)
            real_system_tools.set_agent_dispatcher(None)
            self.addCleanup(real_system_tools.set_agent_dispatcher, None)
            self.addCleanup(real_system_tools.set_local_fallback_enabled, True)

            command_result = await manager.call_tool(
                "exec_sys_cmd",
                {"cmd": 'python -c "print(123)"'},
                route_context={"tool_bundle": ["exec_sys_cmd"], "mcp_servers": [], "current_mode": "documents"},
            )
            read_result = await manager.call_tool(
                "read_local_documents",
                {"paths": [str(Path(trusted_dir) / "notes.md")]},
                route_context={"tool_bundle": ["read_local_documents"], "mcp_servers": [], "current_mode": "documents"},
            )

            self.assertFalse(command_result.ok)
            self.assertEqual(command_result.error.code, "local_agent_required")
            self.assertEqual(command_result.error.details["capability_suffix"], "shell.exec")
            self.assertFalse(read_result.ok)
            self.assertEqual(read_result.error.code, "local_agent_required")
            self.assertEqual(read_result.error.details["capability_suffix"], "file.read")

    async def test_brain_route_call_normalizes_structured_result(self):
        brain = Brain(
            adapter=None,
            tools_manager=_StructuredToolsManager(),
            context_manager=_FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        brain._http_session = _FakeClientSession()

        result = await brain._call_tool_with_route(
            "lookup_profile",
            {},
            session_id="session-1",
            source=None,
            tool_activity_callback=None,
            route_context={"current_mode": "normal"},
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.tool_name, "lookup_profile")
        self.assertEqual(result.content.data, {"ok": True})
        self.assertIn('"tool_name": "lookup_profile"', brain._tool_message_content(result))


if __name__ == "__main__":
    unittest.main()
