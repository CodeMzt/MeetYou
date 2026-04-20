from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.app import App


class _FakeModeManager:
    def get_core_mcp_boundary_diagnostics(self, *, available_mcp_servers, configured_mcp_servers):
        del available_mcp_servers, configured_mcp_servers
        return {
            "classification_standard": {},
            "core_mcp_servers": [
                {"server_name": "tavily_web", "status": "configured", "usable": True, "degraded": False},
                {"server_name": "notion_knowledge", "status": "configured", "usable": True, "degraded": False},
                {"server_name": "browser_automation", "status": "configured", "usable": True, "degraded": False},
            ],
            "agent_managed_mcp_servers": [],
            "runtime_native_tools": [],
            "summary": {
                "configured_server_count": 3,
                "enabled_count": 0,
                "partial_failure_count": 0,
                "partial_failure_servers": [],
            },
        }


class AppCoreMcpDiagnosticsTests(unittest.TestCase):
    def test_runtime_failures_are_counted_as_partial_failures(self):
        app = App.__new__(App)
        app.config = SimpleNamespace(
            get_mcp_servers=lambda: {
                "tavily_web": {},
                "notion_knowledge": {},
                "browser_automation": {},
            },
            get_mcp_server_config_diagnostic=lambda: {
                "scope": "core",
                "path": "user/core_mcp_servers.json",
                "status": "loaded",
                "server_count": 3,
            },
        )
        app.mcp_manager = SimpleNamespace(
            get_server_diagnostics=lambda: [
                {
                    "server_name": "tavily_web",
                    "enabled": True,
                    "status": "unavailable",
                    "tool_count": 0,
                    "command": "npx",
                    "error": "Connection closed",
                },
                {
                    "server_name": "notion_knowledge",
                    "enabled": True,
                    "status": "unavailable",
                    "tool_count": 0,
                    "command": "npx",
                    "error": "Connection closed",
                },
                {
                    "server_name": "browser_automation",
                    "enabled": False,
                    "status": "not_enabled",
                    "tool_count": 0,
                    "command": "npx",
                },
            ]
        )
        app.mode_manager = _FakeModeManager()

        diagnostics = App.get_core_mcp_diagnostics(app)

        self.assertEqual(diagnostics["summary"]["configured_server_count"], 3)
        self.assertEqual(diagnostics["summary"]["enabled_count"], 0)
        self.assertEqual(diagnostics["summary"]["partial_failure_count"], 2)
        self.assertEqual(diagnostics["summary"]["partial_failure_servers"], ["notion_knowledge", "tavily_web"])
        core_servers = {item["server_name"]: item for item in diagnostics["core_mcp_servers"]}
        self.assertEqual(core_servers["tavily_web"]["status"], "unavailable")
        self.assertFalse(core_servers["tavily_web"]["usable"])
        self.assertTrue(core_servers["tavily_web"]["degraded"])

    def test_enabled_but_unusable_runtime_server_is_treated_as_partial_failure(self):
        class _SingleServerModeManager:
            def get_core_mcp_boundary_diagnostics(self, *, available_mcp_servers, configured_mcp_servers):
                del available_mcp_servers, configured_mcp_servers
                return {
                    "classification_standard": {},
                    "core_mcp_servers": [
                        {"server_name": "tavily_web", "status": "configured", "usable": True, "degraded": False},
                    ],
                    "agent_managed_mcp_servers": [],
                    "runtime_native_tools": [],
                    "summary": {
                        "configured_server_count": 1,
                        "enabled_count": 0,
                        "partial_failure_count": 0,
                        "partial_failure_servers": [],
                    },
                }

        app = App.__new__(App)
        app.config = SimpleNamespace(
            get_mcp_servers=lambda: {
                "tavily_web": {},
            },
            get_mcp_server_config_diagnostic=lambda: {
                "scope": "core",
                "path": "user/core_mcp_servers.json",
                "status": "loaded",
                "server_count": 1,
            },
        )
        app.mcp_manager = SimpleNamespace(
            get_server_diagnostics=lambda: [
                {
                    "server_name": "tavily_web",
                    "enabled": True,
                    "status": "enabled",
                    "tool_count": 0,
                    "tool_names": [],
                    "usable": False,
                    "degraded": True,
                    "warning": "no_tools_exposed",
                    "command": "npx",
                }
            ]
        )
        app.mode_manager = _SingleServerModeManager()

        diagnostics = App.get_core_mcp_diagnostics(app)

        self.assertEqual(diagnostics["summary"]["configured_server_count"], 1)
        self.assertEqual(diagnostics["summary"]["enabled_count"], 0)
        self.assertEqual(diagnostics["summary"]["partial_failure_count"], 1)
        self.assertEqual(diagnostics["summary"]["partial_failure_servers"], ["tavily_web"])
        core_server = diagnostics["core_mcp_servers"][0]
        self.assertEqual(core_server["status"], "enabled")
        self.assertFalse(core_server["usable"])
        self.assertTrue(core_server["degraded"])
        self.assertEqual(core_server["tool_names"], [])
        self.assertEqual(core_server["warning"], "no_tools_exposed")
