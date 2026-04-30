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
    ToolErrorCategory,
    ToolPermissionPolicy,
    ToolRegistry,
    ToolRiskClassifier,
    ToolSourceType,
    get_mcp_timeout_seconds,
    normalize_tool_result,
    should_expose_mcp_tool,
)
from core.services.tool_router_service import ToolRouterError
from tools.attachment_tools import AttachmentTools
from tools.memory_tools import MemoryTools
from tools.danxi_tools import get_shared_danxi_tools
from tools.document_tools import DocumentTools
from tools.endpoint_tools import EndpointTools
from tools.lightweight_tools import LightweightTools
from tools.office_tools import OfficeTools
from tools.scheduler_tools import SchedulerTools
from tools.scenario_tools import ScenarioTools
from tools.study_tools import StudyTools
from tools.thread_tools import ThreadTools
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
    "manage_scheduled_jobs",
    "create_scheduled_workflow",
    "manage_scheduled_workflows",
    "create_scheduled_delivery",
    "manage_scheduled_deliveries",
    "send_endpoint_message",
    "send_delivery_message",
    "set_delivery_preference",
    "emit_progress_notice",
    "manage_threads",
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

_ENDPOINT_LOCAL_FILE_TOOLS = {
    "analyze_workspace",
    "read_local_documents",
    "write_local_document",
    "rewrite_local_document",
}
_ENDPOINT_REQUIRED_LOCAL_TOOLS = {"exec_sys_cmd", *_ENDPOINT_LOCAL_FILE_TOOLS}

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
        self._scheduler_tools = SchedulerTools()
        self._thread_tools = ThreadTools()
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
        self._core_domain = None

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
            "manage_model_reasoning": getattr(system_tools_module, "manage_model_reasoning", None),
            "manage_threads": self._thread_tools.manage_threads,
            "restart_core": getattr(system_tools_module, "restart_core", None),
            "emit_progress_notice": getattr(system_tools_module, "emit_progress_notice", None),
            "list_active_endpoints": self._endpoint_tools.list_active_endpoints,
            "list_endpoint_tool_targets": self._endpoint_tools.list_endpoint_tool_targets,
            "list_delivery_targets": self._endpoint_tools.list_delivery_targets,
            "set_delivery_preference": self._endpoint_tools.set_delivery_preference,
            "send_delivery_message": self._endpoint_tools.send_delivery_message,
            "send_endpoint_message": self._endpoint_tools.send_endpoint_message,
            "search_web": self._web_search_tools.search_web,
            "read_web_page": self._web_search_tools.read_web_page,
            "research_topic": self._scenario_tools.research_topic,
            "inspect_page": self._scenario_tools.inspect_page,
            "track_source_updates": self._scenario_tools.track_source_updates,
            "search_knowledge": self._scenario_tools.search_knowledge,
            "manage_tasks": self._scenario_tools.manage_tasks,
            "manage_scheduled_jobs": self._scheduler_tools.manage_scheduled_jobs,
            "create_scheduled_workflow": self._scheduler_tools.create_scheduled_workflow,
            "manage_scheduled_workflows": self._scheduler_tools.manage_scheduled_workflows,
            "create_scheduled_delivery": self._scheduler_tools.create_scheduled_delivery,
            "manage_scheduled_deliveries": self._scheduler_tools.manage_scheduled_deliveries,
            "list_skills": self._scenario_tools.list_skills,
            "load_skill": self._scenario_tools.load_skill,
            "create_skill": self._scenario_tools.create_skill,
            "manage_skill": self._scenario_tools.manage_skill,
            "list_attachments": self._attachment_tools.list_attachments,
            "read_attachment": self._attachment_tools.read_attachment,
            "delete_attachment": self._attachment_tools.delete_attachment,
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
        self._tool_router_available = False

    def set_tool_router(self, dispatcher) -> None:
        if self._document_tools is not None:
            self._document_tools.set_tool_router(dispatcher)
        self._register_core_tools_with_router(dispatcher)
        self._tool_router_available = dispatcher is not None
        self._authorization_gateway.set_local_capability_dispatcher_available(dispatcher is not None)

    def set_capability_dispatcher(self, dispatcher) -> None:
        self.set_tool_router(dispatcher)

    def _register_core_tools_with_router(self, dispatcher) -> None:
        register = getattr(dispatcher, "register_core_tool", None)
        if not callable(register):
            return

        for tool_name in sorted(self._registry.supported_funcs):
            normalized = str(tool_name or "").strip()
            if not normalized or normalized in _ENDPOINT_REQUIRED_LOCAL_TOOLS:
                continue
            register(normalized, self._build_tool_router_core_handler(normalized))

    def _build_tool_router_core_handler(self, tool_name: str):
        async def _handler(arguments: dict[str, Any]) -> Any:
            return await self.call_tool(tool_name, dict(arguments or {}))

        return _handler

    def set_core_domain(self, core_domain) -> None:
        self._core_domain = core_domain
        self._attachment_tools.set_core_domain(core_domain)
        self._scheduler_tools.set_core_domain(core_domain)
        self._thread_tools.set_core_domain(core_domain)
        self._workspace_tools.set_core_domain(core_domain)
        self._endpoint_tools.set_core_domain(core_domain)

    def set_scheduler_job_trigger(self, callback) -> None:
        self._scheduler_tools.set_trigger_job_callback(callback)

    def set_runtime_bridge(self, *, session_manager=None, gateway_getter=None) -> None:
        self._workspace_tools.set_runtime(session_manager=session_manager, gateway_getter=gateway_getter)
        self._thread_tools.set_runtime(session_manager=session_manager, gateway_getter=gateway_getter)
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
        existing_names = {
            str(tool.get("function", {}).get("name") or "").strip()
            for tool in filtered_tools
            if str(tool.get("function", {}).get("name") or "").strip()
        }
        filtered_tools.extend(self._contextual_endpoint_tool_schemas(route_context, existing_names=existing_names))
        return filtered_tools

    @staticmethod
    def _endpoint_action_risk(risk_level: str) -> str:
        normalized = str(risk_level or "read").strip().lower()
        if normalized in {"system", "destructive"}:
            return "destructive"
        if normalized in {"write", "local_write"}:
            return "local_write"
        if normalized in {"external_write", "network_write"}:
            return "external_write"
        return "read"

    @staticmethod
    def _endpoint_tool_slug(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip()).strip("_") or "tool"

    @staticmethod
    def _valid_parameters_schema(schema: Any) -> dict[str, Any]:
        if not isinstance(schema, dict) or not schema:
            return {"type": "object", "properties": {}, "additionalProperties": True}
        normalized = dict(schema)
        if normalized.get("type") != "object":
            return {"type": "object", "properties": {}, "additionalProperties": True}
        normalized.setdefault("properties", {})
        return normalized

    @staticmethod
    def _visibility_allows_auto_inject(capability) -> bool:
        meta = dict(getattr(capability, "meta", {}) or {})
        visibility = meta.get("visibility") if isinstance(meta.get("visibility"), dict) else {}
        if "auto_inject" in visibility:
            return bool(visibility.get("auto_inject"))
        if "auto_inject" in meta:
            return bool(meta.get("auto_inject"))
        return True

    @staticmethod
    def _route_workspace_id(route_context: dict[str, Any]) -> str:
        workspace = route_context.get("workspace") if isinstance(route_context.get("workspace"), dict) else {}
        return str(route_context.get("workspace_id") or workspace.get("workspace_id") or "").strip()

    @staticmethod
    def _route_endpoint_id(route_context: dict[str, Any]) -> str:
        endpoint = route_context.get("endpoint") if isinstance(route_context.get("endpoint"), dict) else {}
        return str(route_context.get("endpoint_id") or route_context.get("origin_endpoint_id") or endpoint.get("endpoint_id") or "").strip()

    def _endpoint_constraints_allow(self, capability, endpoint, route_context: dict[str, Any]) -> bool:
        constraints = dict(getattr(capability, "constraints", {}) or {})
        mode_values = constraints.get("modes") or constraints.get("assistant_modes")
        if isinstance(mode_values, list):
            current_mode = str(route_context.get("current_mode") or "").strip()
            allowed_modes = {str(item).strip() for item in mode_values if str(item).strip()}
            if allowed_modes and current_mode not in allowed_modes:
                return False
        workspace_id = self._route_workspace_id(route_context)
        endpoint_scope = [str(item).strip() for item in (getattr(endpoint, "workspace_scope", []) or []) if str(item).strip()]
        if workspace_id and endpoint_scope and workspace_id not in endpoint_scope and "*" not in endpoint_scope:
            return False
        constraint_workspaces = constraints.get("workspace_ids") or constraints.get("workspace_scope")
        if isinstance(constraint_workspaces, list):
            allowed_workspaces = {str(item).strip() for item in constraint_workspaces if str(item).strip()}
            if allowed_workspaces and workspace_id and workspace_id not in allowed_workspaces and "*" not in allowed_workspaces:
                return False
        address_values = constraints.get("address_types") or constraints.get("address_type")
        if isinstance(address_values, str):
            address_values = [address_values]
        if isinstance(address_values, list):
            endpoint_context = route_context.get("endpoint") if isinstance(route_context.get("endpoint"), dict) else {}
            route_address_type = str(route_context.get("address_type") or endpoint_context.get("address_type") or "").strip()
            allowed_address_types = {str(item).strip() for item in address_values if str(item).strip()}
            if allowed_address_types and "*" not in allowed_address_types and route_address_type not in allowed_address_types:
                return False
        auth_policy = route_context.get("authorization_policy") if isinstance(route_context.get("authorization_policy"), dict) else {}
        if bool(auth_policy.get("read_only")) and self._endpoint_action_risk(str(getattr(capability, "risk_level", "") or "read")) != "read":
            return False
        return True

    def _contextual_endpoint_tool_schemas(self, route_context: dict[str, Any] | None, *, existing_names: set[str]) -> list[dict[str, Any]]:
        route_context = route_context or {}
        if bool(route_context.get("disable_tools")) or self._core_domain is None:
            return []
        origin_endpoint_id = self._route_endpoint_id(route_context)
        if not origin_endpoint_id:
            return []
        services = getattr(self._core_domain, "services", None)
        if services is None:
            return []
        origin = services.endpoint.get_by_endpoint_id(origin_endpoint_id)
        if origin is None:
            return []
        provider_type = str(getattr(origin, "provider_type", "") or "").strip()
        online_statuses = {"online", "ready", "active"}
        catalog = route_context.setdefault("endpoint_tool_catalog", {})
        tool_map = catalog.setdefault("tools", {})
        schemas: list[dict[str, Any]] = []
        for endpoint in services.endpoint.list_all():
            endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "").strip()
            if not endpoint_id:
                continue
            if provider_type and str(getattr(endpoint, "provider_type", "") or "").strip() != provider_type:
                continue
            if str(getattr(endpoint, "status", "") or "").strip().lower() not in online_statuses:
                continue
            for capability in services.endpoint_capability.list_for_endpoint(endpoint_row_id=getattr(endpoint, "id", None)):
                if not bool(getattr(capability, "enabled", True)):
                    continue
                if not self._visibility_allows_auto_inject(capability):
                    continue
                if not self._endpoint_constraints_allow(capability, endpoint, route_context):
                    continue
                tool_key = str(getattr(capability, "tool_key", "") or "").strip()
                if not tool_key:
                    continue
                capability_id = str(getattr(capability, "capability_id", "") or "")
                suffix = self._endpoint_tool_slug(tool_key)[:48]
                digest = hashlib.sha256(f"{endpoint_id}\n{capability_id}\n{tool_key}".encode("utf-8")).hexdigest()[:10]
                dynamic_name = f"ep_{digest}_{suffix}"
                if dynamic_name in existing_names:
                    continue
                meta = dict(getattr(capability, "meta", {}) or {})
                title = str(meta.get("title") or tool_key).strip()
                description = str(meta.get("description") or title or tool_key).strip()
                input_schema = meta.get("input_schema") if isinstance(meta.get("input_schema"), dict) else getattr(capability, "schema", {})
                output_schema = meta.get("output_schema") if isinstance(meta.get("output_schema"), dict) else {}
                tool_map[dynamic_name] = {
                    "endpoint_id": endpoint_id,
                    "capability_id": capability_id,
                    "tool_key": tool_key,
                    "risk_level": str(getattr(capability, "risk_level", "") or "read"),
                    "requires_confirmation": bool(getattr(capability, "requires_confirmation", False)),
                    "constraints": dict(getattr(capability, "constraints", {}) or {}),
                    "title": title,
                    "description": description,
                    "input_schema": dict(input_schema or {}),
                    "output_schema": dict(output_schema or {}),
                }
                schemas.append(
                    {
                        "type": "function",
                        "function": {
                            "name": dynamic_name,
                            "description": description,
                            "parameters": self._valid_parameters_schema(input_schema),
                            "metadata": {
                                "source": "endpoint",
                                "endpoint_id": endpoint_id,
                                "capability_id": capability_id,
                                "tool_key": tool_key,
                                "risk_level": str(getattr(capability, "risk_level", "") or "read"),
                                "requires_confirmation": bool(getattr(capability, "requires_confirmation", False)),
                                "output_schema": dict(output_schema or {}),
                            },
                        },
                    }
                )
                existing_names.add(dynamic_name)
        catalog["origin_endpoint_id"] = origin_endpoint_id
        catalog["provider_type"] = provider_type
        return schemas

    @staticmethod
    def _resolve_endpoint_catalog_tool(tool_name: str, *, route_context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        route_context = route_context or {}
        catalog = route_context.get("endpoint_tool_catalog") if isinstance(route_context.get("endpoint_tool_catalog"), dict) else {}
        tools = catalog.get("tools") if isinstance(catalog.get("tools"), dict) else {}
        payload = tools.get(str(tool_name or "").strip())
        return dict(payload) if isinstance(payload, dict) else None

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
        dynamic_tool = self._resolve_endpoint_catalog_tool(tool_name, route_context=route_context)
        if dynamic_tool is not None:
            constraints = dict(dynamic_tool.get("constraints") or {})
            action_risk = self._endpoint_action_risk(str(dynamic_tool.get("risk_level") or "read"))
            safe_parallel = bool(constraints.get("safe_parallel", action_risk == "read"))
            try:
                max_concurrency = max(1, int(constraints.get("max_concurrency") or (3 if safe_parallel else 1)))
            except (TypeError, ValueError):
                max_concurrency = 3 if safe_parallel else 1
            return {
                "tool_name": str(tool_name or "").strip(),
                "source": "endpoint",
                "action_risk": action_risk,
                "safe_parallel": safe_parallel,
                "parallel_group": str(constraints.get("parallel_group") or f"endpoint:{dynamic_tool.get('endpoint_id')}"),
                "resource_key": str(constraints.get("resource_key") or f"endpoint:{dynamic_tool.get('endpoint_id')}:{dynamic_tool.get('tool_key')}"),
                "mutates_state": action_risk in {"local_write", "external_write", "destructive"},
                "requires_order": action_risk in {"local_write", "external_write", "destructive"},
                "max_concurrency": max_concurrency,
            }
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
        if not resource_key and normalized_tool_name in _ENDPOINT_LOCAL_FILE_TOOLS:
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
                if normalized in _ENDPOINT_REQUIRED_LOCAL_TOOLS:
                    executor_owner = "tool_router" if self._tool_router_available else "endpoint_required"
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
        dynamic_tool = self._resolve_endpoint_catalog_tool(tool_name, route_context=route_context)
        if dynamic_tool is not None:
            return await self._call_endpoint_catalog_tool(
                tool_name,
                tool_args,
                session_id=session_id,
                route_context=route_context,
                dynamic_tool=dynamic_tool,
            )
        return await self._executor.execute(
            tool_name,
            tool_args,
            session_id=session_id,
            source=source,
            tool_activity_callback=tool_activity_callback,
            route_context=route_context,
        )

    async def _call_endpoint_catalog_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None,
        *,
        session_id: str = "",
        route_context: dict[str, Any] | None = None,
        dynamic_tool: dict[str, Any],
    ) -> ToolCallResult:
        action_risk = self._endpoint_action_risk(str(dynamic_tool.get("risk_level") or "read"))
        if self._core_domain is None or getattr(self._core_domain, "tool_router", None) is None:
            return ToolCallResult.failure(
                tool_name=tool_name,
                source=ToolSourceType.UNKNOWN,
                action_risk=action_risk,
                code="tool_router_unavailable",
                category=ToolErrorCategory.DEPENDENCY,
                message="ToolRouter is unavailable for endpoint catalog tool dispatch.",
                retryable=True,
            )
        if tool_args is not None and not isinstance(tool_args, dict):
            return ToolCallResult.failure(
                tool_name=tool_name,
                source=ToolSourceType.UNKNOWN,
                action_risk=action_risk,
                code="tool_arguments_invalid",
                category=ToolErrorCategory.VALIDATION,
                message="Tool arguments must be a JSON object.",
                details={"tool_name": tool_name, "provided_type": type(tool_args).__name__},
            )
        route_context = route_context or {}
        constraints = dict(dynamic_tool.get("constraints") or {})
        try:
            timeout_seconds = int(constraints.get("timeout_seconds") or constraints.get("timeout") or 120)
        except (TypeError, ValueError):
            timeout_seconds = 120
        try:
            result = await self._core_domain.tool_router.dispatch_tool_call(
                tool_key=str(dynamic_tool.get("tool_key") or "").strip(),
                arguments=dict(tool_args or {}),
                target_endpoint_id=str(dynamic_tool.get("endpoint_id") or "").strip(),
                session_id=session_id,
                workspace_id=self._route_workspace_id(route_context),
                title=f"Endpoint catalog tool: {dynamic_tool.get('tool_key')}",
                timeout_seconds=max(5, timeout_seconds),
                confirmed=False,
            )
        except ToolRouterError as exc:
            category = (
                ToolErrorCategory.PERMISSION
                if exc.code == "tool_confirmation_required"
                else ToolErrorCategory.DEPENDENCY
                if exc.retryable
                else ToolErrorCategory.EXECUTION
            )
            return ToolCallResult.failure(
                tool_name=tool_name,
                source=ToolSourceType.UNKNOWN,
                action_risk=action_risk,
                code=exc.code,
                category=category,
                message=exc.message,
                retryable=exc.retryable,
                details={
                    **dict(exc.details or {}),
                    "endpoint_id": str(dynamic_tool.get("endpoint_id") or ""),
                    "tool_key": str(dynamic_tool.get("tool_key") or ""),
                    "capability_id": str(dynamic_tool.get("capability_id") or ""),
                },
            )
        return normalize_tool_result(
            result,
            tool_name=tool_name,
            source=ToolSourceType.UNKNOWN,
            action_risk=action_risk,
            metadata={
                "source": "endpoint",
                "endpoint_id": str(dynamic_tool.get("endpoint_id") or ""),
                "tool_key": str(dynamic_tool.get("tool_key") or ""),
                "capability_id": str(dynamic_tool.get("capability_id") or ""),
            },
        )
