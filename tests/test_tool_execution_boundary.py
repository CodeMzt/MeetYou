from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.app import App
from core.config import ConfigManager
from core.tools_manager import ToolsManager
from desktop_agent.config import DesktopAgentConfig
from desktop_agent.protocol import build_capabilities_snapshot
from tools import system_tools
from tools.document_tools import DocumentTools


class _FakeModeManager:
    def __init__(self, trusted_roots: list[str]):
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
        resolved = str(Path(path_value).resolve())
        return any(resolved == root or resolved.startswith(f"{root}{os.sep}") for root in self._trusted_roots)


class _RecordingDispatcher:
    def __init__(self):
        self.calls: list[dict] = []

    async def dispatch_agent_capability(self, **kwargs):
        return await self.dispatch_local_capability(**kwargs)

    async def dispatch_local_capability(self, **kwargs):
        self.calls.append(dict(kwargs))
        suffix = kwargs["capability_suffix"]
        if suffix == "shell.exec":
            return {"stdout": "ok", "summary": "ok"}
        if suffix == "file.read":
            return {"summary": "read", "content": "hello", "size_bytes": 5}
        if suffix == "file.write":
            return {"summary": "write", "bytes_written": 5}
        raise AssertionError(f"Unexpected capability suffix: {suffix}")


class _FakeHeart:
    async def get_background_status(self):
        return {
            "schedule": {"due_task_count": 0},
            "execution": {},
            "delivery": {},
            "system": {},
            "background_status_sources": [],
        }


class _FakeBrain:
    def get_session_debug_snapshot(self, session_id: str):
        return {
            "session_id": session_id,
            "route": {"current_mode": "documents", "tool_bundle": ["read_local_documents"]},
            "route_history": [],
            "context_plan": {},
            "memory_scope": {"session_id": session_id},
            "authorization": {"recent_decisions": []},
            "object_operations": [],
            "reply_control": {},
            "checkpoints": [],
            "runtime_state": {"session_id": session_id},
            "usage": {"session_id": session_id},
            "request": {},
            "compression": {},
            "last_failure": {},
            "updated_at": "2026-04-24T00:00:00Z",
        }


class ToolExecutionBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def _build_tools_manager(self, *, mcp_tool_map: dict[str, str] | None = None) -> ToolsManager:
        memory = SimpleNamespace(save_memory=None, recall_memory=None, recall_memory_structured=None)
        context_manager = SimpleNamespace(update_context=None)
        mcp_manager = SimpleNamespace(
            tool_map=dict(mcp_tool_map or {}),
            mcp_servers_list=[],
            mcp_tools={},
            init_mcp_servers=self._noop_async,
            call_mcp_tool=self._noop_async,
        )
        return ToolsManager(memory, context_manager, mcp_manager, system_tools, mode_manager=_FakeModeManager([]))

    async def _noop_async(self, *args, **kwargs):
        del args, kwargs
        return None

    async def test_local_file_and_shell_tools_must_use_agent_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dispatcher = _RecordingDispatcher()
            tools = DocumentTools(_FakeModeManager([tmp_dir]), agent_dispatcher=dispatcher, allow_local_fallback=False)
            target = Path(tmp_dir) / "boundary.md"

            await tools.write_local_document(str(target), "hello", preview=False, confirmed=True, session_id="sess-1")
            await tools.read_local_documents([str(target)], session_id="sess-1")

            system_tools.set_capability_dispatcher(dispatcher)
            system_tools.set_local_fallback_enabled(False)
            self.addCleanup(system_tools.set_capability_dispatcher, None)
            self.addCleanup(system_tools.set_local_fallback_enabled, True)
            await system_tools.exec_sys_cmd("echo ok", session_id="sess-1")

            self.assertFalse(target.exists(), "core process should not directly write local file when dispatcher is used")
            self.assertEqual(dispatcher.calls[0]["capability_suffix"], "file.write")
            self.assertEqual(dispatcher.calls[1]["capability_suffix"], "file.read")
            self.assertEqual(dispatcher.calls[2]["capability_suffix"], "shell.exec")

    async def test_config_separates_core_mcp_and_desktop_agent_local_mcp_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "user").mkdir()
            (root / "user" / "config.json").write_text(
                json.dumps({"api_provider": "openai", "model": "gpt-4o"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "user" / "core_mcp_servers.json").write_text(
                json.dumps({"mcpServers": {"core_docs": {"command": "python", "enabled": True}}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "user" / "mcp_servers.json").write_text(
                json.dumps({"mcpServers": {"desktop_local": {"command": "npx", "enabled": True}}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / ".env").write_text("MEETYOU_API_KEY=test\n", encoding="utf-8")

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                config = ConfigManager(config_file_path=str(root / "user" / "config.json"), env_file_path=str(root / ".env"))
                diagnostic = config.get_mcp_server_config_diagnostic()
            finally:
                os.chdir(old_cwd)

            self.assertEqual(sorted(config.get_mcp_servers()), ["core_docs"])
            self.assertEqual(diagnostic["path"], "user/core_mcp_servers.json")
            desktop_payload = json.loads((root / "user" / "mcp_servers.json").read_text(encoding="utf-8"))
            self.assertIn("desktop_local", desktop_payload["mcpServers"])

    async def test_capability_snapshot_and_boundary_diagnostics_keep_core_agent_split(self):
        snapshot = build_capabilities_snapshot(
            DesktopAgentConfig(agent_id="desktop-main-agent", workspace_ids=["desktop-main"])
        )
        capability_suffixes = {
            capability["capability_id"].removeprefix("agent.desktop-main-agent.")
            for capability in snapshot["payload"]["capabilities"]
        }
        self.assertIn("file.read", capability_suffixes)
        self.assertIn("file.write", capability_suffixes)
        self.assertIn("shell.exec", capability_suffixes)

        manager = self._build_tools_manager(mcp_tool_map={"core_lookup": "core_docs"})
        diagnostics = manager.get_tool_execution_boundary_snapshot()
        tools = {item["tool_name"]: item for item in diagnostics["tools"]}

        self.assertEqual(tools["read_local_documents"]["executor_owner"], "agent_dispatch")
        self.assertEqual(tools["write_local_document"]["source_type"], "builtin_agent_proxy")
        self.assertEqual(tools["danxi_list_posts"]["executor_owner"], "core")
        self.assertEqual(tools["core_lookup"]["executor_owner"], "core_mcp")
        self.assertEqual(diagnostics["core_mcp_config_path"], "user/core_mcp_servers.json")
        self.assertEqual(diagnostics["desktop_agent_mcp_config_path"], "user/mcp_servers.json")

    async def test_runtime_debug_includes_tool_execution_boundary_matrix(self):
        app = App.__new__(App)
        app.brain = _FakeBrain()
        app.heart = _FakeHeart()
        app.tools_manager = SimpleNamespace(
            get_route_debug_snapshot=lambda _route: {"visible_tools": ["read_local_documents"], "candidate_tools": [], "authorization_preview": []},
            get_tool_execution_boundary_snapshot=lambda: {
                "tools": [
                    {
                        "tool_name": "read_local_documents",
                        "source_type": "builtin_agent_proxy",
                        "executor_owner": "agent_dispatch",
                        "risk": "read",
                        "parallelizable": True,
                    }
                ]
            },
        )
        app._interaction_responses = None
        app.event_bus = None
        app.get_core_mcp_diagnostics = lambda: {"summary": {"configured_server_count": 0}}

        payload = await App.get_runtime_debug(app, "sess-1")

        self.assertIn("tool_execution_boundary", payload)
        boundary = payload["tool_execution_boundary"]
        self.assertIn("tools", boundary)
        self.assertEqual(boundary["tools"][0]["executor_owner"], "agent_dispatch")


if __name__ == "__main__":
    unittest.main()
