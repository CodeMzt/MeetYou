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
from tools.document_tools import DocumentTools
from tools.office_tools import OfficeTools
from tools.scenario_tools import ScenarioTools
from tools.study_tools import StudyTools
from tools.web_search import WebSearchTools

logger = logging.getLogger("meetyou.tools_manager")

_DEFAULT_MCP_TIMEOUT_SECONDS = 10.0
_BROWSER_MCP_TIMEOUT_SECONDS = 30.0
_HIDDEN_MCP_PREFIXES = ("browser_", "tavily-")
_HIDDEN_MCP_SERVER_KEYWORDS = ("notion",)
_ACTION_RISK_RANK = {
    "read": 0,
    "local_write": 1,
    "external_write": 2,
    "destructive": 3,
}


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

    def __init__(self, memory, context_manager, mcp_manager, system_tools_module, mode_manager=None):
        self.tools_schema_dict: dict[str, Any] = {}
        self._mcp_manager = mcp_manager
        self._mode_manager = mode_manager
        self._agent_memory_tools = AgentMemoryTools(memory)
        self._web_search_tools = WebSearchTools(mcp_manager)
        self._document_tools = DocumentTools(mode_manager) if mode_manager is not None else None
        self._scenario_tools = ScenarioTools(
            memory,
            context_manager,
            mcp_manager,
            mode_manager=mode_manager,
        )
        self._office_tools = OfficeTools(mode_manager, self._document_tools) if self._document_tools else None
        self._study_tools = StudyTools(self._document_tools) if self._document_tools else None

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
            "get_background_status": getattr(system_tools_module, "get_background_status", None),
            "search_web": self._web_search_tools.search_web,
            "read_web_page": self._web_search_tools.read_web_page,
            "research_topic": self._scenario_tools.research_topic,
            "inspect_page": self._scenario_tools.inspect_page,
            "track_source_updates": self._scenario_tools.track_source_updates,
            "search_knowledge": self._scenario_tools.search_knowledge,
            "manage_tasks": self._scenario_tools.manage_tasks,
        }
        self.supported_funcs = {name: func for name, func in self.supported_funcs.items() if func is not None}
        if self._document_tools is not None:
            self.supported_funcs.update(
                {
                    "analyze_workspace": self._document_tools.analyze_workspace,
                    "read_local_documents": self._document_tools.read_local_documents,
                    "write_local_document": self._document_tools.write_local_document,
                    "rewrite_local_document": self._document_tools.rewrite_local_document,
                    "compile_report": self._document_tools.compile_report,
                }
            )
        if self._office_tools is not None:
            self.supported_funcs.update(
                {
                    "manage_schedule": self._office_tools.manage_schedule,
                    "draft_message": self._office_tools.draft_message,
                    "meeting_brief": self._office_tools.meeting_brief,
                    "sync_notes": self._office_tools.sync_notes,
                }
            )
        if self._study_tools is not None:
            self.supported_funcs.update(
                {
                    "build_study_plan": self._study_tools.build_study_plan,
                    "extract_learning_points": self._study_tools.extract_learning_points,
                    "quiz_me": self._study_tools.quiz_me,
                    "generate_flashcards": self._study_tools.generate_flashcards,
                    "track_mastery": self._study_tools.track_mastery,
                }
            )
        self._tool_action_risks: dict[str, str] = {
            "exec_sys_cmd": "destructive",
            "get_current_system_time": "read",
            "get_sys_vitals": "read",
            "get_background_status": "read",
            "remember_knowledge": "local_write",
            "research_topic": "read",
            "inspect_page": "read",
            "track_source_updates": "read",
            "search_knowledge": "read",
            "manage_tasks": "local_write",
            "analyze_workspace": "read",
            "read_local_documents": "read",
            "write_local_document": "local_write",
            "rewrite_local_document": "local_write",
            "compile_report": "read",
            "manage_schedule": "external_write",
            "draft_message": "external_write",
            "meeting_brief": "local_write",
            "sync_notes": "local_write",
            "build_study_plan": "read",
            "extract_learning_points": "read",
            "quiz_me": "read",
            "generate_flashcards": "read",
            "track_mastery": "local_write",
        }

    async def init_tools(self, tools_schema_path: str, mcp_servers: dict):
        """Load built-in tool schema and initialize MCP servers."""
        with open(tools_schema_path, "r", encoding="utf-8") as handle:
            self.tools_schema_dict = json.load(handle)

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

    def _iter_llm_visible_tools(self) -> list[dict]:
        tools: list[dict] = []
        for key in ("common_tools", "chain_tools"):
            tools.extend(self.tools_schema_dict.get(key, []))
        return tools

    def _tool_schema_by_name(self, tool_name: str, sections: tuple[str, ...] | None = None) -> dict | None:
        keys = sections or ("common_tools", "chain_tools", "memory_tools", "background_tools")
        for key in keys:
            for tool in self.tools_schema_dict.get(key, []):
                function = tool.get("function", {})
                if function.get("name") == tool_name:
                    return tool
        return None

    def get_all_tools(self, route_context: dict[str, Any] | None = None) -> list[dict]:
        """Return the LLM-visible tool schemas."""
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
        for tool in self._iter_llm_visible_tools():
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
            server_name = self._mcp_manager.tool_map.get(tool_name, "")
            if not _should_expose_mcp_tool(tool_name, server_name):
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
            "search_memory",
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
            "manage_tasks",
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

    def _is_tool_allowed(self, tool_name: str, route_context: dict[str, Any] | None = None) -> bool:
        route_context = route_context or {}
        allowed_tool_names = {
            str(item).strip()
            for item in route_context.get("tool_bundle", [])
            if str(item).strip()
        }
        if allowed_tool_names and tool_name in allowed_tool_names:
            return True
        if allowed_tool_names and tool_name not in allowed_tool_names:
            return False

        allowed_mcp_servers = {
            str(item).strip()
            for item in route_context.get("mcp_servers", [])
            if str(item).strip()
        }
        if allowed_mcp_servers and tool_name in self._mcp_manager.tool_map:
            return self._mcp_manager.tool_map.get(tool_name, "") in allowed_mcp_servers
        return True

    def get_tool_action_risk(self, tool_name: str) -> str:
        if tool_name in self._tool_action_risks:
            return self._tool_action_risks[tool_name]
        lowered = str(tool_name or "").lower()
        if any(token in lowered for token in ("delete", "remove", "erase")):
            return "destructive"
        if any(token in lowered for token in ("write", "create", "append", "move", "rename")):
            return "local_write"
        return "read"

    def get_action_risk_for_tools(self, tool_names: list[str] | tuple[str, ...]) -> str:
        highest = "read"
        for tool_name in tool_names:
            risk = self.get_tool_action_risk(tool_name)
            if _ACTION_RISK_RANK.get(risk, 0) > _ACTION_RISK_RANK.get(highest, 0):
                highest = risk
        return highest

    async def call_tool(
        self,
        tool_name: str,
        tool_args: dict,
        session_id: str = "",
        source=None,
        tool_activity_callback=None,
        route_context: dict[str, Any] | None = None,
    ) -> str:
        """Dispatch a tool call to either a built-in tool or an MCP server."""
        if not self._is_tool_allowed(tool_name, route_context=route_context):
            return f"Error: tool not allowed in the current route: {tool_name}"

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
                if "route_context" in signature.parameters:
                    call_kwargs["route_context"] = route_context or {}
                return await func(**call_kwargs)
            except TypeError as exc:
                return f"Error: argument mismatch for {tool_name}: {exc}"
            except Exception as exc:
                logger.error("Built-in tool %s failed: %s", tool_name, exc)
                return f"Error: {tool_name} failed: {exc}"

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
                return f"Error: MCP tool {tool_name} returned empty content"
            except asyncio.TimeoutError:
                return f"Error: MCP tool {tool_name} timed out"
            except Exception as exc:
                logger.error("MCP tool %s failed: %s", tool_name, exc)
                return f"Error: MCP tool {tool_name} failed: {exc}"

        return f"Error: tool not found: {tool_name}"
