"""
Tool manager.

Responsible for:
1. loading tool schema from JSON and MCP servers
2. registering built-in tools
3. dispatching built-in and MCP tool calls
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any

from tools.agent_memory import AgentMemoryTools
from tools.scenario_tools import ScenarioTools
from tools.web_search import WebSearchTools

logger = logging.getLogger("meetyou.tools_manager")

_DEFAULT_MCP_TIMEOUT_SECONDS = 10.0
_BROWSER_MCP_TIMEOUT_SECONDS = 30.0
_HIDDEN_MCP_PREFIXES = ("browser_", "tavily-")
_HIDDEN_MCP_SERVER_KEYWORDS = ("notion",)


def _is_browser_tool(tool_name: str) -> bool:
    return tool_name.startswith("browser_")


def _get_mcp_timeout_seconds(tool_name: str) -> float:
    if _is_browser_tool(tool_name):
        return _BROWSER_MCP_TIMEOUT_SECONDS
    return _DEFAULT_MCP_TIMEOUT_SECONDS


def _should_expose_mcp_tool(tool_name: str, server_name: str = "") -> bool:
    if any(tool_name.startswith(prefix) for prefix in _HIDDEN_MCP_PREFIXES):
        return False
    lowered_server = str(server_name or "").lower()
    if any(keyword in lowered_server for keyword in _HIDDEN_MCP_SERVER_KEYWORDS):
        return False
    return True


class ToolsManager:
    """Central dispatcher for built-in tools and MCP tools."""

    def __init__(self, memory, context_manager, mcp_manager, system_tools_module):
        self.tools_schema_dict: dict[str, Any] = {}
        self._mcp_manager = mcp_manager
        self._agent_memory_tools = AgentMemoryTools(memory)
        self._web_search_tools = WebSearchTools(mcp_manager)
        self._scenario_tools = ScenarioTools(memory, context_manager, mcp_manager)

        self.supported_funcs: dict[str, Any] = {
            "exec_sys_cmd": system_tools_module.exec_sys_cmd,
            "save_memory": memory.save_memory,
            "remember_knowledge": self._agent_memory_tools.remember_knowledge,
            "search_memory": self._agent_memory_tools.search_memory,
            "recall_memory": memory.recall_memory,
            "recall_memory_structured": memory.recall_memory_structured,
            "get_current_system_time": system_tools_module.get_current_system_time,
            "update_context": context_manager.update_context,
            "get_sys_vitals": system_tools_module.get_sys_vitals,
            "search_web": self._web_search_tools.search_web,
            "read_web_page": self._web_search_tools.read_web_page,
            "research_topic": self._scenario_tools.research_topic,
            "inspect_page": self._scenario_tools.inspect_page,
            "search_knowledge": self._scenario_tools.search_knowledge,
            "manage_tasks": self._scenario_tools.manage_tasks,
        }

    async def init_tools(self, tools_schema_path: str, mcp_servers: dict):
        """Load built-in tool schema and initialize MCP servers."""
        with open(tools_schema_path, "r", encoding="utf-8") as f:
            self.tools_schema_dict = json.load(f)

        await self._mcp_manager.init_mcp_servers(mcp_servers)
        self.tools_schema_dict["mcp_tools"] = []
        for server_name in self._mcp_manager.mcp_servers_list:
            self.tools_schema_dict["mcp_tools"].extend(
                self._mcp_manager.mcp_tools.get(server_name, [])
            )

        logger.info(
            "Tools initialized: built-in=%s, mcp=%s",
            len(self.supported_funcs),
            len(self.tools_schema_dict.get("mcp_tools", [])),
        )

    def get_all_tools(self) -> list[dict]:
        """Return the LLM-visible tool schemas."""
        all_tools: list[dict] = []
        for key in ("common_tools", "chain_tools"):
            all_tools.extend(self.tools_schema_dict.get(key, []))

        for tool in self.tools_schema_dict.get("mcp_tools", []):
            function = tool.get("function", {})
            tool_name = function.get("name", "")
            server_name = self._mcp_manager.tool_map.get(tool_name, "")
            if _should_expose_mcp_tool(tool_name, server_name):
                all_tools.append(tool)
        return all_tools

    def get_heartbeat_tools(self) -> list[dict]:
        """Return the smaller tool subset available to the heartbeat."""
        tools: list[dict] = []
        for key in ("common_tools", "memory_tools"):
            tools.extend(self.tools_schema_dict.get(key, []))
        return tools

    async def call_tool(
        self,
        tool_name: str,
        tool_args: dict,
        session_id: str = "",
        source=None,
        tool_activity_callback=None,
    ) -> str:
        """Dispatch a tool call to either a built-in tool or an MCP server."""
        if tool_name in self.supported_funcs:
            try:
                call_kwargs = dict(tool_args)
                func = self.supported_funcs[tool_name]
                signature = inspect.signature(func)
                if "session_id" in signature.parameters:
                    call_kwargs["session_id"] = session_id
                if "source" in signature.parameters:
                    call_kwargs["source"] = source
                if "activity_callback" in signature.parameters:
                    call_kwargs["activity_callback"] = tool_activity_callback
                return await func(**call_kwargs)
            except TypeError as exc:
                return f"Error: 参数不匹配 {tool_name}: {exc}"
            except Exception as exc:
                logger.error("Built-in tool %s failed: %s", tool_name, exc)
                return f"Error: {tool_name} 执行失败: {exc}"

        if tool_name in self._mcp_manager.tool_map:
            try:
                result = await asyncio.wait_for(
                    self._mcp_manager.call_mcp_tool(tool_name, tool_args),
                    timeout=_get_mcp_timeout_seconds(tool_name),
                )
                if result.content:
                    return "\n".join(
                        item.text
                        for item in result.content
                        if getattr(item, "type", "") == "text"
                    )
                return f"Error: MCP 工具 {tool_name} 返回空内容"
            except asyncio.TimeoutError:
                return f"Error: MCP 工具 {tool_name} 超时"
            except Exception as exc:
                logger.error("MCP tool %s failed: %s", tool_name, exc)
                return f"Error: MCP 工具 {tool_name} 失败: {exc}"

        return f"Error: 未找到工具 {tool_name}"
