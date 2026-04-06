import json
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools_manager import ToolsManager


class LightweightToolsTests(unittest.IsolatedAsyncioTestCase):
    def _build_manager(self):
        memory = SimpleNamespace(
            save_memory=None,
            recall_memory=None,
            recall_memory_structured=None,
        )
        context_manager = SimpleNamespace(update_context=None)
        mcp_manager = SimpleNamespace(tool_map={}, get_server_diagnostics=lambda: [])
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
        return manager

    async def test_lightweight_tools_are_registered_and_callable(self):
        manager = self._build_manager()

        visible_names = {tool["function"]["name"] for tool in manager.get_all_tools()}
        self.assertIn("summarize_text", visible_names)
        self.assertIn("organize_notes", visible_names)
        self.assertIn("extract_action_items", visible_names)

        summary = await manager.call_tool("summarize_text", {"text": "Line one. Line two with action items. Line three."})
        self.assertTrue(summary.ok)
        payload = json.loads(summary.content.text)
        self.assertEqual(payload["tool"], "summarize_text")
        self.assertTrue(payload["highlights"])

        notes = await manager.call_tool(
            "organize_notes",
            {"text": "Kickoff notes. Action item: draft update tomorrow. Owner pending."},
        )
        self.assertTrue(notes.ok)
        notes_payload = json.loads(notes.content.text)
        self.assertEqual(notes_payload["tool"], "organize_notes")
        self.assertTrue(notes_payload["sections"])

    async def test_route_debug_snapshot_surfaces_degradation_notes(self):
        manager = self._build_manager()

        snapshot = manager.get_route_debug_snapshot(
            {
                "tool_bundle": ["summarize_text"],
                "mcp_servers": [],
                "capability_set": {
                    "mcp_diagnostics": [
                        {
                            "server_name": "tavily_web",
                            "status": "requires_auth",
                            "usable": False,
                            "fallback_tools": ["research_topic", "summarize_text"],
                            "degraded": True,
                        }
                    ],
                    "degradation_notes": [
                        {
                            "capability_type": "mcp_server",
                            "capability_id": "tavily_web",
                            "status": "requires_auth",
                            "fallback_tools": ["research_topic", "summarize_text"],
                        }
                    ],
                },
            }
        )

        self.assertEqual(snapshot["candidate_tools"], ["summarize_text"])
        self.assertEqual(snapshot["mcp_server_diagnostics"][0]["server_name"], "tavily_web")
        self.assertEqual(snapshot["degradation_notes"][0]["capability_id"], "tavily_web")


if __name__ == "__main__":
    unittest.main()
