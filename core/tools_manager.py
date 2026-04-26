from __future__ import annotations

import hashlib
from pathlib import Path, PureWindowsPath
import re
from typing import Any
from urllib.parse import urlparse, urlunparse

from core.tool_runtime import (
    ToolCallResult,
    ToolAuthorizationGateway,
    ToolExecutor,
    ToolPermissionPolicy,
    ToolRegistry,
    ToolRiskClassifier,
    get_mcp_timeout_seconds,
    should_expose_mcp_tool,
)
from tools.attachment_tools import AttachmentTools
from tools.memory_tools import MemoryTools
from tools.danxi_tools import get_shared_danxi_tools
from tools.document_tools import DocumentTools
from tools.endpoint_tools import EndpointTools
from tools.lightweight_tools import LightweightTools
from tools.office_tools import OfficeTools
from tools.procedure_tools import ProcedureTools
from tools.scenario_tools import ScenarioTools
from tools.study_tools import StudyTools
from tools.web_search import WebSearchTools
from tools.workspace_tools import WorkspaceTools

_get_mcp_timeout_seconds = get_mcp_timeout_seconds
_should_expose_mcp_tool = should_expose_mcp_tool
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")

_ORDER_REQUIRED_TOOLS = {
    "ask_human",
    "switch_assistant_mode",
    "switch_workspace",
    "save_memory",
    "remember_knowledge",
    "manage_memories",
    "manage_tasks",
    "manage_scheduled_tasks",
    "send_endpoint_message",
    "emit_short_reply",
    "emit_temporary_reply",
    "restart_core",
    "danxi_login",
    "danxi_logout",
    "danxi_set_webvpn_cookie",
    "danxi_clear_webvpn_cookie",
    "danxi_create_post",
    "danxi_reply_post",
    "danxi_edit_reply",
    "danxi_delete_reply",
    "danxi_delete_post",
    "danxi_manage_favorite",
    "danxi_manage_subscription",
    "danxi_mark_message_read",
}

_CLIENT_LOCAL_FILE_TOOLS = {
    "analyze_workspace",
    "read_local_documents",
    "write_local_document",
    "rewrite_local_document",
}
_CLIENT_DIRECTED_LOCAL_TOOLS = {"exec_sys_cmd", *_CLIENT_LOCAL_FILE_TOOLS}

_WEB_READ_TOOLS = {"search_web", "read_web_page"}
_WEB_MCP_READ_PREFIXES = ("tavily",)


def _stable_short_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _normalize_url_key(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.lower()
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            "",
            parsed.query,
            "",
        )
    )


