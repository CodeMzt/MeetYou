from __future__ import annotations

import unittest
raise unittest.SkipTest("Legacy Desktop Agent MCP tests were replaced by Desktop Client coverage.")

import asyncio
import unittest

from desktop_agent.config import DesktopAgentConfig
from desktop_agent.mcp_runtime import DesktopAgentMCPRuntime
from desktop_agent.protocol import build_capabilities_snapshot
from desktop_agent.runtime import DesktopAgentRuntime


class _FakeMCPManager:
    def __init__(self):
        self.mcp_tools = {
            "filesystem_tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file from MCP",
                        "parameters": {"type": "object"},
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "description": "Write a file through MCP",
                        "parameters": {"type": "object"},
                    },
                }
            ]
        }

    async def init_mcp_servers(self, mcp_servers: dict):
        self.last_servers = dict(mcp_servers)

    async def call_mcp_tool(self, tool_name: str, tool_args: dict):
        return {"tool_name": tool_name, "tool_args": dict(tool_args)}

    async def close_mcp_servers(self):
        return None

    def get_server_diagnostics(self):
        return []


class DesktopAgentMCPRuntimeTests(unittest.TestCase):
    def test_mcp_runtime_exposes_capabilities(self):
        config = DesktopAgentConfig(agent_id="desktop-main-agent", workspace_ids=["personal"])
        runtime = DesktopAgentMCPRuntime(config, manager=_FakeMCPManager())
        asyncio.run(runtime.initialize())
        capabilities = runtime.capability_definitions()

        capability_map = {item["tool_name"]: item for item in capabilities}

        self.assertEqual(len(capabilities), 2)
        self.assertEqual(
            capability_map["read_file"]["capability_id"],
            "agent.desktop-main-agent.mcp.filesystem_tools.read_file",
        )
        self.assertEqual(capability_map["read_file"]["workspace_ids"], ["personal"])
        self.assertEqual(capability_map["read_file"]["risk_level"], "read")
        self.assertFalse(capability_map["read_file"]["requires_confirmation"])
        self.assertEqual(capability_map["write_file"]["risk_level"], "local_write")
        self.assertTrue(capability_map["write_file"]["requires_confirmation"])

    def test_mcp_runtime_calls_underlying_tool(self):
        config = DesktopAgentConfig(agent_id="desktop-main-agent", workspace_ids=["personal"])
        runtime = DesktopAgentMCPRuntime(config, manager=_FakeMCPManager())
        asyncio.run(runtime.initialize())
        result = asyncio.run(runtime.call_capability(
            "agent.desktop-main-agent.mcp.filesystem_tools.read_file",
            {"path": "demo.txt"},
        ))

        self.assertEqual(result["tool_name"], "read_file")
        self.assertEqual(result["payload"]["tool_args"]["path"], "demo.txt")

    def test_runtime_includes_mcp_capabilities_in_snapshot(self):
        config = DesktopAgentConfig(agent_id="desktop-main-agent", workspace_ids=["personal"])
        runtime = DesktopAgentRuntime(config)
        runtime._mcp_runtime = DesktopAgentMCPRuntime(config, manager=_FakeMCPManager())  # noqa: SLF001
        asyncio.run(runtime._mcp_runtime.initialize())  # noqa: SLF001
        snapshot = build_capabilities_snapshot(
            config,
            revision=7,
            extra_capabilities=runtime._mcp_runtime.capability_definitions(),  # noqa: SLF001
        )

        capability_ids = {item["capability_id"] for item in snapshot["payload"]["capabilities"]}
        self.assertIn("agent.desktop-main-agent.mcp.filesystem_tools.read_file", capability_ids)
        self.assertIn("agent.desktop-main-agent.mcp.filesystem_tools.write_file", capability_ids)
