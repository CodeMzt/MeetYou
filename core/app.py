"""
Application wiring and lifecycle management.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import os
import traceback
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from adapters.base import create_adapter
from core.assistant_modes import AssistantModeManager
from core.brain import Brain, BrainOutputEvent
from core.config import ConfigManager
from core.context import ContextManager
from core.app_lifecycle import (
    run_app_runtime,
    setup_app_runtime,
    shutdown_app_runtime,
    sync_config_state_to_db,
    sync_memory_state_to_db,
    sync_source_catalog_state_to_db,
    sync_task_state_to_db,
)
from core.thread_delivery_bridge import ThreadDeliveryBridge
from core.event_bus import EventBus
from core.exceptions import ConfigError, ExceptionRouter, MeetYouError
from core.heart import Heart
from core.interaction_response_service import InteractionResponseService
from core.io_protocol import (
    EventTarget,
    EventType,
    InboundEvent,
    OutboundEvent,
    SourceKind,
    StreamEventType,
    TargetKind,
    make_source,
    make_target,
)
from core.logger import setup_logger
from core.model_capabilities.resolver import get_model_capability_resolver
from core.runtime_context import bind_event_context, get_event_context, reset_event_context
from core.session_actor import SessionActorRuntime
from core.session_manager import SessionManager
from core.services.heartbeat_workflow import HeartbeatWorkflow
from core.services.thread_titles import extract_title_from_model_text
from core.speaker import Speaker
from core.status import RuntimeStatus, StatusManager, utcnow_iso
from core.tools_manager import ToolsManager
from gateway.api import FastAPIGateway
from platform_layer.detector import detect_platform
from sensors.proprioceptor import Proprioceptor
from service_runtime.models import RuntimeError
from tools import system_tools
from tools.mcp import MCPManager
from tools.memory import Memory
from tools.task_manager import TaskManager

logger = logging.getLogger("meetyou.app")


def _ensure_utc_datetime(value):
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _positive_int_config(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(1, parsed)

_CONTEXT_POOL_TOOL_SKIPLIST = {
    "search_memory",
    "recall_memory",
    "recall_memory_structured",
    "remember_knowledge",
    "save_memory",
    "manage_memories",
    "switch_workspace",
    "list_workspaces",
    "update_context",
    "emit_progress_notice",
    "restart_core",
}

_PROJECT_CONTEXT_SOURCE_LIMIT = 5
_PROJECT_CONTEXT_SOURCE_CONTENT_LIMIT = 1200


@dataclass(slots=True)
class SessionExecutionRequest:
    session_id: str
    event: InboundEvent
    input_info: dict[str, Any]
    target: EventTarget
    is_boot: bool
    is_proactive_idle_poke: bool = False


def _initial_progress_notice_content(metadata: dict[str, Any]) -> str:
    values = dict(metadata or {})
    if bool(values.get("transient")):
        return ""
    if bool(values.get("supports_streaming_reply", True)) and not bool(values.get("progress_notice_autostart")):
        return ""
    policy = str(values.get("progress_notice_policy") or "").strip()
    if policy != "required_before_nontrivial_final" and not bool(values.get("progress_notice_autostart")):
        return ""
    text = str(
        values.get("progress_notice_content")
        or values.get("initial_progress_notice")
        or "我正在处理，请稍候。"
    ).strip()
    return text


_BRAIN_IMMEDIATE_KEYS = {
    "api_provider",
    "api_url",
    "api_key",
    "model",
    "soul_path",
}
_HEART_IMMEDIATE_KEYS = {
    "heartbeat_api_provider",
    "heartbeat_api_url",
    "heartbeat_api_key",
    "housekeeping_interval",
    "heartbeat_interval",
    "heartbeat_idle_poke_enabled",
    "heartbeat_idle_poke_after_seconds",
    "heartbeat_idle_poke_cooldown_seconds",
    "heartbeat_idle_context_compaction_enabled",
    "heart_model",
    "heartbeat_path",
    "scheduler_interval",
}
_MEMORY_IMMEDIATE_KEYS = {
    "embedding_api_url",
    "embedding_api_key",
    "embedding_model",
}
_MODE_IMMEDIATE_KEYS = {
    "assistant_modes",
    "mode_router",
    "trusted_write_roots",
    "source_catalog_path",
    "research_contact_email",
    "document_parsers",
    "office_integrations",
}
_RESTART_REQUIRED_KEYS = {
    "client_access_token",
    "core_cmd_policy_path",
    "core_command_output_max_chars",
    "core_command_timeout_seconds",
    "core_shell_exec_enabled",
    "cmd_policy_path",
    "database_url",
    "enable_feishu_bot",
    "enable_meetwechat_client",
    "feishu_app_id",
    "feishu_app_secret",
    "feishu_broadcast_chat_ids",
    "feishu_default_chat_id",
    "feishu_chat_registry_path",
    "gateway_host",
    "gateway_port",
    "mcp_registry_url",
    "memory_file_path",
    "notion_token",
    "task_file_path",
    "tavily_api_key",
    "tools_schema_path",
    "meetwechat_base_url",
    "meetwechat_error_backoff_seconds",
    "meetwechat_max_text_chars",
    "meetwechat_poll_interval_seconds",
    "meetwechat_proxy_policy",
    "meetwechat_state_file",
    "meetwechat_inbound_worker_count",
    "meetwechat_inbound_queue_size",
    "meetwechat_outbound_worker_count",
    "meetwechat_outbound_queue_size",
    "meetwechat_outbound_min_interval_ms",
    "meetwechat_send_timeout_ms",
    "meetwechat_state_flush_interval_ms",
    "meetwechat_gateway_endpoint_idle_ttl_seconds",
}


class App:
    def __init__(self, health_getter=None, telemetry_recorder=None, restart_requester=None):
        setup_logger(enable_console=True, component="service")

        self.event_bus = EventBus()
        self.exception_router = ExceptionRouter()
        self.config = ConfigManager()
        self.platform = detect_platform()
        self.status_manager = StatusManager()
        self.mode_manager = AssistantModeManager(self.config)

        self.main_adapter = create_adapter(self._get_main_provider())
        self.heart_adapter = create_adapter(self._get_heart_provider())

        self.memory = Memory()
        self.task_manager = TaskManager(
            self.memory,
            task_file_path=self.config.get("task_file_path") or "user/memory_tasks.json",
        )
        self.mcp_manager = MCPManager()
        system_tools.init_system_tools(
            self.platform,
            self.event_bus,
            self.config.get("cmd_policy_path") or "user/cmd_policy.json",
            allow_local_fallback=False,
            core_shell_exec_enabled=self.config.get_bool("core_shell_exec_enabled", True),
            core_cmd_policy_path=self.config.get("core_cmd_policy_path") or "user/core_cmd_policy.json",
            core_command_timeout_seconds=_positive_int_config(
                self.config.get("core_command_timeout_seconds"),
                120,
            ),
            core_command_output_max_chars=_positive_int_config(
                self.config.get("core_command_output_max_chars"),
                20000,
            ),
        )

        self.context_manager = ContextManager(self.memory, self.main_adapter, self.event_bus)
        self.tools_manager = ToolsManager(
            self.memory,
            self.context_manager,
            self.mcp_manager,
            system_tools,
            self.mode_manager,
            task_manager=self.task_manager,
            config=self.config,
        )
        self.brain = Brain(
            self.main_adapter,
            self.tools_manager,
            self.context_manager,
            self.event_bus,
            self.exception_router,
            mode_manager=self.mode_manager,
        )
        self.brain.set_performance_config(self.config)
        self.brain.set_provider_name(self._get_main_provider())
        self.heart = Heart(
            self.heart_adapter,
            self.config,
            self.tools_manager,
            self.memory,
            self.task_manager,
            self.event_bus,
            self.exception_router,
            status_callback=self._update_heartbeat_status,
        )
        system_tools.set_background_status_provider(self.heart.get_background_status)
        system_tools.set_heartbeat_settings_provider(self.get_heartbeat_settings)
        system_tools.set_heartbeat_settings_updater(self.update_heartbeat_settings)
        system_tools.set_progress_notice_emitter(self.emit_progress_notice)

        self.session_manager = SessionManager()
        self.heart.set_session_manager(self.session_manager)
        self.speaker = Speaker(self.session_manager)
        self.gateway: FastAPIGateway | None = None
        self.core_domain = None
        self.db_engine = None
        self.db_session_factory = None
        self.core_services = None
        self.proprioceptor = Proprioceptor(self.platform, self.context_manager, self.event_bus)
        self._health_getter = health_getter
        self._telemetry_recorder = telemetry_recorder
        self._restart_requester = restart_requester
        self.tools_manager.set_execution_observer(self._observe_tool_result)

        self._brain_source = make_source(SourceKind.SYSTEM.value, "brain")
        self._runtime_source = make_source(SourceKind.SYSTEM.value, "runtime")
        self._usage_source = make_source(SourceKind.SYSTEM.value, "usage")
        self._control_source = make_source(SourceKind.SYSTEM.value, "reply_control")
        self._session_execution_runtime = SessionActorRuntime(self._process_session_execution)
        self._confirm_approval_requests: dict[str, dict[str, Any]] = {}
        self._interaction_responses = InteractionResponseService(self.event_bus)
        self._thread_delivery_bridge = ThreadDeliveryBridge(
            gateway_getter=lambda: getattr(self, "gateway", None),
            core_services_getter=lambda: getattr(self, "core_services", None),
        )

        self.exception_router.on_system_error(self._log_error)
        self.exception_router.on_user_error(self._display_error)
        self.event_bus.subscribe(self.event_bus.CONFIRM_REQUEST, self._handle_confirm_request)
        self.event_bus.subscribe(self.event_bus.CONFIRM_RESPONSE, self._handle_confirm_response)
        self.event_bus.subscribe(self.event_bus.HUMAN_INPUT_REQUEST, self._handle_human_input_request)
        self.event_bus.subscribe(self.event_bus.HUMAN_INPUT_RESPONSE, self._handle_human_input_response)

        logger.info("Service runtime dependencies initialized")

    def _get_thread_delivery_bridge(self) -> ThreadDeliveryBridge:
        bridge = getattr(self, "_thread_delivery_bridge", None)
        if isinstance(bridge, ThreadDeliveryBridge):
            return bridge
        bridge = ThreadDeliveryBridge(
            gateway_getter=lambda: getattr(self, "gateway", None),
            core_services_getter=lambda: getattr(self, "core_services", None),
        )
        self._thread_delivery_bridge = bridge
        return bridge

    def _runtime_principal_context(self) -> dict[str, str]:
        principal = getattr(getattr(self, "core_domain", None), "principal", None)
        if principal is None:
            return {}
        payload = {
            "principal_id": str(getattr(principal, "id", "") or "").strip(),
            "principal_key": str(getattr(principal, "principal_key", "") or "").strip(),
        }
        return {key: value for key, value in payload.items() if value}

    def _actor_row_id(self, actor_id: str = ""):
        core_services = getattr(self, "core_services", None)
        actor_service = getattr(core_services, "actor", None) if core_services is not None else None
        if actor_service is None:
            return None
        normalized_actor_id = str(actor_id or "").strip()
        if not normalized_actor_id:
            principal = getattr(getattr(self, "core_domain", None), "principal", None)
            principal_key = str(getattr(principal, "principal_key", "") or "self").strip() or "self"
            normalized_actor_id = f"user:{principal_key}"
        actor = actor_service.get_by_actor_id(normalized_actor_id)
        if actor is not None:
            return getattr(actor, "id", None)
        ensure_actor = getattr(actor_service, "ensure_actor", None)
        if not callable(ensure_actor):
            return None
        if normalized_actor_id.startswith("system."):
            actor_type = normalized_actor_id.replace(".", "_")
            display_name = normalized_actor_id
            permission_profile_id = f"profile.{actor_type}"
            actor = ensure_actor(
                actor_id=normalized_actor_id,
                actor_type=actor_type,
                display_name=display_name,
                permission_profile_id=permission_profile_id,
            )
            return getattr(actor, "id", None)
        principal = getattr(getattr(self, "core_domain", None), "principal", None)
        principal_key = str(getattr(principal, "principal_key", "") or "self").strip() or "self"
        actor = ensure_actor(
            actor_id=normalized_actor_id,
            actor_type="user",
            owner_user_id=principal_key,
            display_name=str(getattr(principal, "display_name", "") or principal_key),
            permission_profile_id="profile.default_user",
        )
        return getattr(actor, "id", None)

    def _observe_tool_result(self, tool_name: str, result, tool_args: dict | None = None) -> None:
        if self._telemetry_recorder is not None:
            try:
                self._telemetry_recorder.observe_tool_result(tool_name, result, tool_args=tool_args)
            except Exception as exc:
                logger.debug("Tool telemetry observer failed: %s", exc, exc_info=True)
        if str(tool_name or "").strip() in _CONTEXT_POOL_TOOL_SKIPLIST:
            return
        if not getattr(result, "ok", False):
            return
        core_services = getattr(self, "core_services", None)
        context_pool = getattr(core_services, "context_pool", None) if core_services is not None else None
        principal = getattr(getattr(self, "core_domain", None), "principal", None)
        if context_pool is None or principal is None:
            return
        try:
            context_pool.record_tool_result_by_context(
                principal_id=principal.id,
                tool_name=tool_name,
                result=result,
                tool_args=tool_args,
                event_context=get_event_context(),
            )
        except Exception as exc:
            logger.debug("Failed to record tool result into ContextPool: %s", exc, exc_info=True)

    def _get_main_provider(self) -> str:
        return self.config.get("api_provider") or "openai"

    def _get_heart_provider(self) -> str:
        return self.config.get("heartbeat_api_provider") or self._get_main_provider()

    @staticmethod
    def _safe_int(value: Any, default: int | None = None) -> int | None:
        if value in (None, ""):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _build_model_options(self, metadata: dict | None = None) -> dict:
        metadata = metadata or {}
        overrides = metadata.get("input_options") or {}
        thinking_override = overrides.get("thinking") or {}

        default_enabled = self.config.get_bool("thinking_enabled", False)
        default_effort = self.config.get("thinking_effort") or None
        default_budget = self._safe_int(self.config.get("thinking_budget_tokens"))

        thinking_enabled = bool(thinking_override.get("enabled", default_enabled))
        if thinking_enabled:
            thinking = {
                "enabled": True,
                "effort": thinking_override.get("effort", default_effort) or None,
                "budget_tokens": self._safe_int(
                    thinking_override.get("budget_tokens"),
                    default_budget,
                ),
            }
        else:
            thinking = {"enabled": False, "effort": None, "budget_tokens": None}
        return {"thinking": thinking}

    async def generate_thread_title_from_user_message(
        self,
        *,
        content: str,
        thread_id: str = "",
        message_id: str = "",
    ) -> dict[str, str]:
        del thread_id, message_id
        prompt_content = str(content or "").strip()
        if not prompt_content:
            return {"title": "", "provider": self._get_main_provider(), "model": str(self.config.get("model") or "")}
        if not self.brain.is_initialized or getattr(self.brain, "_http_session", None) is None:
            return {"title": "", "provider": self._get_main_provider(), "model": str(self.config.get("model") or ""), "error": "brain_not_initialized"}

        provider = self._get_main_provider()
        model = str(self.config.get("model") or "")
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 MeetYou 的会话标题生成器。只根据用户首条消息生成一个简短中文标题。"
                    "不要照抄完整问题，不要解释，不要加引号，不要使用句号。"
                    "标题应概括意图或主题，优先 6 到 14 个汉字，最长 24 个字符。"
                ),
            },
            {
                "role": "user",
                "content": f"用户首条消息：\n{prompt_content[:2400]}\n\n请只输出标题。",
            },
        ]
        adapter_options = Brain._build_adapter_options({"thinking": {"enabled": False, "effort": None, "budget_tokens": None}})
        try:
            result = await asyncio.wait_for(
                self.main_adapter.chat(
                    self.brain._http_session,
                    self.config.get("api_url") or "",
                    self.config.get("api_key") or "",
                    model,
                    messages,
                    tools=None,
                    **adapter_options,
                ),
                timeout=20,
            )
        except Exception as exc:
            logger.warning("Auto thread title generation failed: %s", exc)
            return {"title": "", "provider": provider, "model": model, "error": type(exc).__name__}

        title = extract_title_from_model_text(str(result.get("content") or ""))
        return {"title": title, "provider": provider, "model": model}

    async def _log_error(self, error: MeetYouError):
        logger.error("[SYSTEM] %s: %s", type(error).__name__, error)

    async def _display_error(self, error: MeetYouError):
        context = get_event_context()
        session_id = context.get("session_id", "")
        target = context.get("target")
        if session_id:
            await self.speaker.emit_error(
                session_id,
                str(error),
                make_source(SourceKind.SYSTEM.value, "exception"),
                target=target if isinstance(target, EventTarget) else None,
            )
            return
        logger.warning("User-level error without bound session: %s", error)

    async def _emit_runtime_status_event(
        self,
        session_id: str,
        target: EventTarget | None,
        turn_id: str = "",
    ):
        snapshot = self.brain.get_session_runtime_snapshot(session_id)
        if snapshot is None:
            return
        metadata = {"turn_id": turn_id or snapshot.get("turn_id", "")}
        await self.speaker.emit(
            OutboundEvent(
                session_id=session_id,
                type=EventType.RUNTIME_STATUS.value,
                role="system",
                content=snapshot,
                source=self._runtime_source,
                target=target or EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                metadata=metadata,
            )
        )
        await self._get_thread_delivery_bridge().publish_runtime_state(session_id, snapshot, turn_id=metadata["turn_id"])

    async def _emit_usage_event(
        self,
        session_id: str,
        payload: dict,
        target: EventTarget | None,
        turn_id: str = "",
    ):
        await self.speaker.emit(
            OutboundEvent(
                session_id=session_id,
                type=EventType.USAGE.value,
                role="system",
                content=payload,
                source=self._usage_source,
                target=target or EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                metadata={"turn_id": turn_id},
            )
        )
        await self._get_thread_delivery_bridge().publish_runtime_usage(session_id, payload)

    async def _emit_reasoning_stream_event(
        self,
        session_id: str,
        stream_id: str,
        phase: str,
        content: str,
        target: EventTarget | None,
        turn_id: str,
    ):
        await self.speaker.emit(
            OutboundEvent(
                session_id=session_id,
                type=EventType.REASONING.value,
                role="assistant",
                content=content,
                source=self._brain_source,
                target=target or EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                stream_id=stream_id,
                metadata={
                    "stream_event": phase,
                    "stream_channel": "reasoning",
                    "turn_id": turn_id,
                },
            )
        )
        await self._get_thread_delivery_bridge().publish_reasoning_event(
            session_id,
            stream_id=stream_id,
            turn_id=turn_id,
            phase=phase,
            content=content,
        )

    async def _handle_confirm_request(self, event):
        approval_context = self._ensure_confirm_approval_context(event)
        snapshot = self.brain.get_session_runtime_snapshot(event.session_id) or {}
        self.brain.set_session_runtime_state(
            event.session_id,
            RuntimeStatus.WAITING_CONFIRM.value,
            detail="Waiting for confirmation",
            active_tools=snapshot.get("active_tools", []),
            stream_id=snapshot.get("stream_id", ""),
            turn_id=snapshot.get("turn_id", ""),
        )
        await self._emit_runtime_status_event(
            event.session_id,
            event.target if isinstance(event.target, EventTarget) else None,
            snapshot.get("turn_id", ""),
        )
        await self.speaker.emit(event)
        await self._get_thread_delivery_bridge().publish_confirm_request(event, approval_context=approval_context)

    async def _handle_confirm_response(self, payload):
        if not isinstance(payload, dict):
            return
        session_id = payload.get("session_id", "")
        if not session_id:
            return
        request_id = str(payload.get("request_id") or "").strip()
        if request_id:
            context = self._confirm_approval_requests.get(request_id)
            if isinstance(context, dict):
                endpoint_id = str(payload.get("endpoint_id") or "").strip()
                if endpoint_id:
                    context["endpoint_id"] = endpoint_id
                    self._confirm_approval_requests[request_id] = context
        request_id = str(payload.get("request_id") or "").strip()
        approval_context = self._apply_confirm_approval_decision(
            request_id=request_id,
            accepted=bool(payload.get("accepted")),
            reason=str(payload.get("reason") or "").strip(),
        )
        snapshot = self.brain.get_session_runtime_snapshot(session_id) or {}
        self.brain.set_session_runtime_state(
            session_id,
            RuntimeStatus.TOOL_CALLING.value,
            detail="Resuming tool call",
            active_tools=snapshot.get("active_tools", []),
            stream_id=snapshot.get("stream_id", ""),
            turn_id=snapshot.get("turn_id", ""),
        )
        await self._emit_runtime_status_event(
            session_id,
            EventTarget(kind=TargetKind.CURRENT_SESSION.value),
            snapshot.get("turn_id", ""),
        )
        await self._get_thread_delivery_bridge().publish_confirm_resolution(payload, approval_context=approval_context)
        if request_id:
            self._confirm_approval_requests.pop(request_id, None)

    def _ensure_confirm_approval_context(self, event) -> dict[str, Any]:
        request_id = str(getattr(event, "request_id", "") or "").strip()
        if not request_id:
            return {}
        existing = self._confirm_approval_requests.get(request_id)
        if existing:
            return dict(existing)

        core_services = getattr(self, "core_services", None)
        if core_services is None:
            return {}

        session_id = str(getattr(event, "session_id", "") or "").strip()
        if not session_id:
            return {}
        session_row = core_services.session.get_by_session_id(session_id)
        if session_row is None:
            return {}
        thread_row = core_services.thread.get_by_id(session_row.thread_id)
        if thread_row is None:
            return {}
        workspace_row = core_services.workspace.get_by_id(session_row.workspace_id)

        event_metadata = dict(getattr(event, "metadata", {}) or {})
        approval_type = str(event_metadata.get("approval_type") or "chat_confirmation").strip() or "chat_confirmation"
        operation_type = str(event_metadata.get("approval_operation_type") or "chat_confirmation").strip() or "chat_confirmation"
        operation_title = str(event_metadata.get("approval_title") or "Chat Confirmation").strip() or "Chat Confirmation"
        risk_level = str(
            event_metadata.get("risk_level")
            or event_metadata.get("action_risk")
            or "system"
        ).strip().lower() or "system"
        operation = core_services.operation.create_operation(
            thread_id=thread_row.id,
            workspace_id=session_row.workspace_id,
            operation_type=operation_type,
            execution_target="core.local",
            title=operation_title,
            requested_by_actor_id=self._actor_row_id(),
            requested_by_session_id=session_row.id,
            status="waiting_approval",
            metadata={
                "confirm_request_id": request_id,
                "confirm_session_id": session_id,
                "confirm_prompt": str(getattr(event, "content", "") or ""),
                "approval_required": True,
                "source": "event_bus_confirm",
                **({"approval_metadata": dict(event_metadata)} if event_metadata else {}),
            },
        )
        approval = core_services.approval.create_approval(
            operation_id=operation.id,
            approval_type=approval_type,
            risk_level=risk_level,
        )
        operation = core_services.operation.update_status(
            operation_id=operation.id,
            status="waiting_approval",
            metadata={
                "approval_id": approval.approval_id,
                "approval_status": approval.status,
                "approval_type": approval.approval_type,
                "approval_risk_level": approval.risk_level,
                "approval_required": True,
            },
        ) or operation

        context = {
            "request_id": request_id,
            "session_id": session_id,
            "thread_id": thread_row.thread_id,
            "workspace_id": getattr(workspace_row, "workspace_id", ""),
            "operation_id": operation.operation_id,
            "operation_row_id": operation.id,
            "operation_status": operation.status,
            "approval_id": approval.approval_id,
            "approval_status": approval.status,
            "approval_type": approval.approval_type,
            "risk_level": approval.risk_level,
        }
        self._confirm_approval_requests[request_id] = context
        return dict(context)

    def get_confirm_approval_context(self, request_id: str) -> dict[str, Any]:
        normalized = str(request_id or "").strip()
        if not normalized:
            return {}
        return dict(self._confirm_approval_requests.get(normalized) or {})

    def _apply_confirm_approval_decision(self, *, request_id: str, accepted: bool, reason: str = "") -> dict[str, Any]:
        normalized_request_id = str(request_id or "").strip()
        if not normalized_request_id:
            return {}
        context = dict(self._confirm_approval_requests.get(normalized_request_id) or {})
        if not context:
            return {}

        core_services = getattr(self, "core_services", None)
        if core_services is None:
            return context

        approval_id = str(context.get("approval_id") or "").strip()
        operation_row_id = context.get("operation_row_id")
        approval = core_services.approval.get_by_approval_id(approval_id) if approval_id else None
        if approval is not None and approval.status == "pending":
            approval = core_services.approval.decide_approval(
                approval_id=approval.approval_id,
                decision="approve" if accepted else "reject",
                reason=reason,
                decided_by_actor_id=self._actor_row_id(),
            )

        if operation_row_id is not None:
            operation = core_services.operation.update_status(
                operation_id=operation_row_id,
                status="succeeded" if accepted else "rejected",
                result_summary="确认已通过" if accepted else (reason or "确认已拒绝"),
                metadata={
                    "approval_id": approval_id,
                    "approval_status": getattr(approval, "status", ""),
                    "approval_required": True,
                    "confirm_decision": "approve" if accepted else "reject",
                },
            )
            if operation is not None:
                context["operation_status"] = operation.status

        if approval is not None:
            context["approval_status"] = approval.status
        self._confirm_approval_requests[normalized_request_id] = context
        return context

    async def _handle_human_input_request(self, event):
        snapshot = self.brain.get_session_runtime_snapshot(event.session_id) or {}
        self.brain.set_session_runtime_state(
            event.session_id,
            RuntimeStatus.WAITING_HUMAN_INPUT.value,
            detail="Waiting for human input",
            active_tools=snapshot.get("active_tools", []),
            stream_id=snapshot.get("stream_id", ""),
            turn_id=snapshot.get("turn_id", ""),
        )
        await self._emit_runtime_status_event(
            event.session_id,
            event.target if isinstance(event.target, EventTarget) else None,
            snapshot.get("turn_id", ""),
        )
        await self.speaker.emit(event)
        await self._get_thread_delivery_bridge().publish_human_input_request(event)

    async def _handle_human_input_response(self, payload):
        if not isinstance(payload, dict):
            return
        session_id = payload.get("session_id", "")
        if not session_id:
            return
        snapshot = self.brain.get_session_runtime_snapshot(session_id) or {}
        self.brain.set_session_runtime_state(
            session_id,
            RuntimeStatus.TOOL_CALLING.value,
            detail="Resuming tool call",
            active_tools=snapshot.get("active_tools", []),
            stream_id=snapshot.get("stream_id", ""),
            turn_id=snapshot.get("turn_id", ""),
        )
        await self._emit_runtime_status_event(
            session_id,
            EventTarget(kind=TargetKind.CURRENT_SESSION.value),
            snapshot.get("turn_id", ""),
        )
        await self._get_thread_delivery_bridge().publish_human_input_resolution(payload)

    async def _update_heartbeat_status(self, status: str, detail: str = ""):
        snapshot = self.status_manager.set_heartbeat(status, detail)
        await self.speaker.emit(
            OutboundEvent(
                session_id="system:heart",
                type=EventType.RUNTIME_STATUS.value,
                role="system",
                content=snapshot,
                source=self._runtime_source,
                target=EventTarget(kind=TargetKind.BROADCAST.value),
            )
        )

    async def _refresh_brain_runtime(self):
        self.main_adapter = create_adapter(self._get_main_provider())
        self.context_manager.set_adapter(self.main_adapter)
        self.brain.set_adapter(self.main_adapter)
        self.brain.set_provider_name(self._get_main_provider())
        sys_prompt = self.config.get_prompt("soul")
        if not self.brain.is_initialized:
            await self.brain.init_brain(sys_prompt)
            return
        persisted_context = await self.context_manager.load_context()
        await self.brain.refresh_base_prompt(sys_prompt, persisted_context)

    async def _refresh_heart_runtime(self):
        self.heart_adapter = create_adapter(self._get_heart_provider())
        self.heart.set_adapter(self.heart_adapter)
        await self.heart.refresh_config()
        system_tools.set_background_status_provider(self.heart.get_background_status)
        system_tools.set_heartbeat_settings_provider(self.get_heartbeat_settings)
        system_tools.set_heartbeat_settings_updater(self.update_heartbeat_settings)
        system_tools.set_progress_notice_emitter(self.emit_progress_notice)
        system_tools.set_core_restart_handler(self.request_core_restart)

    async def _refresh_mode_runtime(self):
        self.mode_manager = AssistantModeManager(self.config)
        tools_manager_setter = getattr(self.tools_manager, "set_mode_manager", None)
        if callable(tools_manager_setter):
            tools_manager_setter(self.mode_manager)
        brain_setter = getattr(self.brain, "set_mode_manager", None)
        if callable(brain_setter):
            brain_setter(self.mode_manager)

    def _resolve_background_target(self, session_id: str, target: EventTarget) -> EventTarget:
        resolved_target = target
        if target.kind == TargetKind.CURRENT_SESSION.value and session_id:
            resolved_target = self.session_manager.get_default_target(session_id)
        return EventTarget(
            kind=str(getattr(resolved_target, "kind", "") or ""),
            id=str(getattr(resolved_target, "id", "") or ""),
            metadata=dict(getattr(resolved_target, "metadata", {}) or {}),
        )

    def _resolve_session_thread_id(self, session_id: str) -> str:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return ""
        core_services = getattr(self, "core_services", None)
        if core_services is not None:
            session_row = core_services.session.get_by_session_id(normalized_session_id)
            if session_row is not None:
                thread_row = core_services.thread.get_by_id(session_row.thread_id)
                thread_id = str(getattr(thread_row, "thread_id", "") or "").strip()
                if thread_id:
                    return thread_id
        session_manager = getattr(self, "session_manager", None)
        get_binding = getattr(session_manager, "get_binding", None)
        if not callable(get_binding):
            return ""
        binding = get_binding(normalized_session_id)
        metadata = dict(getattr(binding, "metadata", {}) or {}) if binding is not None else {}
        return str(metadata.get("thread_id") or "").strip()

    def _has_active_endpoint_thread(self, session_id: str) -> bool:
        thread_id = self._resolve_session_thread_id(session_id)
        if not thread_id:
            return False
        gateway = getattr(self, "gateway", None)
        endpoint_ws_manager = getattr(gateway, "endpoint_ws_manager", None)
        has_subscription = getattr(endpoint_ws_manager, "has_subscription", None)
        return bool(callable(has_subscription) and has_subscription(target_type="thread", target_id=thread_id))

    def _can_deliver_task_update(self, session_id: str, target: EventTarget) -> bool:
        resolved_target = self._resolve_background_target(session_id, target)
        if resolved_target.kind == TargetKind.WEB.value:
            return self._has_active_endpoint_thread(session_id)
        if resolved_target.kind in {TargetKind.FEISHU.value, TargetKind.WECHAT.value}:
            return self._has_active_endpoint_thread(session_id)
        if resolved_target.kind == TargetKind.CLI.value:
            return bool(session_id)
        return False

    def _can_persist_client_thread_message(self, session_id: str, target: EventTarget) -> bool:
        resolved_target = self._resolve_background_target(session_id, target)
        if resolved_target.kind not in {TargetKind.WEB.value, TargetKind.FEISHU.value, TargetKind.WECHAT.value}:
            return False
        return bool(self._resolve_session_thread_id(session_id))

    async def _deliver_background_message(
        self,
        session_id: str,
        target: EventTarget,
        message: str,
        *,
        activity_kind: str,
    ) -> bool:
        if not session_id or not message:
            return False
        resolved_target = self._resolve_background_target(session_id, target)
        if resolved_target.kind in {TargetKind.WEB.value, TargetKind.FEISHU.value, TargetKind.WECHAT.value} and self._can_persist_client_thread_message(session_id, resolved_target):
            await self._get_thread_delivery_bridge().persist_and_publish_assistant_message(
                session_id,
                content=message,
                stream_id="",
                turn_id=uuid4().hex,
            )
            return True
        if resolved_target.kind == TargetKind.CLI.value:
            await self.speaker.emit_text(
                session_id,
                message,
                self._runtime_source,
                target=resolved_target,
                metadata={"activity_kind": activity_kind},
            )
            return True
        return False

    async def _emit_pending_task_updates(self, session_id: str, target: EventTarget, source) -> None:
        del session_id, target, source
        return

    def _recent_user_delivery(self, *, require_deliverable: bool = True) -> tuple[str, EventTarget] | None:
        list_recent = getattr(self.session_manager, "list_recent_bindings", None)
        if not callable(list_recent):
            return None
        for binding in list_recent():
            session_id = str(getattr(binding, "session_id", "") or "").strip()
            if not session_id or session_id.startswith("system:"):
                continue
            source = getattr(binding, "source", None)
            source_kind = str(getattr(source, "kind", "") or "").strip().lower()
            if source_kind not in {SourceKind.WEB.value, SourceKind.FEISHU.value, SourceKind.WECHAT.value, SourceKind.CLI.value}:
                continue
            target = getattr(binding, "default_target", None)
            if target is None:
                continue
            resolved_target = EventTarget(
                kind=str(getattr(target, "kind", "") or ""),
                id=str(getattr(target, "id", "") or ""),
                metadata=dict(getattr(target, "metadata", {}) or {}),
            )
            if self._can_deliver_task_update(session_id, resolved_target) or (
                not require_deliverable and self._can_persist_client_thread_message(session_id, resolved_target)
            ):
                return session_id, resolved_target
        return None


    def _recent_thread_delivery_bridge_metadata(self, *, workspace_ids: list[str] | None = None) -> dict[str, str]:
        list_recent = getattr(self.session_manager, "list_recent_bindings", None)
        if not callable(list_recent):
            return {}
        allowed_workspace_ids = {str(item or "").strip() for item in (workspace_ids or []) if str(item or "").strip()}
        fallback: dict[str, str] = {}
        for binding in list_recent():
            session_id = str(getattr(binding, "session_id", "") or "").strip()
            if not session_id or session_id.startswith("system:"):
                continue
            source = getattr(binding, "source", None)
            source_kind = str(getattr(source, "kind", "") or "").strip().lower()
            if source_kind not in {SourceKind.WEB.value, SourceKind.FEISHU.value, SourceKind.WECHAT.value, SourceKind.CLI.value}:
                continue
            metadata = dict(getattr(binding, "metadata", {}) or {})
            thread_id = str(metadata.get("thread_id") or "").strip()
            if not thread_id:
                continue
            candidate = {
                "thread_id": thread_id,
                "workspace_id": str(metadata.get("workspace_id") or "").strip(),
                "endpoint_id": str(metadata.get("endpoint_id") or "").strip(),
                "bridged_session_id": session_id,
            }
            if allowed_workspace_ids and candidate["workspace_id"] in allowed_workspace_ids:
                return candidate
            if not fallback:
                fallback = candidate
        return fallback

    @staticmethod
    def _is_heartbeat_signal(event: InboundEvent) -> bool:
        return (
            event.type == EventType.SIGNAL.value
            and (
                str(event.session_id or "").strip() == "system:heart"
                or str(getattr(event.source, "kind", "") or "").strip().lower() == SourceKind.HEART.value
            )
        )

    def _build_signal_input(self, event: InboundEvent) -> dict[str, Any]:
        message = str(event.content or "").strip()
        decision = str((event.metadata or {}).get("heartbeat_decision") or "notify").strip().lower()
        signal_kind = str((event.metadata or {}).get("heartbeat_signal_kind") or "system_issue").strip().lower()
        severity = "high" if decision == "escalate" else "medium"
        guidance_map = {
            "urgent_deadline": (
                "There is a time-sensitive scheduled follow-up that may need user attention.\n"
                "If you respond, keep it to at most two short sentences.\n"
                "Do not frame it as a hard deadline unless the issue explicitly says the user is at risk of missing something.\n"
                "Mention only the nearest scheduled follow-up and the next helpful step."
            ),
            "temporal_attention": (
                "There is a time-sensitive scheduled follow-up that may need user attention.\n"
                "If you respond, keep it to at most two short sentences.\n"
                "Do not frame it as a hard deadline unless the issue explicitly says the user is at risk of missing something.\n"
                "Mention only the nearest scheduled follow-up and the next helpful step."
            ),
            "system_issue": (
                "There is a concrete background issue that may affect task execution or reminders.\n"
                "If you respond, keep it to at most two short sentences.\n"
                "Focus only on the relevant issue and the practical next step."
            ),
            "idle_poke": (
                "There is no critical system issue.\n"
                "If you respond, send exactly one short natural sentence.\n"
                "Do not mention background checks, diagnostics, or internal signals."
            ),
        }
        return {
            "role": "system",
            "content": (
                "[Background Signal]\n"
                "A background heartbeat check detected something that may deserve a proactive user-facing follow-up.\n"
                f"Signal kind: {signal_kind}\n"
                f"Severity: {severity}\n"
                f"Observed issue: {message}\n"
                "If you respond, keep the existing assistant persona and the same style as the current conversation.\n"
                "Do not switch into a special alerting or ops tone.\n"
                + guidance_map.get(
                    signal_kind,
                    "Focus on the concrete impact, whether action is actually needed, and the next helpful step.",
                )
            ),
            "metadata": {
                **dict(getattr(event, "metadata", {}) or {}),
                "transient": True,
                "disable_tools": True,
            },
        }

    async def _handle_control_event(self, event):
        metadata = dict(getattr(event, "metadata", {}) or {})
        control_kind = str(metadata.get("control_kind") or "").strip().lower()
        payload = event.content if isinstance(event.content, dict) else {}
        task_key = str(payload.get("task_key") or "").strip()
        if control_kind == "reply_control":
            await self._handle_reply_control_event(event)
            return True
        if control_kind in {"scheduled_task", "scheduled_reminder"} and task_key:
            logger.info(
                "Ignoring legacy TaskManager scheduler control event for %s; V4 Scheduler jobs run through scheduled_jobs and RunEventLog.",
                task_key,
            )
            return True
        return False

    def get_config_snapshot(self) -> dict[str, dict[str, Any]]:
        return self.config.snapshot()

    def get_config_entry(self, key: str) -> dict[str, Any]:
        return self.config.describe_key(key)

    def get_memory_snapshot(
        self,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
    ) -> dict[str, Any]:
        return self.memory.get_memory_snapshot(
            source_id=source_id,
            session_id=session_id,
            include_invalidated=include_invalidated,
        )

    def get_memory_graph(
        self,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
    ) -> dict[str, Any]:
        return self.memory.get_memory_graph_view(
            source_id=source_id,
            session_id=session_id,
            include_invalidated=include_invalidated,
        )

    async def clear_memory_state(self) -> dict[str, Any]:
        memory_result = await self.memory.clear_all()
        session_result = self.brain.clear_all_conversation_state()
        return {
            "ok": True,
            **memory_result,
            **session_result,
            "updated_at": utcnow_iso(),
        }

    async def update_memory_record_status(self, memory_id: str, status: str) -> dict[str, Any]:
        return await self.memory.update_record_status(memory_id, status)

    async def delete_memory_record(self, memory_id: str) -> dict[str, Any]:
        return await self.memory.delete_record(memory_id)

    async def _sync_config_state_to_db(self) -> None:
        await sync_config_state_to_db(self)

    async def _sync_memory_state_to_db(self) -> None:
        await sync_memory_state_to_db(self)

    async def _sync_task_state_to_db(self) -> None:
        await sync_task_state_to_db(self)

    async def _sync_source_catalog_state_to_db(self) -> None:
        await sync_source_catalog_state_to_db(self)

    def get_runtime_state(self, session_id: str = "") -> dict[str, Any]:
        return {
            "global_state": self.status_manager.get_global(),
            "heartbeat_state": self.status_manager.get_heartbeat(),
            "session_state": self.brain.get_session_runtime_snapshot(session_id) if session_id else None,
        }

    def get_core_mcp_diagnostics(self) -> dict[str, Any]:
        configured_servers = sorted(self.config.get_mcp_servers())
        mcp_manager = getattr(self, "mcp_manager", None)
        runtime_server_diagnostics = list(
            getattr(mcp_manager, "get_server_diagnostics", lambda: [])()
        )
        available_servers = [
            str(item.get("server_name") or "").strip()
            for item in runtime_server_diagnostics
            if str(item.get("status") or "").strip() == "enabled"
            and str(item.get("server_name") or "").strip()
        ]
        mode_manager = getattr(self, "mode_manager", None)
        if mode_manager is not None and hasattr(mode_manager, "get_core_mcp_boundary_diagnostics"):
            boundary = mode_manager.get_core_mcp_boundary_diagnostics(
                available_mcp_servers=available_servers,
                configured_mcp_servers=configured_servers,
            )
        else:
            boundary = {
                "classification_standard": {},
                "core_mcp_servers": [],
                "client_managed_mcp_servers": [],
                "runtime_native_tools": [],
                "summary": {
                    "configured_server_count": len(configured_servers),
                    "enabled_count": len(available_servers),
                    "partial_failure_count": 0,
                    "partial_failure_servers": [],
                    "client_managed_server_count": 0,
                    "runtime_native_exception_count": 0,
                },
            }
        runtime_by_name = {
            str(item.get("server_name") or "").strip(): dict(item)
            for item in runtime_server_diagnostics
            if str(item.get("server_name") or "").strip()
        }
        enriched_core_servers: list[dict[str, Any]] = []
        for item in boundary.get("core_mcp_servers", []):
            payload = dict(item or {})
            runtime_payload = runtime_by_name.get(str(payload.get("server_name") or "").strip(), {})
            if runtime_payload:
                payload["runtime"] = runtime_payload
                runtime_status = str(runtime_payload.get("status") or "").strip()
                runtime_usable = runtime_payload.get("usable")
                if runtime_status:
                    payload["status"] = runtime_status
                    payload["usable"] = (
                        bool(runtime_usable)
                        if isinstance(runtime_usable, bool)
                        else runtime_status == "enabled"
                    )
                    payload["degraded"] = runtime_status in {"requires_auth", "unavailable"} or (
                        runtime_status == "enabled" and payload["usable"] is False
                    )
                if runtime_payload.get("error") and not payload.get("error"):
                    payload["error"] = runtime_payload.get("error")
                if runtime_payload.get("command") and not payload.get("command"):
                    payload["command"] = runtime_payload.get("command")
                if runtime_payload.get("tool_count") is not None:
                    payload["tool_count"] = int(runtime_payload.get("tool_count") or 0)
                if runtime_payload.get("tool_names") is not None:
                    payload["tool_names"] = list(runtime_payload.get("tool_names") or [])
                if runtime_payload.get("warning") and not payload.get("warning"):
                    payload["warning"] = runtime_payload.get("warning")
            enriched_core_servers.append(payload)
        boundary["core_mcp_servers"] = enriched_core_servers
        summary = dict(boundary.get("summary") or {})
        core_server_names = [
            str(item.get("server_name") or "").strip()
            for item in enriched_core_servers
            if str(item.get("server_name") or "").strip()
        ]
        enabled_servers = [
            name
            for name in core_server_names
            if str(runtime_by_name.get(name, {}).get("status") or "").strip() == "enabled"
            and runtime_by_name.get(name, {}).get("usable", True) is not False
        ]
        partial_failure_servers = sorted(
            name
            for name in core_server_names
            if str(runtime_by_name.get(name, {}).get("status") or "").strip() in {"requires_auth", "unavailable"}
            or (
                str(runtime_by_name.get(name, {}).get("status") or "").strip() == "enabled"
                and runtime_by_name.get(name, {}).get("usable") is False
            )
        )
        summary["configured_server_count"] = len(core_server_names) or len(configured_servers)
        summary["enabled_count"] = len(enabled_servers)
        summary["partial_failure_count"] = len(partial_failure_servers)
        summary["partial_failure_servers"] = partial_failure_servers
        boundary["summary"] = summary
        boundary["config"] = self.config.get_mcp_server_config_diagnostic()
        boundary["configured_server_names"] = configured_servers
        boundary["runtime_server_diagnostics"] = runtime_server_diagnostics
        return boundary

    def _session_exists(self, session_id: str) -> bool:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return False
        core_services = getattr(self, "core_services", None)
        if core_services is not None and getattr(core_services, "session", None) is not None:
            session_row = core_services.session.get_by_session_id(normalized_session_id)
            if session_row is not None:
                return True
        return self.session_manager.get_binding(normalized_session_id) is not None

    @staticmethod
    def _empty_reply_control_snapshot() -> dict[str, Any]:
        return {
            "active_turn": None,
            "pending_command": None,
            "last_command": {},
            "last_completed_command": {},
            "last_finish_reason": "",
            "checkpoint_count": 0,
            "latest_replay_input": None,
        }

    async def get_runtime_debug(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id is required")
        try:
            session_debug = self.brain.get_session_debug_snapshot(session_id)
        except ValueError:
            if not self._session_exists(session_id):
                raise
            session_debug = {
                "session_id": session_id,
                "route": {},
                "route_history": [],
                "context_plan": {},
                "memory_scope": {
                    "session_id": session_id,
                    "prefetched": False,
                    "found": False,
                    "profile_count": 0,
                    "fact_count": 0,
                    "recent_event_count": 0,
                },
                "authorization": {"recent_decisions": []},
                "object_operations": [],
                "reply_control": self._empty_reply_control_snapshot(),
                "checkpoints": [],
                "runtime_state": self.brain.get_session_runtime_snapshot(session_id) or {},
                "usage": self.brain.get_session_usage_snapshot(session_id) or {},
                "request": {},
                "compression": {},
                "last_failure": {},
                "updated_at": utcnow_iso(),
            }
        route_snapshot = dict(session_debug.get("route") or {})
        tool_debug_getter = getattr(self.tools_manager, "get_route_debug_snapshot", None)
        route_authorization = (
            tool_debug_getter(route_snapshot)
            if callable(tool_debug_getter)
            else {"visible_tools": [], "candidate_tools": [], "authorization_preview": []}
        )
        background_status = await self.heart.get_background_status()
        interaction_responses = getattr(self, "_interaction_responses", None)
        if interaction_responses is None and getattr(self, "event_bus", None) is not None:
            interaction_responses = InteractionResponseService(self.event_bus)
        confirmation_status = (
            interaction_responses.get_confirmation_status(session_id=session_id)
            if interaction_responses is not None
            else {"pending": False, "request_id": ""}
        )
        return {
            "session_id": session_id,
            "route": route_snapshot,
            "route_history": [
                dict(item)
                for item in session_debug.get("route_history", [])
                if isinstance(item, dict)
            ],
            "context_plan": dict(session_debug.get("context_plan") or {}),
            "memory_scope": dict(session_debug.get("memory_scope") or {}),
            "authorization": {
                "route_preview": route_authorization,
                "recent_decisions": [
                    dict(item)
                    for item in (session_debug.get("authorization") or {}).get("recent_decisions", [])
                    if isinstance(item, dict)
                ],
                "confirmation": {
                    "pending": bool(confirmation_status.get("pending", False)),
                    "request_id": str(confirmation_status.get("request_id", "") or ""),
                },
            },
            "object_operations": [
                dict(item)
                for item in session_debug.get("object_operations", [])
                if isinstance(item, dict)
            ],
            "reply_control": dict(session_debug.get("reply_control") or {}),
            "checkpoints": [
                dict(item)
                for item in session_debug.get("checkpoints", [])
                if isinstance(item, dict)
            ],
            "task_state": {
                "background": {
                    "schedule": dict(background_status.get("schedule") or {}),
                    "execution": dict(background_status.get("execution") or {}),
                    "delivery": dict(background_status.get("delivery") or {}),
                    "system": dict(background_status.get("system") or {}),
                    "heartbeat_idle": {
                        "enabled": bool(background_status.get("heartbeat_idle_poke_enabled")),
                        "eligible": bool(background_status.get("idle_poke_eligible")),
                        "after_seconds": int(background_status.get("heartbeat_idle_poke_after_seconds") or 0),
                        "cooldown_seconds": int(background_status.get("heartbeat_idle_poke_cooldown_seconds") or 0),
                        "context_compaction_enabled": bool(background_status.get("heartbeat_idle_context_compaction_enabled")),
                        "last_idle_poke_at": str(background_status.get("last_idle_poke_at") or ""),
                        "last_proactive_delivery_at": str(background_status.get("last_proactive_delivery_at") or ""),
                        "last_proactive_delivery_status": str(background_status.get("last_proactive_delivery_status") or ""),
                    },
                },
                "sources": list(background_status.get("background_status_sources") or []),
            },
            "runtime_state": dict(session_debug.get("runtime_state") or {}),
            "usage": dict(session_debug.get("usage") or {}),
            "request": dict(session_debug.get("request") or {}),
            "compression": dict(session_debug.get("compression") or {}),
            "last_failure": dict(session_debug.get("last_failure") or {}),
            "core_mcp": self.get_core_mcp_diagnostics(),
            "updated_at": str(session_debug.get("updated_at") or utcnow_iso()),
        }

    async def _emit_reply_control_event(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        target: EventTarget | None = None,
        turn_id: str = "",
    ) -> None:
        await self.speaker.emit(
            OutboundEvent(
                session_id=session_id,
                type=EventType.CONTROL.value,
                role="system",
                content=dict(payload or {}),
                source=self._control_source,
                target=target or EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                metadata={"turn_id": turn_id},
            )
        )
        await self._get_thread_delivery_bridge().publish_control_event(session_id, dict(payload or {}), turn_id=turn_id)

    async def _submit_reply_control_replay(
        self,
        *,
        session_id: str,
        input_info: dict[str, Any],
        source,
        target: EventTarget,
        is_boot: bool = False,
    ) -> None:
        replay_event = InboundEvent(
            session_id=session_id,
            type=EventType.MESSAGE.value,
            role=str(input_info.get("role") or "user"),
            content=input_info.get("content") or "",
            source=source,
            target=target,
            metadata=dict(input_info.get("metadata") or {}),
        )
        await self._session_execution_runtime.submit(
            session_id,
            SessionExecutionRequest(
                session_id=session_id,
                event=replay_event,
                input_info=dict(input_info or {}),
                target=target,
                is_boot=is_boot,
            ),
        )

    async def _handle_reply_control_event(self, event: InboundEvent) -> None:
        payload = event.content if isinstance(event.content, dict) else {}
        session_id = str(event.session_id or "").strip()
        action = str(payload.get("action") or "").strip().lower()
        guidance = str(payload.get("guidance") or "").strip()
        checkpoint_id = str(payload.get("checkpoint_id") or "").strip()
        turn_id = str(payload.get("turn_id") or "").strip()
        stream_id = str(payload.get("stream_id") or "").strip()
        target = self.session_manager.get_default_target(session_id)
        snapshot = self.brain.get_session_runtime_snapshot(session_id) or {}
        result = self.brain.request_reply_control(
            session_id,
            action=action,
            request_id=getattr(event, "event_id", ""),
            guidance=guidance,
            checkpoint_id=checkpoint_id,
            turn_id=turn_id,
            stream_id=stream_id,
        )
        result.setdefault("request_id", getattr(event, "event_id", ""))
        await self._emit_reply_control_event(
            session_id,
            result,
            target=target,
            turn_id=turn_id or str(snapshot.get("turn_id") or ""),
        )
        await self._emit_runtime_status_event(session_id, target, turn_id or str(snapshot.get("turn_id") or ""))
        if result.get("status") == "accepted":
            cancelled = await self._session_execution_runtime.cancel(session_id)
            if not cancelled:
                finalization = self.brain.finalize_reply_control(
                    session_id,
                    turn_id=turn_id or str(snapshot.get("turn_id") or ""),
                    interrupted=True,
                )
                if isinstance(finalization.get("control_result"), dict):
                    await self._emit_reply_control_event(
                        session_id,
                        dict(finalization.get("control_result") or {}),
                        target=target,
                        turn_id=turn_id or str(snapshot.get("turn_id") or ""),
                    )
                replay_input = finalization.get("replay_input")
                if isinstance(replay_input, dict):
                    await self._submit_reply_control_replay(
                        session_id=session_id,
                        input_info=replay_input,
                        source=event.source,
                        target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                    )
                await self._emit_runtime_status_event(session_id, target, turn_id or str(snapshot.get("turn_id") or ""))
            return
        replay_input = result.get("replay_input")
        if isinstance(replay_input, dict):
            await self._submit_reply_control_replay(
                session_id=session_id,
                input_info=replay_input,
                source=event.source,
                target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
            )

    @staticmethod
    def _runtime_error_payload_from_exception(exc: Exception) -> dict[str, Any]:
        if isinstance(getattr(exc, "runtime_error_payload", None), dict):
            payload = dict(getattr(exc, "runtime_error_payload"))
            payload.setdefault("occurred_at", utcnow_iso())
            return payload
        return RuntimeError.from_exception(
            exc,
            code="conversation_request_failed",
            category="runtime",
            retryable=False,
        ).model_dump(mode="json")

    async def get_background_status(self) -> dict[str, Any]:
        return await self.heart.get_background_status()

    async def get_runtime_usage(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id is required")
        snapshot = self.brain.get_session_usage_snapshot(session_id)
        if snapshot is not None and snapshot.get("usage_ready"):
            return snapshot

        resolver = getattr(self.mode_manager, "resolve_context_limit", None)
        if callable(resolver):
            context_limit_info = await resolver(
                provider_name=self._get_main_provider(),
                api_url=self.config.get("api_url") or "",
                model_name=self.config.get("model") or "",
                adapter=self.main_adapter,
            )
        else:
            context_limit_info = {
                "context_limit_tokens": int(self.main_adapter.get_context_limit(self.config.get("model") or "")),
                "context_limit_source": "fallback",
                "context_limit_model": self.config.get("model") or "",
                "context_limit_confidence": "low",
            }

        zero_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        }

        if snapshot is not None:
            merged_snapshot = dict(snapshot)
            merged_snapshot["usage_ready"] = False
            merged_snapshot["context_limit_tokens"] = int(
                merged_snapshot.get("context_limit_tokens") or context_limit_info.get("context_limit_tokens", 0) or 0
            )
            merged_snapshot["context_limit_source"] = str(
                merged_snapshot.get("context_limit_source") or context_limit_info.get("context_limit_source") or "fallback"
            )
            merged_snapshot["context_limit_model"] = str(
                merged_snapshot.get("context_limit_model") or context_limit_info.get("context_limit_model") or self.config.get("model") or ""
            )
            merged_snapshot["context_limit_confidence"] = str(
                merged_snapshot.get("context_limit_confidence")
                or context_limit_info.get("context_limit_confidence")
                or "low"
            )
            merged_snapshot.setdefault("context_breakdown", {
                "system": 0,
                "history": 0,
                "tool_history": 0,
                "memory_context": 0,
                "policy": 0,
                "current_input": 0,
                "proprioception": 0,
                "total": 0,
            })
            merged_snapshot.setdefault("last_turn_usage", dict(zero_usage))
            merged_snapshot.setdefault("session_totals", {**zero_usage, "turn_count": 0})
            merged_snapshot.setdefault("current_context_tokens_estimated", 0)
            merged_snapshot.setdefault("context_budget_breakdown", {})
            merged_snapshot.setdefault("usage_source", "estimated")
            merged_snapshot.setdefault("updated_at", utcnow_iso())
            return merged_snapshot

        if not self._session_exists(session_id):
            raise ValueError(f"Session not found: {session_id}")

        return {
            "session_id": session_id,
            "usage_ready": False,
            "context_limit_tokens": int(context_limit_info.get("context_limit_tokens", 0) or 0),
            "context_limit_source": str(context_limit_info.get("context_limit_source") or "fallback"),
            "context_limit_model": str(context_limit_info.get("context_limit_model") or self.config.get("model") or ""),
            "context_limit_confidence": str(context_limit_info.get("context_limit_confidence") or "low"),
            "current_context_tokens_estimated": 0,
            "context_budget_breakdown": {},
            "context_breakdown": {
                "system": 0,
                "history": 0,
                "tool_history": 0,
                "memory_context": 0,
                "policy": 0,
                "current_input": 0,
                "proprioception": 0,
                "total": 0,
            },
            "last_turn_usage": dict(zero_usage),
            "session_totals": {**zero_usage, "turn_count": 0},
            "usage_source": "estimated",
            "updated_at": utcnow_iso(),
        }

    @staticmethod
    def _scheduler_job_public_event_payload(
        *,
        event,
        run,
        thread_row=None,
        session_row=None,
        stream_id: str = "",
        turn_id: str = "",
    ) -> dict[str, Any]:
        created_at = getattr(event, "created_at", None)
        return {
            "event_id": str(getattr(event, "event_id", "") or ""),
            "run_id": str(getattr(run, "run_id", "") or ""),
            "thread_id": str(getattr(thread_row, "thread_id", "") or "") if thread_row is not None else "",
            "session_id": str(getattr(session_row, "session_id", "") or "") if session_row is not None else "",
            "seq": int(getattr(event, "seq", 0) or 0),
            "type": str(getattr(event, "type", "") or ""),
            "payload": dict(getattr(event, "payload", {}) or {}),
            "durable": bool(getattr(event, "durable", True)),
            "stream_id": str(stream_id or ""),
            "turn_id": str(turn_id or ""),
            "created_at": created_at.isoformat() if created_at is not None and hasattr(created_at, "isoformat") else "",
        }

    async def _publish_scheduler_run_event(
        self,
        *,
        event,
        run,
        thread_row=None,
        session_row=None,
        stream_id: str = "",
        turn_id: str = "",
    ) -> None:
        gateway = getattr(self, "gateway", None)
        if gateway is None or thread_row is None:
            return
        publisher = getattr(gateway, "publish_endpoint_run_event", None)
        if not callable(publisher):
            return
        await publisher(
            thread_id=str(getattr(thread_row, "thread_id", "") or ""),
            run_id=str(getattr(run, "run_id", "") or ""),
            event=self._scheduler_job_public_event_payload(
                event=event,
                run=run,
                thread_row=thread_row,
                session_row=session_row,
                stream_id=stream_id,
                turn_id=turn_id,
            ),
        )

    @staticmethod
    def _scheduler_tool_names(tools: list[dict]) -> list[str]:
        names: list[str] = []
        for tool in tools:
            name = str(tool.get("function", {}).get("name", "")).strip()
            if name and name not in names:
                names.append(name)
        return names

    @staticmethod
    def _filter_scheduler_tools(tools: list[dict], requested_names: Any) -> list[dict]:
        if not isinstance(requested_names, list):
            return tools
        allowlist = [str(item or "").strip() for item in requested_names if str(item or "").strip()]
        if not allowlist:
            return tools
        by_name = {
            str(tool.get("function", {}).get("name", "")).strip(): tool
            for tool in tools
            if str(tool.get("function", {}).get("name", "")).strip()
        }
        return [by_name[name] for name in allowlist if name in by_name]

    def _scheduler_workspace_row(self, job, *, workspace_id: str = "", run_template: dict[str, Any] | None = None):
        if self.core_domain is None:
            return None
        services = self.core_domain.services
        if getattr(job, "workspace_id", None) is not None:
            workspace = services.workspace.get_by_id(job.workspace_id)
            if workspace is not None:
                return workspace
        template = dict(run_template or {})
        workspace_key = str(template.get("workspace_id") or workspace_id or "personal").strip() or "personal"
        return services.workspace.get_by_workspace_id(workspace_key)

    def _ensure_scheduler_thread_session(
        self,
        job,
        *,
        workspace_row,
        run_template: dict[str, Any],
        delivery_policy: dict[str, Any],
    ):
        if self.core_domain is None or workspace_row is None:
            return None, None
        services = self.core_domain.services
        thread_row = None
        session_row = None
        session_id = str(run_template.get("session_id") or delivery_policy.get("session_id") or "").strip()
        if session_id:
            session_row = services.session.get_by_session_id(session_id)
            if session_row is not None:
                thread_row = services.thread.get_by_id(session_row.thread_id)
        thread_id = str(
            run_template.get("thread_id")
            or delivery_policy.get("thread_id")
            or (getattr(job, "meta", {}) or {}).get("thread_id")
            or ""
        ).strip()
        if thread_row is None and thread_id:
            thread_row = services.thread.get_by_thread_id(thread_id)

        create_thread = bool(run_template.get("create_thread", delivery_policy.get("create_thread", True)))
        if thread_row is None and create_thread:
            title = str(run_template.get("thread_title") or getattr(job, "name", "") or getattr(job, "job_id", "") or "Scheduled job").strip()
            thread_row = services.thread.create_thread(
                principal_id=self.core_domain.principal.id,
                workspace_id=workspace_row.id,
                title=f"Scheduled job: {title}",
            )
            if bool(getattr(job, "deletable", True)):
                metadata = dict(getattr(job, "meta", {}) or {})
                metadata["thread_id"] = thread_row.thread_id
                services.scheduler.update_job(job_id=str(getattr(job, "job_id", "") or ""), metadata=metadata)

        if session_row is None and thread_row is not None:
            scheduler_endpoint = services.endpoint.get_by_endpoint_id("core.scheduler")
            session_row = services.session.create_session(
                thread_id=thread_row.id,
                origin_endpoint_id=getattr(scheduler_endpoint, "id", None),
                workspace_id=workspace_row.id,
                status="active",
            )
        return thread_row, session_row

    def _scheduler_job_messages(self, job, *, run_template: dict[str, Any], manual: bool) -> list[dict[str, Any]]:
        raw_messages = run_template.get("messages")
        if isinstance(raw_messages, list) and raw_messages:
            return [dict(item) for item in raw_messages if isinstance(item, dict)]
        prompt = str(
            run_template.get("prompt")
            or run_template.get("content")
            or run_template.get("instruction")
            or getattr(job, "name", "")
            or getattr(job, "job_id", "")
            or "Run the scheduled job."
        ).strip()
        system_prompt = str(run_template.get("system_prompt") or "").strip() or (
            "[V4 Scheduled Workflow]\n"
            "You are executing a Core-owned Scheduled Workflow. Scheduler owns only the trigger timing; the workflow owns the action plan and output policy.\n"
            "Use assistant.progress_notice for progress when work is nontrivial. The final result must be returned as normal assistant text so Core can persist it as a Message.\n"
            "If delivery targets are configured, Core Delivery will send the persisted assistant Message after the run. Do not use send_endpoint_message to answer the originating scheduled job thread."
        )
        user_payload = {
            "job_id": str(getattr(job, "job_id", "") or ""),
            "name": str(getattr(job, "name", "") or ""),
            "kind": str(getattr(job, "kind", "") or ""),
            "action_ref": str(getattr(job, "action_ref", "") or "core.workflow.assistant_turn"),
            "workflow_type": str(run_template.get("workflow_type") or "assistant_run"),
            "manual_trigger": bool(manual),
            "scheduled_at": utcnow_iso(),
            "prompt": prompt,
            "parameters": dict(run_template.get("parameters") or {}),
            "output_policy": dict(run_template.get("output_policy") or {}),
            "metadata": dict(getattr(job, "meta", {}) or {}),
        }
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]

    async def _deliver_scheduler_message_targets(
        self,
        *,
        job,
        run,
        message,
        delivery_policy: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if self.core_domain is None:
            return []
        services = self.core_domain.services
        targets = delivery_policy.get("targets") if isinstance(delivery_policy.get("targets"), list) else []
        results: list[dict[str, Any]] = []
        for target in targets:
            if not isinstance(target, dict):
                continue
            endpoint_id = str(target.get("endpoint_id") or "").strip()
            address_id = str(target.get("address_id") or "").strip()
            address = None
            endpoint = None
            if address_id:
                address = services.endpoint_address.get_by_address_id(address_id)
                if address is None:
                    results.append({"address_id": address_id, "status": "missing"})
                    continue
                endpoint = services.endpoint.get_by_id(getattr(address, "endpoint_id", None))
                endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "")
            elif endpoint_id:
                endpoint = services.endpoint.get_by_endpoint_id(endpoint_id)
            if not endpoint_id:
                results.append({"status": "missing_endpoint", "address_id": address_id})
                continue
            if endpoint is None:
                results.append({"endpoint_id": endpoint_id, "status": "missing"})
                continue
            result = await services.delivery.deliver(
                target_endpoint=endpoint,
                target_address=address,
                message_type=str(target.get("message_type") or "message").strip() or "message",
                payload={
                    "job_id": str(getattr(job, "job_id", "") or ""),
                    "run_id": str(getattr(run, "run_id", "") or ""),
                    "message_id": str(getattr(message, "message_id", "") or "") if message is not None else "",
                    "role": "assistant",
                    "content": str(getattr(message, "content", "") or "") if message is not None else "",
                },
                offline_policy=str(target.get("offline_policy") or "store_and_retry"),
            )
            results.append({"endpoint_id": endpoint_id, "address_id": address_id, **dict(result or {})})
        return results

    @staticmethod
    def _scheduler_interval_seconds(job) -> int:
        trigger_config = getattr(job, "trigger_config", {}) or {}
        if not isinstance(trigger_config, dict):
            return 0
        try:
            interval = int(trigger_config.get("interval_seconds") or 0)
        except (TypeError, ValueError):
            return 0
        return interval if interval > 0 else 0

    async def _run_assistant_scheduled_job(self, job, *, workspace_id: str = "", manual: bool = False) -> dict[str, Any]:
        if self.core_domain is None:
            return {"triggered": False, "reason": "core_domain_unavailable", "job_id": str(getattr(job, "job_id", "") or "")}
        services = self.core_domain.services
        run_template = dict(getattr(job, "run_template", {}) or {})
        delivery_policy = dict(getattr(job, "delivery_policy", {}) or {})
        workspace_row = self._scheduler_workspace_row(job, workspace_id=workspace_id, run_template=run_template)
        if workspace_row is None:
            raise ValueError("workspace_id is required for triggering this scheduled job.")
        scheduler_actor = services.actor.get_by_actor_id("system.scheduler")
        if scheduler_actor is None:
            scheduler_actor = services.actor.ensure_actor(
                actor_id="system.scheduler",
                actor_type="system_scheduler",
                display_name="System Scheduler",
                permission_profile_id="profile.system_scheduler",
            )
        scheduler_endpoint = services.endpoint.get_by_endpoint_id("core.scheduler")
        thread_row, session_row = self._ensure_scheduler_thread_session(
            job,
            workspace_row=workspace_row,
            run_template=run_template,
            delivery_policy=delivery_policy,
        )
        run = services.run.create_run(
            workspace_id=workspace_row.id,
            thread_id=getattr(thread_row, "id", None),
            trigger_type="scheduled_job",
            origin_actor_id=scheduler_actor.id,
            origin_endpoint_id=getattr(scheduler_endpoint, "id", None),
            status="running",
            input={
                "job_id": str(getattr(job, "job_id", "") or ""),
                "manual": bool(manual),
                "action_ref": str(getattr(job, "action_ref", "") or "core.workflow.assistant_turn"),
                "run_template": run_template,
            },
            execution_policy=dict(getattr(job, "execution_policy", {}) or {}),
            delivery_policy=delivery_policy,
            metadata={"scheduled_job_id": str(getattr(job, "job_id", "") or ""), "manual": bool(manual)},
        )
        job_run = services.scheduled_job_run.create_job_run(
            job_id=getattr(job, "id", None),
            run_id=run.id,
            status="running",
            metadata={"manual": bool(manual), "job_id": str(getattr(job, "job_id", "") or "")},
        )
        stream_id = str(run_template.get("stream_id") or f"scheduler:{getattr(job, 'job_id', '')}").strip()
        turn_id = str(run_template.get("turn_id") or uuid4().hex).strip()
        started_event = services.run_event.append_event(
            run_id=run.id,
            thread_id=getattr(thread_row, "id", None),
            type="run.started",
            durable=True,
            payload={"trigger_type": "scheduled_job", "job_id": str(getattr(job, "job_id", "") or ""), "manual": bool(manual)},
        )
        await self._publish_scheduler_run_event(
            event=started_event,
            run=run,
            thread_row=thread_row,
            session_row=session_row,
            stream_id=stream_id,
            turn_id=turn_id,
        )

        tools = self._filter_scheduler_tools(self.tools_manager.get_scheduled_job_tools(), run_template.get("tool_bundle"))
        tool_names = self._scheduler_tool_names(tools)
        route_context = {
            "current_mode": str(run_template.get("mode") or "general"),
            "route_reason": "Scheduler triggered a Core-owned V4 scheduled job.",
            "source_profile": str(run_template.get("source_profile") or "scheduled_jobs"),
            "tool_bundle": tool_names,
            "mcp_servers": list(run_template.get("mcp_servers") or []),
            "task_routing": {
                "preferred_tool_key": str(run_template.get("preferred_tool_key") or "").strip(),
                "preferred_target_endpoint_ids": list(run_template.get("preferred_target_endpoint_ids") or []),
                "preferred_endpoint_provider_types": list(run_template.get("preferred_endpoint_provider_types") or []),
                "tool_target_routing_policy": str(run_template.get("tool_target_routing_policy") or "balanced").strip() or "balanced",
            },
        }
        session_id = str(getattr(session_row, "session_id", "") or f"system:scheduler:{getattr(job, 'job_id', '')}")
        token = bind_event_context(
            trace_id=str(getattr(run, "run_id", "") or ""),
            session_id=session_id,
            source=make_source(SourceKind.SYSTEM.value, "scheduler"),
            target=EventTarget(kind=TargetKind.INTERNAL.value),
            job_id=str(getattr(job, "job_id", "") or ""),
            **self._runtime_principal_context(),
        )
        try:
            max_rounds = int(run_template.get("max_rounds") or 0)
        except (TypeError, ValueError):
            max_rounds = 0
        if max_rounds == 6 and not bool(run_template.get("max_rounds_explicit")):
            max_rounds = 0
        try:
            try:
                result = await self.brain.run_background_turn(
                    api_url=self.config.get("api_url") or "",
                    api_key=self.config.get("api_key") or "",
                    model=self.config.get("model") or "",
                    messages=self._scheduler_job_messages(job, run_template=run_template, manual=manual),
                    tools=tools,
                    session_id=session_id,
                    source=make_source(SourceKind.SYSTEM.value, "scheduler"),
                    route_context=route_context,
                    adapter_options=Brain._build_adapter_options(self._build_model_options({})),
                    max_rounds=max_rounds,
                )
            except Exception as exc:
                logger.exception("Scheduled job %s failed during background turn", getattr(job, "job_id", ""))
                result = {
                    "status": "error",
                    "content": f"Error: {exc}",
                    "tool_names": [],
                    "result": {"error": self._runtime_error_payload_from_exception(exc)},
                }
        finally:
            reset_event_context(token)

        content = str(result.get("content") or "").strip()
        succeeded = str(result.get("status") or "").strip() == "ok" and not content.lower().startswith("error:")
        message = None
        if content and thread_row is not None:
            message = services.message.create_message(
                thread_id=thread_row.id,
                session_id=getattr(session_row, "id", None),
                run_id=run.id,
                role="assistant",
                content=content,
                status="completed" if succeeded else "failed",
                created_by_actor_id=scheduler_actor.id,
                origin_endpoint_id=getattr(scheduler_endpoint, "id", None),
                active_workspace_id=workspace_row.id,
                meta={
                    "job_id": str(getattr(job, "job_id", "") or ""),
                    "job_run_id": str(getattr(job_run, "job_run_id", "") or ""),
                    "turn_id": turn_id,
                    "stream_id": stream_id,
                },
            )
            conversation_version = getattr(services, "conversation_version", None)
            if conversation_version is not None:
                attached_message = conversation_version.attach_message_to_active_branch(
                    thread_row_id=thread_row.id,
                    message_row_id=message.id,
                )
                if attached_message is not None:
                    message = attached_message
            message_event = services.run_event.append_event(
                run_id=run.id,
                thread_id=thread_row.id,
                type="message.completed",
                durable=True,
                payload={
                    "thread_id": str(getattr(thread_row, "thread_id", "") or ""),
                    "session_id": str(getattr(session_row, "session_id", "") or ""),
                    "message": {
                        "message_id": message.message_id,
                        "thread_id": thread_row.thread_id,
                        "session_id": str(getattr(session_row, "session_id", "") or ""),
                        "role": message.role,
                        "content": message.content,
                        "status": message.status,
                        "channel": message.channel,
                        "created_at": message.created_at.isoformat() if getattr(message, "created_at", None) is not None else "",
                    },
                    "stream_id": stream_id,
                    "turn_id": turn_id,
                },
            )
            await self._publish_scheduler_run_event(
                event=message_event,
                run=run,
                thread_row=thread_row,
                session_row=session_row,
                stream_id=stream_id,
                turn_id=turn_id,
            )

        target_deliveries = await self._deliver_scheduler_message_targets(
            job=job,
            run=run,
            message=message,
            delivery_policy=delivery_policy,
        )
        final_status = "succeeded" if succeeded else "failed"
        completed_event = services.run_event.append_event(
            run_id=run.id,
            thread_id=getattr(thread_row, "id", None),
            type="run.completed",
            durable=True,
            payload={
                "status": final_status,
                "job_id": str(getattr(job, "job_id", "") or ""),
                "job_run_id": str(getattr(job_run, "job_run_id", "") or ""),
                "message_id": str(getattr(message, "message_id", "") or "") if message is not None else "",
                "tool_names": list(result.get("tool_names") or []),
                "deliveries": target_deliveries,
            },
        )
        services.run.update_status(
            run_row_id=run.id,
            status=final_status,
            output={
                "status": final_status,
                "message_id": str(getattr(message, "message_id", "") or "") if message is not None else "",
                "content": content,
                "result": dict(result.get("result") or {}),
            },
        )
        services.scheduled_job_run.update_status(
            job_run_id=getattr(job_run, "id", None),
            status=final_status,
            error={} if succeeded else {"message": content or "scheduled job failed", "result": dict(result or {})},
            metadata={"message_id": str(getattr(message, "message_id", "") or "") if message is not None else ""},
        )
        await self._publish_scheduler_run_event(
            event=completed_event,
            run=run,
            thread_row=thread_row,
            session_row=session_row,
            stream_id=stream_id,
            turn_id=turn_id,
        )
        return {
            "triggered": True,
            "job_id": str(getattr(job, "job_id", "") or ""),
            "job_run_id": str(getattr(job_run, "job_run_id", "") or ""),
            "run_id": str(getattr(run, "run_id", "") or ""),
            "thread_id": str(getattr(thread_row, "thread_id", "") or "") if thread_row is not None else "",
            "session_id": str(getattr(session_row, "session_id", "") or "") if session_row is not None else "",
            "message_id": str(getattr(message, "message_id", "") or "") if message is not None else "",
            "status": final_status,
            "actor_id": "system.scheduler",
        }

    async def _run_scheduler_job_once(self, job) -> None:
        job_id = str(getattr(job, "job_id", "") or "").strip()
        action_ref = str(getattr(job, "action_ref", "") or "").strip()
        if job_id == "system.heartbeat" or action_ref == "core.workflow.heartbeat":
            try:
                if self.core_domain is not None:
                    HeartbeatWorkflow(self.core_domain.services).run_once(workspace_id="personal")
            except Exception as exc:
                logger.warning("Failed to record system heartbeat scheduler run: %s", exc)
            await self.heart.heartbeat_processor(once=True)
            return
        await self._run_assistant_scheduled_job(job, manual=False)

    async def trigger_scheduled_job(self, *, job_id: str, workspace_id: str = "", manual: bool = True) -> dict[str, Any]:
        if self.core_domain is None:
            return {"triggered": False, "reason": "core_domain_unavailable", "job_id": str(job_id or "").strip()}
        job = self.core_domain.services.scheduler.get_job(str(job_id or "").strip())
        if job is None:
            return {"triggered": False, "reason": "not_found", "job_id": str(job_id or "").strip()}
        action_ref = str(getattr(job, "action_ref", "") or "").strip()
        if str(getattr(job, "job_id", "") or "") == "system.heartbeat" or action_ref == "core.workflow.heartbeat":
            result = HeartbeatWorkflow(self.core_domain.services).run_once(workspace_id=workspace_id or "personal")
            await self.heart.heartbeat_processor(once=True)
            return result
        return await self._run_assistant_scheduled_job(job, workspace_id=workspace_id, manual=manual)

    async def scheduler_processor(self):
        shutdown = self.event_bus.shutdown_event
        lease_owner = f"core.scheduler.{id(self)}"
        while True:
            if shutdown.is_set():
                break
            wait_seconds = 30
            try:
                if self.core_domain is None:
                    wait_seconds = 1
                else:
                    now = datetime.now(timezone.utc)
                    self.core_domain.services.scheduler.ensure_missing_next_fire_times(limit=100)
                    next_fire_at = _ensure_utc_datetime(self.core_domain.services.scheduler.next_fire_at())
                    if next_fire_at is not None:
                        wait_seconds = max(1, min(wait_seconds, int((next_fire_at - now).total_seconds()) + 1))
                    jobs = list(self.core_domain.services.scheduler.list_due_jobs(now=now, limit=50))
                    for job in jobs:
                        job_id = str(getattr(job, "job_id", "") or "").strip()
                        if not job_id or not bool(getattr(job, "enabled", True)):
                            continue
                        leased_job = self.core_domain.services.scheduler.acquire_due_lease(
                            job_id=job_id,
                            lease_owner=lease_owner,
                            lease_seconds=300,
                        )
                        if leased_job is None:
                            continue
                        try:
                            await self._run_scheduler_job_once(leased_job)
                            self.core_domain.services.scheduler.mark_fired(job_id=job_id, fired_at=datetime.now(timezone.utc))
                        except Exception:
                            self.core_domain.services.scheduler.release_lease(job_id=job_id)
                            raise
            except Exception as exc:
                logger.error("Scheduler tick failed: %s", exc)

            try:
                await asyncio.wait_for(shutdown.wait(), timeout=max(int(wait_seconds), 1))
                break
            except asyncio.TimeoutError:
                pass

    async def get_heartbeat_settings(self) -> dict[str, Any]:
        status = {}
        try:
            status = await self.heart.get_background_status()
        except Exception as exc:
            status = {"status_error": str(exc)}
        system_job = None
        try:
            if self.core_domain is not None:
                job = self.core_domain.services.scheduler.get_job("system.heartbeat")
                if job is not None:
                    system_job = {
                        "job_id": str(getattr(job, "job_id", "") or ""),
                        "kind": str(getattr(job, "kind", "") or ""),
                        "enabled": bool(getattr(job, "enabled", True)),
                        "deletable": bool(getattr(job, "deletable", True)),
                        "trigger_type": str(getattr(job, "trigger_type", "") or "interval"),
                        "trigger_config": dict(getattr(job, "trigger_config", {}) or {}),
                        "editable_fields": list(getattr(job, "editable_fields", []) or []),
                        "action_ref": str(getattr(job, "action_ref", "") or ""),
                    }
        except Exception as exc:
            system_job = {"error": str(exc)}
        return {
            "system_heartbeat": system_job or {},
            "settings": self.heart.get_idle_poke_settings_snapshot(),
            "status": {
                "idle_poke_eligible": bool(status.get("idle_poke_eligible")),
                "idle_poke_window_ready": bool(status.get("idle_poke_window_ready")),
                "idle_poke_cooldown_ready": bool(status.get("idle_poke_cooldown_ready")),
                "last_user_activity_at": str(status.get("last_user_activity_at") or ""),
                "recent_user_session_id": str(status.get("recent_user_session_id") or ""),
                "last_idle_poke_at": str(status.get("last_idle_poke_at") or ""),
                "last_proactive_delivery_at": str(status.get("last_proactive_delivery_at") or ""),
                "last_proactive_delivery_status": str(status.get("last_proactive_delivery_status") or ""),
                **({"status_error": str(status.get("status_error"))} if status.get("status_error") else {}),
            },
        }

    async def update_heartbeat_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        idle_allowed = {
            "heartbeat_idle_poke_enabled",
            "heartbeat_idle_poke_after_seconds",
            "heartbeat_idle_poke_cooldown_seconds",
            "heartbeat_idle_context_compaction_enabled",
        }
        scheduler_allowed = {
            "system_heartbeat_enabled",
            "system_heartbeat_interval_seconds",
        }
        normalized = {
            key: value
            for key, value in dict(updates or {}).items()
            if str(key or "").strip() in idle_allowed
        }
        rejected = sorted(
            str(key or "").strip()
            for key in dict(updates or {})
            if str(key or "").strip() and str(key or "").strip() not in idle_allowed | scheduler_allowed
        )
        result = await self.apply_config_updates(normalized) if normalized else {
            "applied_keys": [],
            "reloaded_components": [],
            "restart_required_keys": [],
            "warnings": [],
        }
        scheduler_updates: list[str] = []
        if self.core_domain is not None:
            scheduler = self.core_domain.services.scheduler
            if "system_heartbeat_enabled" in dict(updates or {}):
                scheduler.set_enabled(
                    job_id="system.heartbeat",
                    enabled=bool(dict(updates or {}).get("system_heartbeat_enabled")),
                )
                scheduler_updates.append("system_heartbeat_enabled")
            if "system_heartbeat_interval_seconds" in dict(updates or {}):
                interval = int(dict(updates or {}).get("system_heartbeat_interval_seconds") or 0)
                if interval <= 0:
                    raise ValueError("system_heartbeat_interval_seconds must be positive")
                scheduler.update_interval(job_id="system.heartbeat", interval_seconds=interval)
                scheduler_updates.append("system_heartbeat_interval_seconds")
        return {
            **result,
            "scheduler_applied_keys": scheduler_updates,
            "rejected_keys": rejected,
            "snapshot": await self.get_heartbeat_settings(),
        }

    async def get_model_reasoning_settings(self) -> dict[str, Any]:
        return {
            "scope": "global_default",
            "settings": {
                "thinking_enabled": self.config.get_bool("thinking_enabled", False),
                "thinking_effort": str(self.config.get("thinking_effort") or ""),
                "thinking_budget_tokens": self._safe_int(self.config.get("thinking_budget_tokens"), 0) or 0,
            },
            "allowed_efforts": ["low", "medium", "high", "xhigh", "max"],
            "notes": [
                "When thinking_enabled is false, thinking_effort and thinking_budget_tokens are cleared and omitted from provider requests."
            ],
        }

    async def update_model_reasoning_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"thinking_enabled", "thinking_effort", "thinking_budget_tokens"}
        requested = dict(updates or {})
        sanitized = {key: value for key, value in requested.items() if key in allowed}
        rejected = sorted(str(key) for key in requested if key not in allowed)
        if sanitized.get("thinking_enabled") is False:
            sanitized["thinking_effort"] = ""
            sanitized["thinking_budget_tokens"] = 0
        result = await self.apply_config_updates(sanitized) if sanitized else {
            "applied_keys": [],
            "reloaded_components": [],
            "restart_required_keys": [],
            "warnings": [],
        }
        return {
            **result,
            "rejected_keys": rejected,
            "snapshot": await self.get_model_reasoning_settings(),
        }

    async def emit_progress_notice(
        self,
        content: str,
        *,
        session_id: str = "",
        source=None,
        turn_id: str = "",
    ) -> dict[str, Any]:
        del source
        text = str(content or "").strip()
        if not text:
            return {"delivered": False, "reason": "empty_content"}
        context = get_event_context()
        resolved_session_id = str(session_id or context.get("session_id") or "").strip()
        if not resolved_session_id:
            return {"delivered": False, "reason": "session_unavailable"}
        snapshot = self.brain.get_session_runtime_snapshot(resolved_session_id) or {}
        status = str(snapshot.get("status") or "").strip()
        if status not in {RuntimeStatus.THINKING.value, RuntimeStatus.TOOL_CALLING.value}:
            return {
                "delivered": False,
                "reason": "progress_notice_not_allowed",
                "status": status,
            }
        context_turn_id = str(turn_id or context.get("turn_id") or "").strip()
        active_turn_id = str(snapshot.get("turn_id") or "").strip()
        if context_turn_id and active_turn_id and context_turn_id != active_turn_id:
            return {
                "delivered": False,
                "reason": "turn_mismatch",
                "turn_id": context_turn_id,
                "active_turn_id": active_turn_id,
            }
        bridge = self._get_thread_delivery_bridge()
        publisher = getattr(bridge, "publish_progress_notice", None)
        result = await publisher(
            resolved_session_id,
            content=text,
            turn_id=active_turn_id or context_turn_id,
            stream_id=str(snapshot.get("stream_id") or "").strip(),
        )
        if result.get("delivered"):
            logger.info(
                "Progress notice emitted",
                extra={
                    "session_id": resolved_session_id,
                    "turn_id": active_turn_id or context_turn_id,
                },
            )
        return result

    async def request_core_restart(
        self,
        password: str,
        *,
        reason: str = "",
        delay_seconds: int = 1,
        session_id: str = "",
        source=None,
    ) -> dict[str, Any]:
        del source
        expected = (
            os.getenv("MEETYOU_CORE_ADMIN_PASSWORD")
            or str(self.config.get("core_admin_password") or "").strip()
            or "123456"
        )
        if str(password or "") != expected:
            return {"ok": False, "accepted": False, "reason": "invalid_password"}
        requester = self._restart_requester
        if not callable(requester):
            return {"ok": False, "accepted": False, "reason": "restart_unsupported"}
        delay = max(0, min(int(delay_seconds or 0), 30))
        result = requester(reason=str(reason or "").strip(), delay_seconds=delay, session_id=str(session_id or "").strip())
        if asyncio.iscoroutine(result):
            result = await result
        payload = dict(result or {})
        payload.setdefault("ok", bool(payload.get("accepted")))
        payload.setdefault("accepted", bool(payload.get("ok")))
        payload.setdefault("delay_seconds", delay)
        return payload

    async def apply_config_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.config.begin_transaction()
        applied_keys: list[str] = []
        warnings: list[str] = []
        try:
            applied_keys, warnings = self.config.apply_updates(updates)
            if not applied_keys:
                return {
                    "applied_keys": [],
                    "reloaded_components": [],
                    "restart_required_keys": [],
                    "warnings": warnings,
                }

            self.config.reload()
            await self._sync_config_state_to_db()
            reloaded_components = await self._reload_config_components(applied_keys, warnings)
        except Exception as exc:
            if not applied_keys:
                raise
            rollback_error: Exception | None = None
            try:
                self.config.rollback_transaction(snapshot)
                self.config.reload()
                await self._reload_config_components(applied_keys, [])
            except Exception as restore_exc:
                rollback_error = restore_exc
            message = f"配置更新失败，已回滚: {exc}"
            if rollback_error is not None:
                raise ConfigError(f"{message}；回滚恢复失败: {rollback_error}") from exc
            raise ConfigError(message) from exc
        restart_required = sorted(_RESTART_REQUIRED_KEYS.intersection(applied_keys))
        if restart_required:
            warnings.append(
                "The following keys were written, but require a gateway restart to fully take effect: "
                + ", ".join(restart_required)
            )
        return {
            "applied_keys": applied_keys,
            "reloaded_components": reloaded_components,
            "restart_required_keys": restart_required,
            "warnings": warnings,
        }

    async def _reload_config_components(self, applied_keys: list[str], warnings: list[str]) -> list[str]:
        reloaded_components: set[str] = set()
        if _BRAIN_IMMEDIATE_KEYS.intersection(applied_keys):
            await self._refresh_brain_runtime()
            reloaded_components.add("brain")

        if _HEART_IMMEDIATE_KEYS.intersection(applied_keys):
            await self._refresh_heart_runtime()
            reloaded_components.add("heart")

        if _MEMORY_IMMEDIATE_KEYS.intersection(applied_keys):
            self.memory.refresh_config(self.config)
            reloaded_components.add("memory")

        if _MODE_IMMEDIATE_KEYS.intersection(applied_keys):
            await self._refresh_mode_runtime()
            reloaded_components.add("mode_manager")
        return sorted(reloaded_components)

    def build_endpoint_connection_prompt(
        self,
        *,
        endpoint_id: str,
        endpoint_type: str,
        display_name: str,
        transport_profile: str,
        workspace_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            base_prompt = str(
                self.config.get_prompt("endpoint_connected")
                or self.config.get_prompt("endpoint_connection")
                or ""
            ).strip()
        except Exception:
            base_prompt = ""
        workspace_list = [str(item).strip() for item in (workspace_ids or []) if str(item).strip()]
        context = {
            "trigger": "endpoint_connected",
            "endpoint_id": str(endpoint_id or "").strip(),
            "endpoint_type": str(endpoint_type or "").strip(),
            "display_name": str(display_name or "").strip(),
            "transport_profile": str(transport_profile or "").strip(),
            "workspace_ids": workspace_list,
        }
        workspace_text = "、".join(workspace_list) if workspace_list else "未声明工作区"
        prompt_parts = []
        if base_prompt:
            prompt_parts.append(base_prompt)
        prompt_parts.append(
            "现在有一个新的 Endpoint Provider 刚刚接入系统。\n"
            "请你像真实协作中的助手一样，主动发出第一条简短、自然、不生硬的连接消息，语气友好、专业，像在和一个刚上线的同事说话。\n"
            "这条消息需要做到三件事：1）表明你已经感知到它已连接；2）结合它的身份和工作区给出贴合上下文的欢迎或协作提示；3）说明你会等待它的能力快照或后续任务。\n"
            "不要输出 JSON、字段名清单、程序化枚举或过度模板化措辞。\n\n"
            f"本次接入的是 {context['display_name'] or context['endpoint_id'] or '未知 Endpoint'}"
            f"（endpoint_id={context['endpoint_id'] or 'unknown'}，类型={context['endpoint_type'] or 'unknown'}，"
            f"传输={context['transport_profile'] or 'unknown'}），当前声明的工作区有：{workspace_text}。"
        )
        prompt = "\n\n".join(prompt_parts).strip()
        return {
            "prompt_name": "endpoint_connected",
            "prompt": prompt,
            "context": context,
        }

    async def inject_endpoint_connection_event(
        self,
        *,
        endpoint_id: str,
        endpoint_type: str,
        display_name: str,
        transport_profile: str,
        workspace_ids: list[str] | None = None,
        connection_prompt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = (
            dict(connection_prompt)
            if isinstance(connection_prompt, dict) and connection_prompt
            else self.build_endpoint_connection_prompt(
                endpoint_id=endpoint_id,
                endpoint_type=endpoint_type,
                display_name=display_name,
                transport_profile=transport_profile,
                workspace_ids=workspace_ids,
            )
        )
        prompt_text = str(payload.get("prompt") or "").strip()
        if not prompt_text:
            return payload
        endpoint_key = str(endpoint_id or "").strip() or "unknown"
        endpoint_session_id = f"system:endpoint:{endpoint_key}"
        endpoint_target = make_target(
            TargetKind.INTERNAL.value,
            target_id=endpoint_key,
            trigger="endpoint_connected",
        )
        bridge_metadata = self._recent_thread_delivery_bridge_metadata(workspace_ids=workspace_ids)
        event = InboundEvent(
            session_id=endpoint_session_id,
            type=EventType.MESSAGE.value,
            role="user",
            content=prompt_text,
            source=make_source(
                SourceKind.SYSTEM.value,
                "endpoint_connection",
                display_name="Endpoint Connection",
                endpoint_id=endpoint_key,
            ),
            target=endpoint_target,
            metadata={
                "prompt_name": str(payload.get("prompt_name") or "endpoint_connected"),
                "trigger": "endpoint_connected",
                "endpoint_id": endpoint_key,
                "endpoint_type": str(endpoint_type or "").strip(),
                "display_name": str(display_name or "").strip(),
                "transport_profile": str(transport_profile or "").strip(),
                "workspace_ids": [str(item).strip() for item in (workspace_ids or []) if str(item).strip()],
                "transient": True,
                "connection_prompt": payload,
                "bridge_thread_id": str(bridge_metadata.get("thread_id") or ""),
                "bridge_workspace_id": str(bridge_metadata.get("workspace_id") or ""),
                "bridge_endpoint_id": str(bridge_metadata.get("endpoint_id") or ""),
                "bridge_session_id": str(bridge_metadata.get("bridged_session_id") or ""),
            },
        )
        bind_runtime_session = getattr(self.session_manager, "bind_runtime_session", None)
        if callable(bind_runtime_session):
            bind_runtime_session(
                make_source(SourceKind.SYSTEM.value, f"endpoint:{endpoint_key}", endpoint_id=endpoint_key),
                session_id=endpoint_session_id,
                default_target=endpoint_target,
                metadata={
                    "transient": True,
                    "trigger": "endpoint_connected",
                    "endpoint_id": endpoint_key,
                    "thread_id": str(bridge_metadata.get("thread_id") or ""),
                    "workspace_id": str(bridge_metadata.get("workspace_id") or ""),
                    "bridge_endpoint_id": str(bridge_metadata.get("endpoint_id") or ""),
                    "bridged_session_id": str(bridge_metadata.get("bridged_session_id") or ""),
                },
            )
        await self.event_bus.inbound_queue.put(event)
        logger.info(
            "Injected endpoint connection event into Core",
            extra={
                "context": {
                    "endpoint_id": endpoint_key,
                    "endpoint_type": str(endpoint_type or "").strip(),
                    "workspace_ids": [str(item).strip() for item in (workspace_ids or []) if str(item).strip()],
                    "trigger": "endpoint_connected",
                    "bridge_thread_id": str(bridge_metadata.get("thread_id") or ""),
                }
            },
        )
        return payload

    @staticmethod
    def _project_context_text(value: Any, *, limit: int = _PROJECT_CONTEXT_SOURCE_CONTENT_LIMIT) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized_limit = max(80, int(limit or _PROJECT_CONTEXT_SOURCE_CONTENT_LIMIT))
        if len(text) <= normalized_limit:
            return text
        return text[:normalized_limit].rstrip() + "\n[truncated]"

    def _build_project_context_metadata(self, thread_id: str) -> dict[str, Any]:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return {}
        domain = getattr(self, "core_domain", None)
        services = getattr(domain, "services", None)
        thread_service = getattr(services, "thread", None)
        project_service = getattr(services, "project", None)
        if thread_service is None or project_service is None:
            return {}
        try:
            thread = thread_service.get_by_thread_id(normalized_thread_id)
        except Exception:
            logger.warning("Failed to load thread for project context", exc_info=True)
            return {}
        project_row_id = getattr(thread, "project_id", None)
        if thread is None or project_row_id is None:
            return {}
        try:
            project = project_service.get_by_id(project_row_id)
        except Exception:
            logger.warning("Failed to load project for context", exc_info=True)
            return {}
        if project is None or str(getattr(project, "status", "") or "active") == "archived":
            return {}
        project_public_id = str(getattr(project, "project_id", "") or "").strip()
        if not project_public_id:
            return {}
        source_payloads: list[dict[str, Any]] = []
        try:
            sources = project_service.list_sources(
                project_id=project_public_id,
                limit=_PROJECT_CONTEXT_SOURCE_LIMIT,
            ) or []
        except Exception:
            logger.warning("Failed to load project sources for context", exc_info=True)
            sources = []
        for source in sources[:_PROJECT_CONTEXT_SOURCE_LIMIT]:
            content = self._project_context_text(getattr(source, "content", ""))
            title = str(getattr(source, "title", "") or "").strip()
            if not title and not content:
                continue
            source_payloads.append(
                {
                    "source_id": str(getattr(source, "source_id", "") or "").strip(),
                    "source_type": str(getattr(source, "source_type", "") or "").strip(),
                    "title": title,
                    "content_type": str(getattr(source, "content_type", "") or "").strip(),
                    "content": content,
                    "updated_at": str(getattr(source, "updated_at", "") or ""),
                }
            )
        return {
            "project_id": project_public_id,
            "project_title": str(getattr(project, "title", "") or "").strip(),
            "project_description": self._project_context_text(getattr(project, "description", ""), limit=800),
            "project_instructions": self._project_context_text(getattr(project, "instructions", ""), limit=1600),
            "project_sources": source_payloads,
            "project_context_loaded": True,
        }

    def _enrich_input_info_with_project_context(self, input_info: dict[str, Any]) -> None:
        if not isinstance(input_info, dict):
            return
        metadata = dict(input_info.get("metadata") or {})
        if bool(metadata.get("project_context_loaded")):
            return
        thread_id = str(metadata.get("thread_id") or "").strip()
        project_context = self._build_project_context_metadata(thread_id)
        if not project_context:
            return
        metadata.update(project_context)
        input_info["metadata"] = metadata

    def _resolve_session_execution_request(self, event: InboundEvent) -> SessionExecutionRequest | None:
        effective_session_id = event.session_id
        is_endpoint_connection_reply = False
        is_proactive_idle_poke = False
        if event.type == EventType.SIGNAL.value:
            if self._is_heartbeat_signal(event):
                signal_kind = str((event.metadata or {}).get("heartbeat_signal_kind") or "").strip().lower()
                is_proactive_idle_poke = signal_kind == "idle_poke" and bool((event.metadata or {}).get("heartbeat_direct_delivery"))
                delivery = self._recent_user_delivery(require_deliverable=not is_proactive_idle_poke)
                if delivery is None:
                    logger.info("Skipping heartbeat signal because no recent active session is available")
                    return None
                effective_session_id, target = delivery
            else:
                target = EventTarget(kind=TargetKind.CURRENT_SESSION.value)
            input_info = self._build_signal_input(event)
        else:
            event_metadata = dict(getattr(event, "metadata", {}) or {})
            is_endpoint_connection_reply = bool(
                event_metadata.get("trigger") == "endpoint_connected"
                and str(effective_session_id or "").strip().startswith("system:endpoint:")
            )
            input_info = {
                "role": event.role,
                "content": event.content,
                "metadata": event_metadata,
            }
            target = (
                EventTarget(kind=TargetKind.BROADCAST.value)
                if effective_session_id == "system:boot"
                else EventTarget(kind=TargetKind.INTERNAL.value, id=event_metadata.get("endpoint_id"))
                if is_endpoint_connection_reply
                else EventTarget(kind=TargetKind.CURRENT_SESSION.value)
            )
        return SessionExecutionRequest(
            session_id=effective_session_id,
            event=event,
            input_info=input_info,
            target=target,
            is_boot=effective_session_id == "system:boot" or is_endpoint_connection_reply,
            is_proactive_idle_poke=is_proactive_idle_poke,
        )

    async def _process_proactive_idle_poke(self, request: SessionExecutionRequest) -> None:
        metadata = dict(request.input_info.get("metadata") or {})
        api_key = self.config.get("api_key") or ""
        api_url = self.config.get("api_url") or ""
        model = self.config.get("model") or ""
        if bool(metadata.get("heartbeat_context_compaction_enabled")):
            try:
                compression = await self.brain.compact_session_for_idle_heartbeat(
                    request.session_id,
                    api_key=api_key,
                    api_url=api_url,
                    model=model,
                    provider_name=self._get_main_provider(),
                )
                logger.info(
                    "Idle heartbeat context compaction checked",
                    extra={
                        "session_id": request.session_id,
                        "triggered": bool((compression.get("compression") or {}).get("triggered")),
                        "reason": str((compression.get("compression") or {}).get("reason") or compression.get("reason") or ""),
                    },
                )
            except Exception as exc:
                logger.warning("Idle heartbeat context compaction failed for %s: %s", request.session_id, exc)

        message = self.brain.compose_idle_poke_message(
            request.session_id,
            observed_issue=str(request.event.content or ""),
        )
        turn_id = uuid4().hex
        await self.brain.record_proactive_assistant_message(
            request.session_id,
            message,
            metadata={
                "heartbeat_decision": metadata.get("heartbeat_decision", "notify"),
                "last_user_activity_at": metadata.get("last_user_activity_at", ""),
                "turn_id": turn_id,
            },
        )
        delivered = await self._deliver_background_message(
            request.session_id,
            request.target,
            message,
            activity_kind="idle_heartbeat",
        )
        self.heart.record_idle_poke_delivery(
            session_id=request.session_id,
            message=message,
            delivered=delivered,
        )
        logger.info(
            "Idle heartbeat proactive delivery handled",
            extra={
                "session_id": request.session_id,
                "target_kind": getattr(request.target, "kind", ""),
                "delivered": delivered,
            },
        )

    async def _process_session_execution(self, request: SessionExecutionRequest) -> None:
        stream_id = ""
        turn_id = uuid4().hex
        answer_chunks: list[str] = []
        self._enrich_input_info_with_project_context(request.input_info)
        metadata = dict(request.input_info.get("metadata") or {})
        source = request.event.source
        source_metadata = getattr(source, "metadata", {}) if source is not None else {}
        if not isinstance(source_metadata, dict):
            source_metadata = {}
        source_kind = str(getattr(source, "kind", "") or "").strip()
        source_id = str(getattr(source, "id", "") or "").strip()
        endpoint_id = str(metadata.get("endpoint_id") or source_metadata.get("endpoint_id") or "").strip()
        if not endpoint_id and source_kind in {"web", "feishu", "wechat", "cli"}:
            endpoint_id = source_id
        active_workspace_id = str(metadata.get("active_workspace_id") or metadata.get("workspace_id") or "").strip()
        token = bind_event_context(
            trace_id=getattr(request.event, "event_id", ""),
            session_id=request.session_id,
            turn_id=turn_id,
            source=request.event.source,
            target=request.target,
            source_kind=source_kind,
            source_id=source_id,
            endpoint_id=endpoint_id,
            active_workspace_id=active_workspace_id,
            workspace_id=active_workspace_id,
            thread_id=str(metadata.get("thread_id") or ""),
            **self._runtime_principal_context(),
        )
        reasoning_started = False
        reasoning_ended = False
        finish_reason = ""

        try:
            if request.is_proactive_idle_poke:
                await self._process_proactive_idle_poke(request)
                return

            api_key = self.config.get("api_key") or ""
            api_url = self.config.get("api_url") or ""
            model = self.config.get("model") or ""
            model_options = self._build_model_options(getattr(request.event, "metadata", {}))

            if request.event.type == EventType.MESSAGE.value and request.event.role == "user":
                await self._emit_pending_task_updates(request.session_id, request.target, request.event.source)

            stream_id = await self.speaker.emit_stream_start(
                request.session_id,
                self._brain_source,
                target=request.target,
                stream_channel="answer",
            )

            async def emit_tool_activity(phase: str, content: str, metadata: dict | None = None):
                metadata = metadata or {}
                await self.speaker.emit_status(
                    request.session_id,
                    content,
                    make_source(SourceKind.SYSTEM.value, "search"),
                    target=request.target,
                    metadata={
                        "activity_kind": metadata.get("activity_kind", "tool_chain"),
                        "search_phase": phase,
                        "activity_phase": phase,
                        "turn_id": turn_id,
                        **metadata,
                    },
                )
                await self._get_thread_delivery_bridge().publish_activity_event(
                    request.session_id,
                    activity={
                        "turn_id": turn_id,
                        "stream_id": stream_id,
                        "phase": phase,
                        "content": content,
                        "activity_kind": metadata.get("activity_kind", "tool_chain"),
                        "tool_names": list(metadata.get("tool_names") or []),
                        "metadata": {
                            "activity_kind": metadata.get("activity_kind", "tool_chain"),
                            "search_phase": phase,
                            "activity_phase": phase,
                            "turn_id": turn_id,
                            **metadata,
                        },
                    },
                    turn_id=turn_id,
                )

            async def phase_callback(status: str, detail: str = "", active_tools: list[str] | None = None):
                self.brain.set_session_runtime_state(
                    request.session_id,
                    status,
                    detail=detail,
                    active_tools=active_tools or [],
                    stream_id=stream_id,
                    turn_id=turn_id,
                )
                await self._emit_runtime_status_event(request.session_id, request.target, turn_id)

            self.brain.set_session_runtime_state(
                request.session_id,
                RuntimeStatus.THINKING.value,
                detail="Starting turn",
                active_tools=[],
                stream_id=stream_id,
                turn_id=turn_id,
                finish_reason="",
            )
            await self._emit_runtime_status_event(request.session_id, request.target, turn_id)

            initial_progress_notice = _initial_progress_notice_content(metadata)
            if initial_progress_notice:
                await self._get_thread_delivery_bridge().publish_progress_notice(
                    request.session_id,
                    content=initial_progress_notice,
                    turn_id=turn_id,
                    stream_id=stream_id,
                )

            async for output in self.brain.input_brain(
                request.session_id,
                request.input_info,
                api_key,
                api_url,
                model,
                provider_name=self._get_main_provider(),
                tool_activity_callback=emit_tool_activity,
                model_options=model_options,
                phase_callback=phase_callback,
            ):
                if not isinstance(output, BrainOutputEvent):
                    continue

                if output.type == "reasoning_text" and output.text:
                    if not reasoning_started:
                        await self._emit_reasoning_stream_event(
                            request.session_id,
                            stream_id,
                            StreamEventType.START.value,
                            "",
                            request.target,
                            turn_id,
                        )
                        reasoning_started = True
                    await self._emit_reasoning_stream_event(
                        request.session_id,
                        stream_id,
                        StreamEventType.CHUNK.value,
                        output.text,
                        request.target,
                        turn_id,
                    )
                elif output.type == "reasoning_end":
                    if reasoning_started and not reasoning_ended:
                        await self._emit_reasoning_stream_event(
                            request.session_id,
                            stream_id,
                            StreamEventType.END.value,
                            "",
                            request.target,
                            turn_id,
                        )
                        reasoning_ended = True
                elif output.type == "answer_text" and output.text:
                    answer_chunks.append(output.text)
                    await self._get_thread_delivery_bridge().publish_message_delta(
                        request.session_id,
                        stream_id=stream_id,
                        turn_id=turn_id,
                        delta=output.text,
                    )
                    if reasoning_started and not reasoning_ended:
                        await self._emit_reasoning_stream_event(
                            request.session_id,
                            stream_id,
                            StreamEventType.END.value,
                            "",
                            request.target,
                            turn_id,
                        )
                        reasoning_ended = True
                    await self.speaker.emit_stream_chunk(
                        request.session_id,
                        output.text,
                        self._brain_source,
                        stream_id,
                        target=request.target,
                        stream_channel="answer",
                    )
                elif output.type == "usage" and output.usage:
                    await self._emit_usage_event(request.session_id, output.usage, request.target, turn_id)

            if reasoning_started and not reasoning_ended:
                await self._emit_reasoning_stream_event(
                    request.session_id,
                    stream_id,
                    StreamEventType.END.value,
                    "",
                    request.target,
                    turn_id,
                )

            finish_reason = "completed"
            self.brain.set_session_runtime_state(
                request.session_id,
                RuntimeStatus.IDLE.value,
                detail="",
                active_tools=[],
                stream_id=stream_id,
                turn_id=turn_id,
                finish_reason=finish_reason,
            )
            await self._emit_runtime_status_event(request.session_id, request.target, turn_id)
            await self.speaker.emit_stream_end(
                request.session_id,
                self._brain_source,
                stream_id,
                target=request.target,
                stream_channel="answer",
                metadata={"turn_id": turn_id, "finish_reason": finish_reason},
            )
            await self._get_thread_delivery_bridge().persist_and_publish_assistant_message(
                request.session_id,
                content="".join(answer_chunks),
                stream_id=stream_id,
                turn_id=turn_id,
            )
        except asyncio.CancelledError:
            finalization = self.brain.finalize_reply_control(
                request.session_id,
                turn_id=turn_id,
                interrupted=True,
            )
            finish_reason = str(finalization.get("finish_reason") or "stopped")
            if reasoning_started and not reasoning_ended:
                await self._emit_reasoning_stream_event(
                    request.session_id,
                    stream_id,
                    StreamEventType.END.value,
                    "",
                    request.target,
                    turn_id,
                )
                reasoning_ended = True
            self.brain.set_session_runtime_state(
                request.session_id,
                RuntimeStatus.IDLE.value,
                detail="",
                active_tools=[],
                stream_id=stream_id,
                turn_id=turn_id,
                finish_reason=finish_reason,
            )
            await self._emit_runtime_status_event(request.session_id, request.target, turn_id)
            await self.speaker.emit_stream_end(
                request.session_id,
                self._brain_source,
                stream_id,
                target=request.target,
                stream_channel="answer",
                metadata={"turn_id": turn_id, "finish_reason": finish_reason},
            )
            control_result = finalization.get("control_result")
            if isinstance(control_result, dict):
                await self._emit_reply_control_event(
                    request.session_id,
                    dict(control_result or {}),
                    target=request.target,
                    turn_id=turn_id,
                )
            replay_input = finalization.get("replay_input")
            if isinstance(replay_input, dict):
                await self._submit_reply_control_replay(
                    session_id=request.session_id,
                    input_info=replay_input,
                    source=request.event.source,
                    target=request.target,
                    is_boot=request.is_boot,
                )
        except Exception as exc:
            logger.error("Brain processing error: %s\n%s", exc, traceback.format_exc())
            if bool(dict(request.input_info.get("metadata") or {}).get("transient")):
                self.brain.discard_trailing_transient_messages(request.session_id)
            error_payload = self._runtime_error_payload_from_exception(exc)
            if reasoning_started and not reasoning_ended:
                await self._emit_reasoning_stream_event(
                    request.session_id,
                    stream_id,
                    StreamEventType.END.value,
                    "",
                    request.target,
                    turn_id,
                )
                reasoning_ended = True
            self.brain.set_session_runtime_state(
                request.session_id,
                RuntimeStatus.ERROR.value,
                detail=str(error_payload.get("message") or str(exc)),
                active_tools=[],
                stream_id=stream_id,
                turn_id=turn_id,
                finish_reason="failed",
            )
            self.brain.mark_reply_turn_failed(request.session_id, turn_id=turn_id)
            await self._emit_runtime_status_event(request.session_id, request.target, turn_id)
            await self.speaker.emit_error(
                request.session_id,
                error_payload,
                self._brain_source,
                target=request.target,
                stream_id=stream_id,
                metadata={"turn_id": turn_id, "stream_channel": "answer"},
            )
        finally:
            reset_event_context(token)
            if request.is_boot:
                await self.brain.close_session(request.session_id)

    async def brain_processor(self):
        shutdown = self.event_bus.shutdown_event
        queue = self.event_bus.inbound_queue

        try:
            while True:
                get_task = asyncio.create_task(queue.get())
                shutdown_task = asyncio.create_task(shutdown.wait())
                done, pending = await asyncio.wait(
                    [get_task, shutdown_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if shutdown_task in done:
                    break

                event = get_task.result()
                if event.type == EventType.CONFIRM_RESPONSE.value:
                    resolved = self.event_bus.resolve_confirmation(
                        event.accepted,
                        request_id=event.request_id,
                        session_id=event.session_id,
                    )
                    if not resolved:
                        await self.speaker.emit_error(
                            event.session_id,
                            "Confirmation request expired or does not match the current session.",
                            make_source(SourceKind.SYSTEM.value, "confirm"),
                        )
                    continue

                if event.type == EventType.CONTROL.value:
                    try:
                        handled = await self._handle_control_event(event)
                        if not handled:
                            logger.warning("Unhandled control event: %s", getattr(event, "metadata", {}))
                    except Exception as exc:
                        logger.error("Control event processing failed: %s\n%s", exc, traceback.format_exc())
                    continue

                request = self._resolve_session_execution_request(event)
                if request is None:
                    continue
                await self._session_execution_runtime.submit(request.session_id, request)
        finally:
            await self._session_execution_runtime.shutdown()

    async def refresh_model_capabilities(self, *, provider_name: str = "", model_name: str = "") -> dict[str, Any]:
        provider = str(provider_name or self._get_main_provider()).strip().lower()
        model = str(model_name or self.config.get("model") or "").strip()
        resolver = get_model_capability_resolver()
        if not model:
            return {
                "provider": provider,
                "model": model,
                "source": "none",
                "old": {},
                "new": {},
                "trusted": False,
                "requires_manual_confirmation": True,
                "diagnostic": "model_name_required",
            }

        try:
            import aiohttp
        except Exception:
            aiohttp = None

        api_url = str(self.config.get("api_url") or "")
        api_key = str(self.config.get("api_key") or "")
        if provider == "anthropic":
            api_url = str(self.config.get("heartbeat_api_url") or api_url)
            api_key = str(self.config.get("heartbeat_api_key") or api_key)

        if aiohttp is None:
            return await resolver.refresh_model_capabilities(provider=provider, model=model, api_url=api_url, api_key=api_key)

        async with aiohttp.ClientSession() as session:
            return await resolver.refresh_model_capabilities(
                provider=provider,
                model=model,
                api_url=api_url,
                api_key=api_key,
                session=session,
            )


    async def setup(self):
        await setup_app_runtime(self)

    async def run(self, *, on_ready=None, on_stopping=None):
        await run_app_runtime(self, on_ready=on_ready, on_stopping=on_stopping)

    async def shutdown(self):
        await shutdown_app_runtime(self)
