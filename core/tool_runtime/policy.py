from __future__ import annotations

from typing import Any

_DEFAULT_MCP_TIMEOUT_SECONDS = 10.0
_BROWSER_MCP_TIMEOUT_SECONDS = 30.0
_HIDDEN_MCP_PREFIXES = ("browser_", "tavily-")
_HIDDEN_MCP_SERVER_KEYWORDS = ("notion",)


def is_browser_tool(tool_name: str) -> bool:
    return str(tool_name or "").startswith("browser_")


def get_mcp_timeout_seconds(tool_name: str) -> float:
    if is_browser_tool(tool_name):
        return _BROWSER_MCP_TIMEOUT_SECONDS
    return _DEFAULT_MCP_TIMEOUT_SECONDS


def should_expose_mcp_tool(tool_name: str, server_name: str = "") -> bool:
    if any(str(tool_name or "").startswith(prefix) for prefix in _HIDDEN_MCP_PREFIXES):
        return False
    lowered_server = str(server_name or "").lower()
    if any(keyword in lowered_server for keyword in _HIDDEN_MCP_SERVER_KEYWORDS):
        return False
    return True


class ToolPermissionPolicy:
    def __init__(self, mcp_manager):
        self._mcp_manager = mcp_manager

    @staticmethod
    def _normalized_set(values: Any) -> set[str]:
        if not isinstance(values, (list, tuple, set)):
            return set()
        return {
            str(item).strip()
            for item in values
            if str(item).strip()
        }

    def is_tool_allowed(self, tool_name: str, route_context: dict[str, Any] | None = None) -> bool:
        route_context = route_context or {}
        allowed_tool_names = self._normalized_set(route_context.get("tool_bundle", []))
        if allowed_tool_names and tool_name in allowed_tool_names:
            return True
        if allowed_tool_names and tool_name not in allowed_tool_names:
            return False

        allowed_mcp_servers = self._normalized_set(route_context.get("mcp_servers", []))
        if allowed_mcp_servers and tool_name in getattr(self._mcp_manager, "tool_map", {}):
            return str(self._mcp_manager.tool_map.get(tool_name, "")).strip() in allowed_mcp_servers
        return True
