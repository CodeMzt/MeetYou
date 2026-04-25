from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("meetyou.tools_manager")

_BUILTIN_FALLBACK_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_workspaces": {
        "type": "function",
        "function": {
            "name": "list_workspaces",
            "description": "List available workspaces and show which workspace is currently active.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_agents": {
                        "type": "boolean",
                        "description": "Include agents registered in each workspace.",
                        "default": False,
                    },
                    "include_clients": {
                        "type": "boolean",
                        "description": "Include clients registered in each workspace.",
                        "default": False,
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Optional session id for resolving the active workspace.",
                        "default": "",
                    },
                },
                "required": [],
            },
            "metadata": {
                "capability_ref": "workspace.list",
                "action_risk": "read",
            },
        },
    },
}


def _tool_name(tool: dict[str, Any] | None) -> str:
    if not isinstance(tool, dict):
        return ""
    function = tool.get("function")
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "").strip()


def _deduplicate_tools(
    tools: list[dict[str, Any]] | None,
    *,
    source_label: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    deduplicated: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    for tool in tools or []:
        name = _tool_name(tool)
        if not name:
            deduplicated.append(tool)
            continue
        if name in seen:
            duplicates.append(name)
            continue
        seen.add(name)
        deduplicated.append(tool)
    if duplicates:
        logger.warning(
            "Duplicate tool schemas ignored in %s: %s",
            source_label,
            ", ".join(sorted(set(duplicates))),
        )
    return deduplicated, duplicates


class ToolRegistry:
    def __init__(self, mcp_manager, *, supported_funcs: dict[str, Any] | None = None):
        self.tools_schema_dict: dict[str, Any] = {}
        self._mcp_manager = mcp_manager
        self.supported_funcs: dict[str, Any] = dict(supported_funcs or {})

    async def init_tools(self, tools_schema_path: str, mcp_servers: dict[str, Any]) -> None:
        with open(tools_schema_path, "r", encoding="utf-8") as handle:
            self.tools_schema_dict = json.load(handle)
        for key in ("common_tools", "chain_tools", "memory_tools", "background_tools", "web_tools"):
            tools, _ = _deduplicate_tools(
                self.tools_schema_dict.get(key, []),
                source_label=f"tools schema section [{key}]",
            )
            self.tools_schema_dict[key] = tools
        self._inject_builtin_fallback_tool_schemas()

        await self._mcp_manager.init_mcp_servers(mcp_servers)
        self.tools_schema_dict["mcp_tools"] = []
        seen_mcp_tool_names: set[str] = set()
        for server_name in getattr(self._mcp_manager, "mcp_servers_list", []):
            tools, _ = _deduplicate_tools(
                self._mcp_manager.mcp_tools.get(server_name, []),
                source_label=f"MCP server [{server_name}]",
            )
            for tool in tools:
                tool_name = _tool_name(tool)
                if tool_name and tool_name in seen_mcp_tool_names:
                    logger.warning(
                        "Duplicate MCP tool schema ignored across servers: %s (server=%s)",
                        tool_name,
                        server_name,
                    )
                    continue
                if tool_name:
                    seen_mcp_tool_names.add(tool_name)
                self.tools_schema_dict["mcp_tools"].append(tool)

        logger.info(
            "Tools initialized: built-in=%s, mcp=%s",
            len(self.supported_funcs),
            len(self.tools_schema_dict.get("mcp_tools", [])),
        )

    def _inject_builtin_fallback_tool_schemas(self) -> None:
        visible_sections = ("common_tools", "chain_tools", "memory_tools", "background_tools", "web_tools")
        known_names = {
            _tool_name(tool)
            for section in visible_sections
            for tool in self.tools_schema_dict.get(section, [])
            if _tool_name(tool)
        }
        common_tools = self.tools_schema_dict.setdefault("common_tools", [])
        for tool_name, schema in _BUILTIN_FALLBACK_TOOL_SCHEMAS.items():
            if tool_name not in self.supported_funcs or tool_name in known_names:
                continue
            common_tools.append(schema)
            known_names.add(tool_name)

    def has_builtin(self, tool_name: str) -> bool:
        return tool_name in self.supported_funcs

    def get_builtin(self, tool_name: str):
        return self.supported_funcs.get(tool_name)

    def has_mcp(self, tool_name: str) -> bool:
        return tool_name in getattr(self._mcp_manager, "tool_map", {})

    def get_mcp_server(self, tool_name: str) -> str:
        return str(getattr(self._mcp_manager, "tool_map", {}).get(tool_name, ""))

    def get_tool_capability_metadata(self, tool_name: str) -> dict[str, Any]:
        normalized_tool_name = str(tool_name or "").strip()
        metadata: dict[str, Any] = {
            "tool_name": normalized_tool_name,
            "source": "unknown",
            "schema_metadata": {},
        }
        if self.has_builtin(normalized_tool_name):
            metadata["source"] = "builtin"
        elif self.has_mcp(normalized_tool_name):
            metadata["source"] = "mcp"
            metadata["mcp_server"] = self.get_mcp_server(normalized_tool_name)

        schema = self._tool_schema_by_name(
            normalized_tool_name,
            sections=("common_tools", "chain_tools", "memory_tools", "background_tools", "web_tools", "mcp_tools"),
        )
        if isinstance(schema, dict):
            function_schema = schema.get("function", {})
            if isinstance(function_schema, dict):
                schema_metadata = function_schema.get("metadata")
                if isinstance(schema_metadata, dict):
                    metadata["schema_metadata"] = dict(schema_metadata)
        return metadata

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

        visible_tool_names = {
            str(tool.get("function", {}).get("name", "")).strip()
            for tool in visible_tools
            if str(tool.get("function", {}).get("name", "")).strip()
        }
        for tool in self.tools_schema_dict.get("mcp_tools", []):
            function = tool.get("function", {})
            tool_name = function.get("name", "")
            server_name = self.get_mcp_server(tool_name)
            if tool_name in visible_tool_names:
                continue
            if not should_expose_mcp_tool(tool_name, server_name):
                continue
            if allowed_mcp_servers and server_name not in allowed_mcp_servers and tool_name not in allowed_tool_names:
                continue
            visible_tools.append(tool)
            if tool_name:
                visible_tool_names.add(tool_name)
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
