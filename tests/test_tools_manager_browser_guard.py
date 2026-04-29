import os
import sys
import json
from types import SimpleNamespace
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools_manager import (
    ToolsManager,
    _get_mcp_timeout_seconds,
    _should_expose_mcp_tool,
)


class ToolsManagerExposureTests(unittest.TestCase):
    def test_core_owned_tools_register_with_tool_router(self):
        memory = SimpleNamespace(
            save_memory=None,
            recall_memory=None,
            recall_memory_structured=None,
        )
        context_manager = SimpleNamespace(update_context=None)
        mcp_manager = SimpleNamespace(tool_map={})
        system_tools = SimpleNamespace(
            exec_sys_cmd=lambda **kwargs: kwargs,
            get_current_system_time=lambda: {"now": "2026-04-29T00:00:00Z"},
            get_sys_vitals=None,
        )
        manager = ToolsManager(memory, context_manager, mcp_manager, system_tools)

        class _Router:
            def __init__(self):
                self.handlers = {}

            def register_core_tool(self, tool_name, handler):
                self.handlers[tool_name] = handler

        router = _Router()
        manager.set_tool_router(router)

        self.assertIn("send_delivery_message", router.handlers)
        self.assertIn("create_scheduled_workflow", router.handlers)
        self.assertIn("list_delivery_targets", router.handlers)
        self.assertIn("get_current_system_time", router.handlers)
        self.assertIn("manage_threads", router.handlers)
        self.assertNotIn("exec_sys_cmd", router.handlers)

    def test_tools_example_schema_does_not_repeat_tool_names(self):
        with open(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user", "tools.example.json"),
            "r",
            encoding="utf-8",
        ) as fh:
            payload = json.load(fh)

        seen: set[str] = set()
        duplicates: set[str] = set()
        for section in payload.values():
            if not isinstance(section, list):
                continue
            for tool in section:
                tool_name = str(tool.get("function", {}).get("name") or "").strip()
                if not tool_name:
                    continue
                if tool_name in seen:
                    duplicates.add(tool_name)
                    continue
                seen.add(tool_name)

        self.assertEqual(duplicates, set())

    def test_browser_tools_use_longer_timeout(self):
        self.assertEqual(_get_mcp_timeout_seconds("browser_navigate"), 30.0)
        self.assertEqual(_get_mcp_timeout_seconds("read_file"), 10.0)

    def test_raw_browser_tools_are_hidden_from_llm(self):
        self.assertFalse(_should_expose_mcp_tool("browser_navigate"))
        self.assertFalse(_should_expose_mcp_tool("browser_snapshot"))

    def test_raw_tavily_tools_are_hidden_from_llm(self):
        self.assertFalse(_should_expose_mcp_tool("tavily-search"))
        self.assertFalse(_should_expose_mcp_tool("tavily-extract"))

    def test_raw_notion_tools_are_hidden_from_llm(self):
        self.assertFalse(_should_expose_mcp_tool("post-search", "notion_knowledge"))

    def test_non_search_mcp_tools_remain_visible(self):
        self.assertTrue(_should_expose_mcp_tool("read_file"))

    def test_main_llm_sees_high_level_chain_tools_only(self):
        memory = SimpleNamespace(
            save_memory=None,
            recall_memory=None,
            recall_memory_structured=None,
        )
        context_manager = SimpleNamespace(update_context=None)
        mcp_manager = SimpleNamespace(tool_map={})
        system_tools = SimpleNamespace(
            exec_sys_cmd=None,
            get_current_system_time=None,
            get_sys_vitals=None,
        )
        manager = ToolsManager(memory, context_manager, mcp_manager, system_tools)
        with open(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user", "tools.json"),
            "r",
            encoding="utf-8",
        ) as fh:
            manager.tools_schema_dict = json.load(fh)

        visible_names = {
            tool["function"]["name"]
            for tool in manager.get_all_tools()
        }

        self.assertIn("research_topic", visible_names)
        self.assertIn("inspect_page", visible_names)
        self.assertIn("search_knowledge", visible_names)
        self.assertIn("manage_tasks", visible_names)
        self.assertIn("list_skills", visible_names)
        self.assertIn("load_skill", visible_names)
        self.assertIn("create_skill", visible_names)
        self.assertIn("list_attachments", visible_names)
        self.assertIn("read_attachment", visible_names)
        self.assertIn("delete_attachment", visible_names)
        self.assertIn("remember_knowledge", visible_names)
        self.assertNotIn("search_memory", visible_names)
        self.assertNotIn("search_web", visible_names)
        self.assertNotIn("recall_memory", visible_names)
        self.assertNotIn("recall_memory_structured", visible_names)
        self.assertNotIn("update_context", visible_names)
        self.assertNotIn("analyze_workspace", visible_names)

    def test_route_context_filters_tool_bundle(self):
        memory = SimpleNamespace(
            save_memory=None,
            recall_memory=None,
            recall_memory_structured=None,
        )
        context_manager = SimpleNamespace(update_context=None)
        mcp_manager = SimpleNamespace(tool_map={})
        system_tools = SimpleNamespace(
            exec_sys_cmd=None,
            get_current_system_time=None,
            get_sys_vitals=None,
        )
        fake_mode_manager = SimpleNamespace()
        manager = ToolsManager(memory, context_manager, mcp_manager, system_tools, fake_mode_manager)
        with open(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user", "tools.json"),
            "r",
            encoding="utf-8",
        ) as fh:
            manager.tools_schema_dict = json.load(fh)

        visible_names = {
            tool["function"]["name"]
            for tool in manager.get_all_tools(
                route_context={
                    "tool_bundle": ["analyze_workspace", "read_local_documents", "compile_report"],
                    "mcp_servers": [],
                }
            )
        }

        self.assertIn("analyze_workspace", visible_names)
        self.assertIn("read_local_documents", visible_names)
        self.assertIn("compile_report", visible_names)
        self.assertNotIn("research_topic", visible_names)
        self.assertNotIn("manage_schedule", visible_names)

    def test_route_context_can_expose_bundled_memory_and_web_primitives(self):
        memory = SimpleNamespace(
            save_memory=None,
            recall_memory=None,
            recall_memory_structured=None,
        )
        context_manager = SimpleNamespace(update_context=None)
        mcp_manager = SimpleNamespace(tool_map={})
        system_tools = SimpleNamespace(
            exec_sys_cmd=None,
            get_current_system_time=None,
            get_sys_vitals=None,
        )
        manager = ToolsManager(memory, context_manager, mcp_manager, system_tools)
        with open(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user", "tools.json"),
            "r",
            encoding="utf-8",
        ) as fh:
            manager.tools_schema_dict = json.load(fh)

        visible_names = {
            tool["function"]["name"]
            for tool in manager.get_all_tools(
                route_context={
                    "tool_bundle": ["search_memory", "search_web", "read_web_page"],
                    "mcp_servers": [],
                }
            )
        }

        self.assertIn("search_memory", visible_names)
        self.assertIn("search_web", visible_names)
        self.assertIn("read_web_page", visible_names)
        self.assertNotIn("research_topic", visible_names)

    def test_heartbeat_tools_use_explicit_allowlist(self):
        memory = SimpleNamespace(
            save_memory=None,
            recall_memory=None,
            recall_memory_structured=None,
        )
        context_manager = SimpleNamespace(update_context=None)
        mcp_manager = SimpleNamespace(tool_map={})
        system_tools = SimpleNamespace(
            exec_sys_cmd=None,
            get_current_system_time=None,
            get_sys_vitals=None,
            get_background_status=None,
        )
        manager = ToolsManager(memory, context_manager, mcp_manager, system_tools)
        with open(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user", "tools.json"),
            "r",
            encoding="utf-8",
        ) as fh:
            manager.tools_schema_dict = json.load(fh)

        visible_names = {tool["function"]["name"] for tool in manager.get_heartbeat_tools()}
        self.assertEqual(
            visible_names,
            {"get_background_status", "get_current_system_time", "get_sys_vitals"},
        )

    def test_duplicate_mcp_tool_names_are_exposed_once(self):
        memory = SimpleNamespace(
            save_memory=None,
            recall_memory=None,
            recall_memory_structured=None,
        )
        context_manager = SimpleNamespace(update_context=None)
        mcp_manager = SimpleNamespace(tool_map={"shared_tool": "server_b"})
        system_tools = SimpleNamespace(
            exec_sys_cmd=None,
            get_current_system_time=None,
            get_sys_vitals=None,
        )
        manager = ToolsManager(memory, context_manager, mcp_manager, system_tools)
        manager.tools_schema_dict = {
            "common_tools": [],
            "chain_tools": [],
            "memory_tools": [],
            "background_tools": [],
            "web_tools": [],
            "mcp_tools": [
                {"type": "function", "function": {"name": "shared_tool", "description": "from a"}},
                {"type": "function", "function": {"name": "shared_tool", "description": "from b"}},
            ],
        }

        visible_names = [
            tool["function"]["name"]
            for tool in manager.get_all_tools()
        ]

        self.assertEqual(visible_names.count("shared_tool"), 1)


if __name__ == "__main__":
    unittest.main()
