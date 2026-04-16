from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_sdk.capability_ids import build_mcp_capability_id, slug_capability_segment
from agent_sdk.risk import ToolRiskClassifier
from desktop_agent.config import DesktopAgentConfig
from tools.mcp import MCPManager


class DesktopAgentMCPRuntime:
    def __init__(self, config: DesktopAgentConfig, manager: MCPManager | None = None):
        self._config = config
        self._manager = manager or MCPManager()
        self._risk_classifier = ToolRiskClassifier()
        self._initialized = False
        self._capability_map: dict[str, dict[str, Any]] = {}

    async def initialize(self) -> None:
        if self._initialized:
            return
        servers = self._load_server_config(self._config.resolved_mcp_servers_path)
        await self._manager.init_mcp_servers(servers)
        self._rebuild_capability_map()
        self._initialized = True

    async def close(self) -> None:
        await self._manager.close_mcp_servers()
        self._initialized = False
        self._capability_map.clear()

    def capability_definitions(self) -> list[dict[str, Any]]:
        return [dict(payload) for payload in self._capability_map.values()]

    def can_handle(self, capability_id: str) -> bool:
        return capability_id in self._capability_map

    async def call_capability(self, capability_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        entry = self._capability_map.get(capability_id)
        if entry is None:
            raise ValueError(f"Unknown MCP capability: {capability_id}")
        result = await self._manager.call_mcp_tool(entry["tool_name"], dict(arguments or {}))
        if isinstance(result, dict):
            payload = result
        elif hasattr(result, "model_dump"):
            payload = result.model_dump(mode="json")
        elif hasattr(result, "dict"):
            payload = result.dict()
        else:
            payload = {"value": result}
        return {
            "summary": f"MCP tool completed: {entry['tool_name']}",
            "server_name": entry["server_name"],
            "tool_name": entry["tool_name"],
            "payload": payload,
        }

    def get_server_diagnostics(self) -> list[dict[str, Any]]:
        return self._manager.get_server_diagnostics()

    @staticmethod
    def _load_server_config(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            servers = payload.get("mcpServers")
            if isinstance(servers, dict):
                return servers
        return {}

    def _rebuild_capability_map(self) -> None:
        mapping: dict[str, dict[str, Any]] = {}
        for server_name, tools in self._manager.mcp_tools.items():
            for tool in tools:
                function = tool.get("function", {}) if isinstance(tool, dict) else {}
                tool_name = str(function.get("name") or "").strip()
                if not tool_name:
                    continue
                risk_level = self._risk_classifier.get_tool_action_risk(tool_name)
                capability_id = build_mcp_capability_id(self._config.agent_id, server_name, tool_name)
                mapping[capability_id] = {
                    "capability_id": capability_id,
                    "kind": "tool",
                    "title": str(function.get("description") or tool_name),
                    "tags": ["desktop", "mcp", slug_capability_segment(server_name)],
                    "risk_level": risk_level,
                    "requires_confirmation": risk_level != "read",
                    "workspace_ids": list(self._config.workspace_ids),
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "input_schema": function.get("parameters") if isinstance(function.get("parameters"), dict) else {},
                }
        self._capability_map = mapping
