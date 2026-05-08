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
from core.runtime_context import bind_event_context, reset_event_context
from core.tool_runtime import ToolCallResult
import core.tool_runtime.executor as tool_executor_module
from core.tools_manager import ToolsManager
from tools import system_tools as real_system_tools


class _FakeRuntimeSession:
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


class _FakeEndpointToolDispatcher:
    async def dispatch_tool_call(
        self,
        *,
        tool_key: str,
        arguments: dict,
        session_id: str = "",
        title: str = "",
        operation_type: str = "",
        timeout_seconds: int = 120,
    ):
        del session_id, title, operation_type, timeout_seconds
        if tool_key == "file.write":
            path = Path(arguments["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = str(arguments.get("mode") or "overwrite")
            content = str(arguments.get("content") or "")
            if mode == "append":
                path.write_text(path.read_text(encoding="utf-8") + content if path.exists() else content, encoding="utf-8")
            else:
                path.write_text(content, encoding="utf-8")
            return {"bytes_written": len(content.encode("utf-8"))}
        raise AssertionError(f"Unexpected tool: {tool_key}")


class _RecordingEndpointToolDispatcher:
    def __init__(self):
        self.calls = []

    async def dispatch_tool_call(self, **kwargs):
        self.calls.append(dict(kwargs))
        if kwargs["tool_key"] == "file.write":
            content = str(kwargs.get("arguments", {}).get("content") or "")
            return {"bytes_written": len(content.encode("utf-8"))}
        raise AssertionError(f"Unexpected tool: {kwargs['tool_key']}")


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
            route_context={"tool_bundle": ["exec_sys_cmd"], "mcp_servers": [], "current_mode": "general"},
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "tool_confirmation_required")
        self.assertTrue(result.metadata["authorization"]["requires_confirmation"])

        confirmed_result = await manager.call_tool(
            "exec_sys_cmd",
            {"cmd": "git reset --hard HEAD", "confirmed": True},
            route_context={"tool_bundle": ["exec_sys_cmd"], "mcp_servers": [], "current_mode": "general"},
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
            manager.set_capability_dispatcher(_FakeEndpointToolDispatcher())
            trusted_path = str(Path(trusted_dir) / "report.md")
            outside_path = str(Path(other_dir) / "report.md")
            route_context = {
                "tool_bundle": ["write_local_document"],
                "mcp_servers": [],
                "current_mode": "general",
            }

            previewless = await manager.call_tool(
                "write_local_document",
                {"path": trusted_path, "content": "# Final\n", "preview": False},
                route_context=route_context,
            )
            self.assertFalse(previewless.ok)
            self.assertEqual(previewless.error.code, "tool_confirmation_required")

            core_boundary_manager = self._build_manager(mode_manager=_FakeModeManager([trusted_dir]))
            blocked = await core_boundary_manager.call_tool(
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
                "endpoint_tool_managed",
            )

    async def test_endpoint_tool_document_write_preserves_windows_path_on_core(self):
        manager = self._build_manager(mode_manager=_FakeModeManager([]))
        dispatcher = _RecordingEndpointToolDispatcher()
        manager.set_capability_dispatcher(dispatcher)
        windows_path = r"E:\Documents\test_write_confirm.md"

        result = await manager.call_tool(
            "write_local_document",
            {"path": windows_path, "content": "ok", "preview": False, "confirmed": True},
            route_context={"tool_bundle": ["write_local_document"], "mcp_servers": [], "current_mode": "general"},
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.content.data["path"], windows_path)
        self.assertEqual(result.content.data["execution_target"], "desktop_endpoint_tool")
        self.assertEqual(dispatcher.calls[0]["arguments"]["path"], windows_path)
        self.assertEqual(result.metadata["authorization"]["write_path"], windows_path)
        self.assertEqual(result.metadata["authorization"]["write_boundary"], "endpoint_tool_managed")
        self.assertIsNone(result.metadata["authorization"]["trusted_root"])

    async def test_contextual_endpoint_tool_catalog_injects_and_dispatches_original_tool_key(self):
        manager = self._build_manager()
        origin = SimpleNamespace(
            id="endpoint-origin",
            endpoint_id="wechat.meetwechat.ui",
            provider_type="wechat",
            status="online",
            workspace_scope=["personal"],
        )
        executor = SimpleNamespace(
            id="endpoint-executor",
            endpoint_id="wechat.meetwechat.executor",
            provider_type="wechat",
            status="online",
            workspace_scope=["personal"],
        )
        other_provider = SimpleNamespace(
            id="endpoint-other",
            endpoint_id="desktop.main.executor",
            provider_type="desktop",
            status="online",
            workspace_scope=["personal"],
        )
        capability = SimpleNamespace(
            tool_key="utility.echo",
            capability_id="endpoint.wechat.meetwechat.executor.utility.echo",
            schema={"type": "object", "properties": {"text": {"type": "string"}}},
            risk_level="read",
            requires_confirmation=False,
            enabled=True,
            constraints={"workspace_ids": ["personal"], "timeout": 15, "max_concurrency": 2},
            meta={
                "title": "Echo",
                "description": "Echo text through the endpoint.",
                "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
                "output_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
                "visibility": {"auto_inject": True},
            },
        )
        other_capability = SimpleNamespace(
            tool_key="utility.other",
            capability_id="endpoint.desktop.main.executor.utility.other",
            schema={"type": "object"},
            risk_level="read",
            requires_confirmation=False,
            enabled=True,
            constraints={},
            meta={"visibility": {"auto_inject": True}},
        )

        class _EndpointService:
            def get_by_endpoint_id(self, endpoint_id):
                return {
                    origin.endpoint_id: origin,
                    executor.endpoint_id: executor,
                    other_provider.endpoint_id: other_provider,
                }.get(endpoint_id)

            def list_all(self):
                return [origin, executor, other_provider]

        class _CapabilityService:
            def list_for_endpoint(self, endpoint_row_id):
                if endpoint_row_id == executor.id:
                    return [capability]
                if endpoint_row_id == other_provider.id:
                    return [other_capability]
                return []

        class _ToolRouter:
            def __init__(self):
                self.calls = []

            async def dispatch_tool_call(self, **kwargs):
                self.calls.append(dict(kwargs))
                return {"text": kwargs["arguments"]["text"]}

        router = _ToolRouter()
        manager.set_core_domain(
            SimpleNamespace(
                services=SimpleNamespace(endpoint=_EndpointService(), endpoint_capability=_CapabilityService()),
                tool_router=router,
            )
        )
        route_context = {
            "endpoint_id": origin.endpoint_id,
            "workspace_id": "personal",
            "current_mode": "general",
            "mcp_servers": [],
        }

        schemas = manager.get_all_tools(route_context=route_context)
        dynamic_names = [
            schema["function"]["name"]
            for schema in schemas
            if schema.get("function", {}).get("metadata", {}).get("source") == "endpoint"
        ]

        self.assertEqual(len(dynamic_names), 1)
        dynamic_name = dynamic_names[0]
        self.assertTrue(dynamic_name.startswith("ep_"))
        self.assertEqual(route_context["endpoint_tool_catalog"]["tools"][dynamic_name]["tool_key"], "utility.echo")

        result = await manager.call_tool(
            dynamic_name,
            {"text": "hello"},
            session_id="sess-1",
            route_context=route_context,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.content.data, {"text": "hello"})
        self.assertEqual(router.calls[0]["tool_key"], "utility.echo")
        self.assertEqual(router.calls[0]["target_endpoint_id"], executor.endpoint_id)
        self.assertEqual(router.calls[0]["workspace_id"], "personal")

    async def test_readonly_authorization_hides_write_tools_and_blocks_write_calls(self):
        with tempfile.TemporaryDirectory() as trusted_dir:
            manager = self._build_manager(mode_manager=_FakeModeManager([trusted_dir]))
            tools_path = Path(__file__).resolve().parent.parent / "user" / "tools.json"
            manager.tools_schema_dict = json.loads(tools_path.read_text(encoding="utf-8"))
            route_context = {
                "tool_bundle": ["search_memory", "remember_knowledge", "create_skill", "manage_skill"],
                "mcp_servers": [],
                "current_mode": "general",
                "authorization_policy": {"read_only": True, "policy_sources": ["mode:general"]},
            }

            visible_names = {
                tool["function"]["name"]
                for tool in manager.get_all_tools(route_context=route_context)
            }
            self.assertIn("search_memory", visible_names)
            self.assertNotIn("remember_knowledge", visible_names)
            self.assertNotIn("create_skill", visible_names)
            self.assertNotIn("manage_skill", visible_names)

            result = await manager.call_tool(
                "remember_knowledge",
                {"content": "store this"},
                route_context=route_context,
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.error.code, "tool_readonly_violation")
            self.assertTrue(result.metadata["authorization"]["read_only"])

    async def test_emit_progress_notice_schema_requires_call_before_slow_operations(self):
        manager = self._build_manager_with_real_system_tools(mode_manager=_FakeModeManager([]))
        tools_path = Path(__file__).resolve().parent.parent / "user" / "tools.example.json"

        await manager.init_tools(str(tools_path), {})

        schema = next(
            tool
            for tool in manager.get_all_tools()
            if tool.get("function", {}).get("name") == "emit_progress_notice"
        )
        description = schema["function"]["description"]
        self.assertIn("must call", description)
        self.assertIn("time-consuming", description)
        self.assertIn("May be called multiple times", description)

    async def test_v4_scheduler_job_tool_hides_configured_tools_without_runtime_implementation(self):
        manager = self._build_manager_with_real_system_tools(mode_manager=_FakeModeManager([]))
        tools_path = Path(__file__).resolve().parent.parent / "user" / "tools.example.json"

        await manager.init_tools(str(tools_path), {})
        manager.tools_schema_dict["chain_tools"].append(
            {
                "type": "function",
                "function": {
                    "name": "configured_without_runtime_impl",
                    "description": "Configured tool without a runtime implementation.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
        )

        visible_names = {
            tool["function"]["name"]
            for tool in manager.get_all_tools()
        }
        self.assertIn("manage_scheduled_jobs", visible_names)
        self.assertNotIn("configured_without_runtime_impl", visible_names)

    async def test_core_local_tools_fail_without_tool_router(self):
        with tempfile.TemporaryDirectory() as trusted_dir:
            manager = self._build_manager_with_real_system_tools(mode_manager=_FakeModeManager([trusted_dir]))
            real_system_tools.init_system_tools(None, None, "missing.json", allow_local_fallback=False)
            real_system_tools.set_tool_router(None)
            self.addCleanup(real_system_tools.set_tool_router, None)
            self.addCleanup(real_system_tools.set_local_fallback_enabled, True)

            command_result = await manager.call_tool(
                "exec_sys_cmd",
                {"cmd": 'python -c "print(123)"'},
                route_context={"tool_bundle": ["exec_sys_cmd"], "mcp_servers": [], "current_mode": "general"},
            )
            read_result = await manager.call_tool(
                "read_local_documents",
                {"paths": [str(Path(trusted_dir) / "notes.md")]},
                route_context={"tool_bundle": ["read_local_documents"], "mcp_servers": [], "current_mode": "general"},
            )

            self.assertFalse(command_result.ok)
            self.assertEqual(command_result.error.code, "local_endpoint_required")
            self.assertEqual(command_result.error.details["tool_key"], "shell.exec")
            self.assertFalse(read_result.ok)
            self.assertEqual(read_result.error.code, "local_endpoint_required")
            self.assertEqual(read_result.error.details["tool_key"], "file.read")

    async def test_exec_core_cmd_runs_allowed_command_on_core_host(self):
        manager = self._build_manager_with_real_system_tools(mode_manager=_FakeModeManager([]))
        real_system_tools.init_system_tools(
            None,
            None,
            "missing.json",
            allow_local_fallback=False,
            core_shell_exec_enabled=True,
            core_cmd_policy_path="missing-core-policy.json",
            core_command_timeout_seconds=10,
            core_command_output_max_chars=20000,
        )
        self.addCleanup(real_system_tools.set_tool_router, None)
        self.addCleanup(real_system_tools.set_local_fallback_enabled, True)

        result = await manager.call_tool(
            "exec_core_cmd",
            {"cmd": "echo hello"},
            route_context={"tool_bundle": ["exec_core_cmd"], "mcp_servers": [], "current_mode": "automation"},
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.content.data["command"], "echo hello")
        self.assertEqual(result.content.data["returncode"], 0)
        self.assertIn("hello", result.content.data["stdout"].lower())
        self.assertEqual(result.content.data["cwd"], str(Path.cwd()))

    async def test_exec_core_cmd_rejects_non_whitelisted_command(self):
        manager = self._build_manager_with_real_system_tools(mode_manager=_FakeModeManager([]))
        real_system_tools.init_system_tools(
            None,
            None,
            "missing.json",
            allow_local_fallback=False,
            core_shell_exec_enabled=True,
            core_cmd_policy_path="missing-core-policy.json",
        )
        self.addCleanup(real_system_tools.set_local_fallback_enabled, True)

        result = await manager.call_tool(
            "exec_core_cmd",
            {"cmd": f'"{sys.executable}" -c "print(123)"'},
            route_context={"tool_bundle": ["exec_core_cmd"], "mcp_servers": [], "current_mode": "automation"},
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "core_command_blocked")
        self.assertEqual(result.error.details["policy_status"], "blocked")

    async def test_exec_core_cmd_times_out_and_kills_process(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            python_prefix = f'"{sys.executable}" -c'
            policy_path = Path(tmp_dir) / "core-policy.json"
            policy_path.write_text(
                json.dumps({"mode": "whitelist", "whitelist": [python_prefix], "blacklist_patterns": []}),
                encoding="utf-8",
            )
            manager = self._build_manager_with_real_system_tools(mode_manager=_FakeModeManager([]))
            real_system_tools.init_system_tools(
                None,
                None,
                "missing.json",
                allow_local_fallback=False,
                core_shell_exec_enabled=True,
                core_cmd_policy_path=str(policy_path),
                core_command_timeout_seconds=1,
            )
            self.addCleanup(real_system_tools.set_local_fallback_enabled, True)

            command = f'{python_prefix} "__import__(\'time\').sleep(2)"'
            result = await manager.call_tool(
                "exec_core_cmd",
                {"cmd": command, "timeout_seconds": 1},
                route_context={"tool_bundle": ["exec_core_cmd"], "mcp_servers": [], "current_mode": "automation"},
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "core_command_timeout")
        self.assertEqual(result.error.details["timeout_seconds"], 1)
        self.assertTrue(result.error.retryable)

    async def test_exec_core_cmd_hidden_and_blocked_when_disabled(self):
        manager = self._build_manager_with_real_system_tools(mode_manager=_FakeModeManager([]))
        tools_path = Path(__file__).resolve().parent.parent / "user" / "tools.example.json"
        real_system_tools.init_system_tools(
            None,
            None,
            "missing.json",
            allow_local_fallback=False,
            core_shell_exec_enabled=False,
            core_cmd_policy_path="missing-core-policy.json",
        )
        self.addCleanup(
            real_system_tools.init_system_tools,
            None,
            None,
            "missing.json",
            True,
            True,
            "missing-core-policy.json",
        )
        await manager.init_tools(str(tools_path), {})

        visible_names = {
            tool["function"]["name"]
            for tool in manager.get_all_tools(
                route_context={"tool_bundle": ["exec_core_cmd"], "mcp_servers": [], "current_mode": "automation"}
            )
        }
        blocked = await manager.call_tool(
            "exec_core_cmd",
            {"cmd": "echo hello"},
            route_context={"tool_bundle": ["exec_core_cmd"], "mcp_servers": [], "current_mode": "automation"},
        )

        self.assertNotIn("exec_core_cmd", visible_names)
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.error.code, "core_command_blocked")
        self.assertIn("disabled", blocked.error.details["policy_reason"].lower())

    async def test_brain_route_call_normalizes_structured_result(self):
        brain = Brain(
            adapter=None,
            tools_manager=_StructuredToolsManager(),
            context_manager=_FakeContextManager(),
            event_bus=None,
            exception_router=None,
        )
        brain._http_session = _FakeRuntimeSession()

        result = await brain._call_tool_with_route(
            "lookup_profile",
            {},
            session_id="session-1",
            source=None,
            tool_activity_callback=None,
            route_context={"current_mode": "general"},
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.tool_name, "lookup_profile")
        self.assertEqual(result.content.data, {"ok": True})
        self.assertIn('"tool_name": "lookup_profile"', brain._tool_message_content(result))

    async def test_emit_progress_notice_uses_runtime_context(self):
        manager = self._build_manager_with_real_system_tools(mode_manager=_FakeModeManager([]))
        delivered = {}

        async def emitter(content, session_id="", source=None, turn_id=""):
            delivered.update(
                {
                    "content": content,
                    "session_id": session_id,
                    "source": source,
                    "turn_id": turn_id,
                }
            )
            return {
                "delivered": True,
                "session_id": session_id,
                "turn_id": turn_id,
            }

        real_system_tools.set_progress_notice_emitter(emitter)
        self.addCleanup(real_system_tools.set_progress_notice_emitter, None)
        token = bind_event_context(
            session_id="session-ctx",
            turn_id="turn-ctx",
            source={"kind": "thread", "thread_id": "thr-1"},
        )
        try:
            result = await manager.call_tool(
                "emit_progress_notice",
                {"content": "Working on it"},
                route_context={"tool_bundle": ["emit_progress_notice"], "mcp_servers": [], "current_mode": "general"},
            )
        finally:
            reset_event_context(token)

        self.assertTrue(result.ok)
        self.assertEqual(delivered["content"], "Working on it")
        self.assertEqual(delivered["session_id"], "session-ctx")
        self.assertEqual(delivered["turn_id"], "turn-ctx")
        self.assertEqual(result.content.data["delivered"], True)
        self.assertEqual(result.content.data["session_id"], "session-ctx")


if __name__ == "__main__":
    unittest.main()
