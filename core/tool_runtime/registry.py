from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("meetyou.tools_manager")


class ToolRegistry:
    def __init__(self, mcp_manager, *, supported_funcs: dict[str, Any] | None = None):
        self.tools_schema_dict: dict[str, Any] = {}
        self._mcp_manager = mcp_manager
        self.supported_funcs: dict[str, Any] = dict(supported_funcs or {})

    async def init_tools(self, tools_schema_path: str, mcp_servers: dict[str, Any]) -> None:
        with open(tools_schema_path, "r", encoding="utf-8") as handle:
            self.tools_schema_dict = json.load(handle)

        await self._mcp_manager.init_mcp_servers(mcp_servers)
        self.tools_schema_dict["mcp_tools"] = []
        for server_name in getattr(self._mcp_manager, "mcp_servers_list", []):
            self.tools_schema_dict["mcp_tools"].extend(
                self._mcp_manager.mcp_tools.get(server_name, [])
            )

        logger.info(
            "Tools initialized: built-in=%s, mcp=%s",
            len(self.supported_funcs),
            len(self.tools_schema_dict.get("mcp_tools", [])),
        )

    def has_builtin(self, tool_name: str) -> bool:
        return tool_name in self.supported_funcs

    def get_builtin(self, tool_name: str):
        return self.supported_funcs.get(tool_name)

    def has_mcp(self, tool_name: str) -> bool:
        return tool_name in getattr(self._mcp_manager, "tool_map", {})

    def get_mcp_server(self, tool_name: str) -> str:
        return str(getattr(self._mcp_manager, "tool_map", {}).get(tool_name, ""))

    def _iter_llm_visible_tools(self, *, allowed_tool_names: set[str] | None = None) -> list[dict]:
        tools: list[dict] = []
        seen: set[str] = set()
        for key in ("common_tools", "chain_tools"):
            for tool in self.tools_schema_dict.get(key, []):
                tool_name = tool.get("function", {}).get("name", "")
                if tool_name in seen:
                    continue
                seen.add(tool_name)
                tools.append(tool)
        if allowed_tool_names:
            for key in ("memory_tools", "web_tools"):
                for tool in self.tools_schema_dict.get(key, []):
                    tool_name = tool.get("function", {}).get("name", "")
                    if tool_name not in allowed_tool_names or tool_name in seen:
                        continue
                    seen.add(tool_name)
                    tools.append(tool)
        return tools

    def _tool_schema_by_name(self, tool_name: str, sections: tuple[str, ...] | None = None) -> dict | None:
        keys = sections or ("common_tools", "chain_tools", "memory_tools", "background_tools")
        for key in keys:
            for tool in self.tools_schema_dict.get(key, []):
                function = tool.get("function", {})
                if function.get("name") == tool_name:
                    return tool
        return None

    def get_all_tools(
        self,
        route_context: dict[str, Any] | None = None,
        *,
        should_expose_mcp_tool,
    ) -> list[dict]:
        route_context = route_context or {}
        allowed_tool_names = {
            str(item).strip()
            for item in route_context.get("tool_bundle", [])
            if str(item).strip()
        }
        allowed_mcp_servers = {
            str(item).strip()
            for item in route_context.get("mcp_servers", [])
            if str(item).strip()
        }

        visible_tools: list[dict] = []
        for tool in self._iter_llm_visible_tools(allowed_tool_names=allowed_tool_names):
            function = tool.get("function", {})
            tool_name = function.get("name", "")
            if tool_name not in self.supported_funcs:
                continue
            if allowed_tool_names and tool_name not in allowed_tool_names:
                continue
            visible_tools.append(tool)

        for tool in self.tools_schema_dict.get("mcp_tools", []):
            function = tool.get("function", {})
            tool_name = function.get("name", "")
            server_name = self.get_mcp_server(tool_name)
            if not should_expose_mcp_tool(tool_name, server_name):
                continue
            if allowed_mcp_servers and server_name not in allowed_mcp_servers and tool_name not in allowed_tool_names:
                continue
            visible_tools.append(tool)
        return visible_tools

    def get_heartbeat_tools(self) -> list[dict]:
        allowlist = (
            "get_background_status",
            "get_current_system_time",
            "get_sys_vitals",
        )
        return [
            tool
            for name in allowlist
            if (tool := self._tool_schema_by_name(name, sections=("background_tools", "common_tools", "memory_tools"))) is not None
        ]

    def get_scheduled_job_tools(self) -> list[dict]:
        allowlist = (
            "research_topic",
            "track_source_updates",
            "manage_scheduled_tasks",
            "get_current_system_time",
            "remember_knowledge",
            "analyze_workspace",
            "read_local_documents",
            "write_local_document",
            "rewrite_local_document",
            "compile_report",
        )
        return [
            tool
            for name in allowlist
            if (tool := self._tool_schema_by_name(name, sections=("chain_tools", "common_tools"))) is not None
        ]
