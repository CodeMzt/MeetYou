import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.config import ConfigManager
from core.tools_manager import ToolsManager
from tools import system_tools as real_system_tools


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


class _RecordingDispatcher:
    def __init__(self):
        self.calls = []

    async def dispatch_agent_capability(self, **kwargs):
        self.calls.append(dict(kwargs))
        suffix = kwargs.get("capability_suffix")
        if suffix == "file.read":
            path = str(kwargs.get("arguments", {}).get("path") or "")
            return {"summary": path, "content": "alpha\nbeta", "size_bytes": 10}
        return {"summary": "ok", "stdout": "ok", "bytes_written": 2}


class ToolExecutionBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def _build_manager(self, *, mode_manager):
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

    async def _noop_async(self, *args, **kwargs):
        del args, kwargs
        return None

    async def test_local_file_tools_require_agent_dispatch(self):
        with tempfile.TemporaryDirectory() as trusted_dir:
            manager = self._build_manager(mode_manager=_FakeModeManager([trusted_dir]))
            real_system_tools.init_system_tools(None, None, "missing.json", allow_local_fallback=False)
            real_system_tools.set_agent_dispatcher(None)
            self.addCleanup(real_system_tools.set_agent_dispatcher, None)
            self.addCleanup(real_system_tools.set_local_fallback_enabled, True)
            route_context = {"tool_bundle": ["read_local_documents"], "mcp_servers": [], "current_mode": "documents"}

            result = await manager.call_tool(
                "read_local_documents",
                {"paths": [str(Path(trusted_dir) / "notes.md")]},
                route_context=route_context,
            )
            self.assertFalse(result.ok)
            self.assertEqual(result.error.code, "local_agent_required")
            self.assertEqual(result.error.details["capability_suffix"], "file.read")

            dispatcher = _RecordingDispatcher()
            manager.set_capability_dispatcher(dispatcher)
            real_system_tools.set_agent_dispatcher(dispatcher)
            dispatched = await manager.call_tool(
                "read_local_documents",
                {"paths": [str(Path(trusted_dir) / "notes.md")]},
                route_context=route_context,
            )
            self.assertTrue(dispatched.ok)
            self.assertEqual(dispatcher.calls[0]["capability_suffix"], "file.read")

    async def test_compile_report_does_not_read_local_files_in_core(self):
        with tempfile.TemporaryDirectory() as trusted_dir:
            local_path = Path(trusted_dir) / "notes.md"
            local_path.write_text("local-only", encoding="utf-8")
            manager = self._build_manager(mode_manager=_FakeModeManager([trusted_dir]))

            blocked = await manager.call_tool(
                "compile_report",
                {"inputs": [str(local_path)], "format": "markdown"},
                route_context={"tool_bundle": ["compile_report"], "current_mode": "documents"},
            )
            self.assertFalse(blocked.ok)
            self.assertEqual(blocked.error.code, "local_agent_required")

            dispatcher = _RecordingDispatcher()
            manager.set_capability_dispatcher(dispatcher)
            dispatched = await manager.call_tool(
                "compile_report",
                {"inputs": [str(local_path)], "format": "markdown"},
                route_context={"tool_bundle": ["compile_report"], "current_mode": "documents"},
            )
            self.assertTrue(dispatched.ok)
            self.assertEqual(dispatcher.calls[0]["capability_suffix"], "file.read")

    def test_core_and_desktop_mcp_paths_are_isolated(self):
        previous_tavily = os.environ.pop("TAVILY_API_KEY", None)
        self.addCleanup(
            lambda: os.environ.__setitem__("TAVILY_API_KEY", previous_tavily)
            if previous_tavily is not None
            else os.environ.pop("TAVILY_API_KEY", None)
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "user").mkdir(parents=True, exist_ok=True)
            (root / "user" / "config.json").write_text(
                json.dumps({"api_provider": "openai", "model": "gpt-4o"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "user" / "mcp_servers.json").write_text(
                json.dumps({"mcpServers": {"desktop_local": {"command": "npx", "args": ["-y", "desktop-mcp"]}}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / ".env").write_text("", encoding="utf-8")

            config = ConfigManager(
                config_file_path=str(root / "user" / "config.json"),
                env_file_path=str(root / ".env"),
            )
            config._mcp_server_config_path = str(root / "user" / "core_mcp_servers.json")  # noqa: SLF001
            config._load_mcp_config()  # noqa: SLF001
            diagnostic = config.get_mcp_server_config_diagnostic()
            self.assertEqual(config.get_mcp_servers(), {})
            self.assertEqual(diagnostic["status"], "missing")
            self.assertEqual(Path(diagnostic["path"]).name, "core_mcp_servers.json")
            self.assertIn("mcp_servers.json", diagnostic["message"])

    async def test_capability_snapshot_boundary_and_danxi_core_allowlist(self):
        manager = self._build_manager(mode_manager=_FakeModeManager([]))
        before = {item["tool_name"]: item for item in manager.get_tool_execution_boundary_snapshot()}
        self.assertEqual(before["read_local_documents"]["executor_owner"], "agent_required")

        dispatcher = _RecordingDispatcher()
        manager.set_capability_dispatcher(dispatcher)
        after = {item["tool_name"]: item for item in manager.get_tool_execution_boundary_snapshot()}
        self.assertEqual(after["read_local_documents"]["executor_owner"], "agent_dispatch")
        self.assertEqual(after["read_local_documents"]["source_type"], "builtin")
        self.assertEqual(after["read_local_documents"]["risk"], "read")
        self.assertTrue(after["read_local_documents"]["parallel_safe"])

        self.assertEqual(after["danxi_list_posts"]["executor_owner"], "core")
        self.assertEqual(after["danxi_list_posts"]["source_type"], "builtin")
        self.assertTrue(after["danxi_list_posts"]["parallel_safe"])


if __name__ == "__main__":
    unittest.main()