class ToolsManager:
    def __init__(self, memory, context_manager, mcp_manager, system_tools_module, mode_manager=None, task_manager=None, config=None):
        self._mcp_manager = mcp_manager
        self._mode_manager = mode_manager
        self._attachment_tools = AttachmentTools()
        self._memory_tools = MemoryTools(memory)
        self._web_search_tools = WebSearchTools(mcp_manager, config=config)
        self._danxi_tools = get_shared_danxi_tools()
        self._document_tools = (
            DocumentTools(mode_manager, allow_local_fallback=False) if mode_manager is not None else None
        )
        self._endpoint_tools = EndpointTools()
        self._lightweight_tools = LightweightTools()
        self._procedure_tools = ProcedureTools()
        self._workspace_tools = WorkspaceTools()
        self._scenario_tools = ScenarioTools(
            memory,
            context_manager,
            mcp_manager,
            mode_manager=mode_manager,
            task_manager=task_manager,
        )
        self._office_tools = OfficeTools(mode_manager, self._document_tools) if self._document_tools else None
        self._study_tools = StudyTools(self._document_tools) if self._document_tools else None

        supported_funcs = {
            "exec_sys_cmd": system_tools_module.exec_sys_cmd,
            "ask_human": getattr(system_tools_module, "ask_human", None),
            "save_memory": memory.save_memory,
            "remember_knowledge": self._memory_tools.remember_knowledge,
            "search_memory": self._memory_tools.search_memory,
            "manage_memories": self._memory_tools.manage_memories,
            "recall_memory": memory.recall_memory,
            "recall_memory_structured": memory.recall_memory_structured,
            "get_current_system_time": system_tools_module.get_current_system_time,
            "update_context": context_manager.update_context,
            "get_sys_vitals": system_tools_module.get_sys_vitals,
            "get_background_status": getattr(system_tools_module, "get_background_status", None),
            "manage_heartbeat_settings": getattr(system_tools_module, "manage_heartbeat_settings", None),
            "restart_core": getattr(system_tools_module, "restart_core", None),
            "emit_short_reply": getattr(system_tools_module, "emit_short_reply", None),
            "emit_temporary_reply": getattr(system_tools_module, "emit_temporary_reply", None),
            "list_active_clients": self._endpoint_tools.list_active_clients,
            "list_client_tool_targets": self._endpoint_tools.list_client_tool_targets,
            "send_endpoint_message": self._endpoint_tools.send_endpoint_message,
            "search_web": self._web_search_tools.search_web,
            "read_web_page": self._web_search_tools.read_web_page,
            "research_topic": self._scenario_tools.research_topic,
            "inspect_page": self._scenario_tools.inspect_page,
            "track_source_updates": self._scenario_tools.track_source_updates,
            "search_knowledge": self._scenario_tools.search_knowledge,
            "manage_tasks": self._scenario_tools.manage_tasks,
            "manage_scheduled_tasks": self._scenario_tools.manage_scheduled_tasks,
            "list_skills": self._scenario_tools.list_skills,
            "load_skill": self._scenario_tools.load_skill,
            "create_skill": self._scenario_tools.create_skill,
            "list_attachments": self._attachment_tools.list_attachments,
            "read_attachment": self._attachment_tools.read_attachment,
            "delete_attachment": self._attachment_tools.delete_attachment,
            "manage_procedures": self._procedure_tools.manage_procedures,
            "list_workspaces": self._workspace_tools.list_workspaces,
            "switch_workspace": self._workspace_tools.switch_workspace,
            "summarize_text": self._lightweight_tools.summarize_text,
            "organize_notes": self._lightweight_tools.organize_notes,
            "extract_action_items": self._lightweight_tools.extract_action_items,
            "danxi_login": self._danxi_tools.danxi_login,
            "danxi_logout": self._danxi_tools.danxi_logout,
            "danxi_get_session_status": self._danxi_tools.danxi_get_session_status,
            "danxi_set_webvpn_cookie": self._danxi_tools.danxi_set_webvpn_cookie,
            "danxi_clear_webvpn_cookie": self._danxi_tools.danxi_clear_webvpn_cookie,
            "danxi_list_divisions": self._danxi_tools.danxi_list_divisions,
            "danxi_list_tags": self._danxi_tools.danxi_list_tags,
            "danxi_list_posts": self._danxi_tools.danxi_list_posts,
            "danxi_get_post": self._danxi_tools.danxi_get_post,
            "danxi_list_floors": self._danxi_tools.danxi_list_floors,
            "danxi_search_posts": self._danxi_tools.danxi_search_posts,
            "danxi_create_post": self._danxi_tools.danxi_create_post,
            "danxi_reply_post": self._danxi_tools.danxi_reply_post,
            "danxi_edit_reply": self._danxi_tools.danxi_edit_reply,
            "danxi_delete_reply": self._danxi_tools.danxi_delete_reply,
            "danxi_delete_post": self._danxi_tools.danxi_delete_post,
            "danxi_manage_favorite": self._danxi_tools.danxi_manage_favorite,
            "danxi_manage_subscription": self._danxi_tools.danxi_manage_subscription,
            "danxi_list_messages": self._danxi_tools.danxi_list_messages,
            "danxi_mark_message_read": self._danxi_tools.danxi_mark_message_read,
        }
        supported_funcs = {name: func for name, func in supported_funcs.items() if func is not None}
        if self._document_tools is not None:
            supported_funcs.update(
                {
                    "analyze_workspace": self._document_tools.analyze_workspace,
                    "read_local_documents": self._document_tools.read_local_documents,
                    "write_local_document": self._document_tools.write_local_document,
                    "rewrite_local_document": self._document_tools.rewrite_local_document,
                    "compile_report": self._document_tools.compile_report,
                }
            )
        if self._office_tools is not None:
            supported_funcs.update(
                {
                    "manage_schedule": self._office_tools.manage_schedule,
                    "draft_message": self._office_tools.draft_message,
                    "meeting_brief": self._office_tools.meeting_brief,
                    "sync_notes": self._office_tools.sync_notes,
                }
            )
        if self._study_tools is not None:
            supported_funcs.update(
                {
                    "build_study_plan": self._study_tools.build_study_plan,
                    "extract_learning_points": self._study_tools.extract_learning_points,
                    "quiz_me": self._study_tools.quiz_me,
                    "generate_flashcards": self._study_tools.generate_flashcards,
                    "track_mastery": self._study_tools.track_mastery,
                }
            )

        self._registry = ToolRegistry(mcp_manager, supported_funcs=supported_funcs)
        self._permission_policy = ToolPermissionPolicy(mcp_manager)
        self._risk_classifier = ToolRiskClassifier()
        self._authorization_gateway = ToolAuthorizationGateway(
            self._permission_policy,
            self._risk_classifier,
            mode_manager=mode_manager,
            command_safety_checker=getattr(system_tools_module, "assess_command_safety", None),
        )
        self._executor = ToolExecutor(
            self._registry,
            self._permission_policy,
            self._risk_classifier,
            mcp_manager,
            authorization_gateway=self._authorization_gateway,
        )
        self._client_tool_dispatcher_available = False

    def set_client_tool_dispatcher(self, dispatcher) -> None:
        if self._document_tools is not None:
            self._document_tools.set_client_tool_dispatcher(dispatcher)
        self._client_tool_dispatcher_available = dispatcher is not None
        self._authorization_gateway.set_local_capability_dispatcher_available(dispatcher is not None)

    def set_capability_dispatcher(self, dispatcher) -> None:
        self.set_client_tool_dispatcher(dispatcher)

    def set_core_domain(self, core_domain) -> None:
        self._attachment_tools.set_core_domain(core_domain)
        self._procedure_tools.set_core_domain(core_domain)
        self._workspace_tools.set_core_domain(core_domain)
        self._endpoint_tools.set_core_domain(core_domain)

    def set_runtime_bridge(self, *, session_manager=None, gateway_getter=None) -> None:
        self._workspace_tools.set_runtime(session_manager=session_manager, gateway_getter=gateway_getter)
        self._endpoint_tools.set_runtime(gateway_getter=gateway_getter)

    def set_state_backends(self, *, office_backend=None, study_backend=None, danxi_backend=None) -> None:
        if self._danxi_tools is not None and danxi_backend is not None:
            self._danxi_tools.set_state_backend(danxi_backend)
        if self._office_tools is not None and office_backend is not None:
            self._office_tools.set_state_backend(office_backend)
        if self._study_tools is not None and study_backend is not None:
            self._study_tools.set_state_backend(study_backend)

    def set_execution_observer(self, observer) -> None:
        self._executor.set_execution_observer(observer)

    @property
    def tools_schema_dict(self) -> dict[str, Any]:
        return self._registry.tools_schema_dict

    @tools_schema_dict.setter
    def tools_schema_dict(self, value: dict[str, Any]) -> None:
        self._registry.tools_schema_dict = dict(value or {})

    @property
    def supported_funcs(self) -> dict[str, Any]:
        return self._registry.supported_funcs

    def set_mode_manager(self, mode_manager) -> None:
        self._mode_manager = mode_manager
        self._authorization_gateway._mode_manager = mode_manager
        if self._document_tools is not None:
            self._document_tools._mode_manager = mode_manager
        if self._scenario_tools is not None:
            self._scenario_tools._mode_manager = mode_manager
            authoritative_sources = getattr(self._scenario_tools, "_authoritative_sources", None)
            if authoritative_sources is not None:
                authoritative_sources._mode_manager = mode_manager
        if self._office_tools is not None:
            self._office_tools._mode_manager = mode_manager

    async def init_tools(self, tools_schema_path: str, mcp_servers: dict[str, Any]) -> None:
        await self._registry.init_tools(tools_schema_path, mcp_servers)

    def get_all_tools(self, route_context: dict[str, Any] | None = None) -> list[dict]:
        visible_tools = self._registry.get_all_tools(
            route_context,
            should_expose_mcp_tool=should_expose_mcp_tool,
        )
        if not route_context:
            return visible_tools
        filtered_tools: list[dict] = []
        for tool in visible_tools:
            function = tool.get("function", {})
            tool_name = str(function.get("name") or "").strip()
            if not tool_name:
                continue
            if self._authorization_gateway.should_expose_tool(tool_name, route_context=route_context):
                filtered_tools.append(tool)
        return filtered_tools

    def get_heartbeat_tools(self) -> list[dict]:
        return self._registry.get_heartbeat_tools()

    def get_scheduled_job_tools(self) -> list[dict]:
        return self._registry.get_scheduled_job_tools()

    def get_tool_action_risk(self, tool_name: str) -> str:
        return self._risk_classifier.get_tool_action_risk(tool_name)

    def get_action_risk_for_tools(self, tool_names: list[str] | tuple[str, ...]) -> str:
        return self._risk_classifier.get_action_risk_for_tools(tool_names)

    def get_route_debug_snapshot(self, route_context: dict[str, Any] | None = None) -> dict[str, Any]:
        route_context = dict(route_context or {})
        visible_tools = self.get_all_tools(route_context=route_context)
        visible_tool_names = [
            str(tool.get("function", {}).get("name") or "").strip()
            for tool in visible_tools
            if str(tool.get("function", {}).get("name") or "").strip()
        ]
        candidate_tool_names = []
        for tool_name in route_context.get("tool_bundle", []):
            normalized_name = str(tool_name or "").strip()
            if normalized_name and normalized_name not in candidate_tool_names:
                candidate_tool_names.append(normalized_name)
        decisions = [
            self._authorization_gateway.decide(tool_name, {}, route_context=route_context).to_dict()
            for tool_name in candidate_tool_names
        ]
        return {
            "visible_tools": visible_tool_names,
            "candidate_tools": candidate_tool_names,
            "authorization_preview": decisions,
            "execution_boundary": self.get_tool_execution_boundary_snapshot(),
            "mcp_server_diagnostics": list(
                route_context.get("capability_set", {}).get("mcp_diagnostics")
                or route_context.get("mcp_diagnostics")
                or getattr(self._mcp_manager, "get_server_diagnostics", lambda: [])()
            ),
            "degradation_notes": list(
                route_context.get("capability_set", {}).get("degradation_notes")
                or route_context.get("degradation_notes")
                or []
            ),
        }

    @staticmethod
    def _normalize_path(path_value: str) -> str:
        path_text = str(path_value or "").strip()
        if not path_text:
            return ""
        if _WINDOWS_ABSOLUTE_PATH_RE.match(path_text):
            return str(PureWindowsPath(path_text))
        try:
            return str(Path(path_text).expanduser().resolve())
        except Exception:
            return path_text

    def get_tool_parallel_metadata(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
        *,
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        normalized_tool_name = str(tool_name or "").strip()
        normalized_tool_args = dict(tool_args or {})
        capability = self._executor.get_tool_capability_metadata(normalized_tool_name)
        action_risk = str(capability.get("action_risk") or self.get_tool_action_risk(normalized_tool_name))
        schema_metadata = capability.get("schema_metadata")
        schema_metadata = dict(schema_metadata) if isinstance(schema_metadata, dict) else {}

        mutates_state = action_risk in {"local_write", "external_write", "destructive"}
        requires_order = normalized_tool_name in _ORDER_REQUIRED_TOOLS
        if normalized_tool_name == "exec_sys_cmd":
            requires_order = True

        resource_key = str(schema_metadata.get("resource_key") or "").strip()
        if not resource_key and normalized_tool_name == "search_web":
            query = str(normalized_tool_args.get("query") or "").strip().lower()
            quality = str(normalized_tool_args.get("quality") or "adaptive").strip().lower()
            max_results = str(normalized_tool_args.get("max_results") or "")
            resource_key = f"web-search:{_stable_short_hash(f'{query}|{quality}|{max_results}')}"
        if not resource_key and normalized_tool_name == "read_web_page":
            url = _normalize_url_key(str(normalized_tool_args.get("url") or ""))
            resource_key = f"web-page:{_stable_short_hash(url)}" if url else "web-page:unknown_url"
        if not resource_key and normalized_tool_name.startswith(_WEB_MCP_READ_PREFIXES):
            serialized = repr(sorted(normalized_tool_args.items()))
            resource_key = f"mcp-web:{normalized_tool_name}:{_stable_short_hash(serialized)}"
        if not resource_key and normalized_tool_name in _CLIENT_LOCAL_FILE_TOOLS:
            path_candidate = normalized_tool_args.get("path") or normalized_tool_args.get("workspace_path")
            normalized_path = self._normalize_path(str(path_candidate or ""))
            if normalized_path:
                resource_key = f"path:{normalized_path}"
            else:
                resource_key = f"{normalized_tool_name}:unknown_path"
        if not resource_key:
            resource_key = f"tool:{normalized_tool_name}"

        safe_parallel_default = action_risk == "read" and not requires_order
        safe_parallel = bool(schema_metadata.get("safe_parallel", safe_parallel_default))
        if normalized_tool_name in _WEB_READ_TOOLS or normalized_tool_name.startswith(_WEB_MCP_READ_PREFIXES):
            safe_parallel = action_risk == "read" and not requires_order
        if requires_order or action_risk in {"local_write", "external_write", "destructive"}:
            safe_parallel = False

        max_concurrency = schema_metadata.get("max_concurrency", 1 if not safe_parallel else 3)
        if normalized_tool_name in _WEB_READ_TOOLS or normalized_tool_name.startswith(_WEB_MCP_READ_PREFIXES):
            max_concurrency = schema_metadata.get("max_concurrency", 3)
        try:
            max_concurrency_int = max(1, int(max_concurrency))
        except (TypeError, ValueError):
            max_concurrency_int = 1 if not safe_parallel else 3

        parallel_group = str(schema_metadata.get("parallel_group") or "").strip() or str(
            schema_metadata.get("resource_key") or ""
        ).strip()
        if not parallel_group:
            parallel_group = action_risk
        if normalized_tool_name in _WEB_READ_TOOLS or normalized_tool_name.startswith(_WEB_MCP_READ_PREFIXES):
            parallel_group = str(schema_metadata.get("parallel_group") or "web_io")

        return {
            "tool_name": normalized_tool_name,
            "source": str(capability.get("source") or "unknown"),
            "action_risk": action_risk,
            "safe_parallel": safe_parallel,
            "parallel_group": parallel_group,
            "resource_key": resource_key,
            "mutates_state": mutates_state,
            "requires_order": requires_order,
            "max_concurrency": max_concurrency_int,
        }

    def get_tool_execution_boundary_snapshot(self) -> list[dict[str, Any]]:
        tool_names = set(self._registry.supported_funcs.keys())
        tool_names.update(getattr(self._mcp_manager, "tool_map", {}).keys())
        snapshot: list[dict[str, Any]] = []
        for tool_name in sorted(name for name in tool_names if str(name or "").strip()):
            normalized = str(tool_name).strip()
            is_builtin = self._registry.has_builtin(normalized)
            if is_builtin:
                source_type = "builtin"
                if normalized in _CLIENT_DIRECTED_LOCAL_TOOLS:
                    executor_owner = "client_tool_dispatch" if self._client_tool_dispatcher_available else "client_tool_required"
                else:
                    executor_owner = "core"
            elif self._registry.has_mcp(normalized):
                source_type = "mcp"
                executor_owner = "core_mcp"
            else:
                source_type = "unknown"
                executor_owner = "unknown"

            risk = self._risk_classifier.get_tool_action_risk(normalized)
            try:
                parallel_safe = bool(self.get_tool_parallel_metadata(normalized, {}).get("safe_parallel", False))
            except Exception:
                parallel_safe = risk == "read"
            snapshot.append(
                {
                    "tool_name": normalized,
                    "source_type": source_type,
                    "executor_owner": executor_owner,
                    "risk": risk,
                    "parallel_safe": parallel_safe,
                }
            )
        return snapshot

    async def call_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None,
        session_id: str = "",
        source=None,
        tool_activity_callback=None,
        route_context: dict[str, Any] | None = None,
    ) -> ToolCallResult:
        return await self._executor.execute(
            tool_name,
            tool_args,
            session_id=session_id,
            source=source,
            tool_activity_callback=tool_activity_callback,
            route_context=route_context,
        )
