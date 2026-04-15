"""
Application wiring and lifecycle management.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore[assignment]

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
from core.client_thread_bridge import ClientThreadBridge
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
from core.runtime_context import bind_event_context, get_event_context, reset_event_context
from core.session_actor import SessionActorRuntime
from core.session_manager import SessionManager
from core.speaker import Speaker
from core.status import RuntimeStatus, StatusManager, utcnow_iso
from core.tools_manager import ToolsManager
from gateway.api import FastAPIGateway
from platform_layer.detector import detect_platform
from sensors.feishu_input_adapter import FeishuInputAdapter
from sensors.feishu_output_adapter import FeishuOutputAdapter
from sensors.proprioceptor import Proprioceptor
from service_runtime.models import RuntimeError
from tools import system_tools
from tools.mcp import MCPManager
from tools.memory import Memory
from tools.task_manager import TaskManager

logger = logging.getLogger("meetyou.app")


@dataclass(slots=True)
class SessionExecutionRequest:
    session_id: str
    event: InboundEvent
    input_info: dict[str, Any]
    target: EventTarget
    is_boot: bool


def _normalize_task_summary(task_record: dict[str, Any]) -> str:
    return str(task_record.get("content") or task_record.get("summary") or task_record.get("task_key") or "scheduled task").strip()


def _task_time_context(task_record: dict[str, Any]) -> dict[str, Any]:
    timezone_name = str(task_record.get("timezone") or "UTC").strip() or "UTC"
    if timezone_name == "UTC" or ZoneInfo is None:
        zone = timezone.utc
    else:
        try:
            zone = ZoneInfo(timezone_name)
        except Exception:
            zone = timezone.utc
            timezone_name = "UTC"
    current_utc = datetime.now(timezone.utc).replace(microsecond=0)
    current_local = current_utc.astimezone(zone)

    def _to_local(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return str(value or "").strip() or None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(zone).isoformat(timespec="seconds")

    return {
        "current_time_utc": current_utc.isoformat().replace("+00:00", "Z"),
        "task_timezone": timezone_name,
        "current_time_local": current_local.isoformat(timespec="seconds"),
        "local_date": current_local.strftime("%Y-%m-%d"),
        "local_time": current_local.strftime("%H:%M:%S"),
        "weekday": current_local.strftime("%A"),
        "next_run_at_local": _to_local(task_record.get("next_run_at")),
        "due_at_local": _to_local(task_record.get("due_at")),
        "current_cycle_start_at_local": _to_local(task_record.get("current_cycle_start_at")),
        "current_cycle_end_at_local": _to_local(task_record.get("current_cycle_end_at")),
    }

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
    "agent_access_token",
    "cmd_policy_path",
    "database_url",
    "enable_feishu_bot",
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
}


class App:
    def __init__(self, health_getter=None, telemetry_recorder=None):
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
        )

        self.context_manager = ContextManager(self.memory, self.main_adapter, self.event_bus)
        self.tools_manager = ToolsManager(
            self.memory,
            self.context_manager,
            self.mcp_manager,
            system_tools,
            self.mode_manager,
            task_manager=self.task_manager,
        )
        self.brain = Brain(
            self.main_adapter,
            self.tools_manager,
            self.context_manager,
            self.event_bus,
            self.exception_router,
            mode_manager=self.mode_manager,
        )
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

        self.session_manager = SessionManager()
        self.heart.set_session_manager(self.session_manager)
        self.speaker = Speaker(self.session_manager)
        self.gateway: FastAPIGateway | None = None
        self.core_domain = None
        self.db_engine = None
        self.db_session_factory = None
        self.core_services = None
        self.feishu_input: FeishuInputAdapter | None = None
        self.feishu_output: FeishuOutputAdapter | None = None
        self.proprioceptor = Proprioceptor(self.platform, self.context_manager, self.event_bus)
        self._health_getter = health_getter
        self._telemetry_recorder = telemetry_recorder
        if self._telemetry_recorder is not None:
            self.tools_manager.set_execution_observer(self._telemetry_recorder.observe_tool_result)

        self._brain_source = make_source(SourceKind.SYSTEM.value, "brain")
        self._runtime_source = make_source(SourceKind.SYSTEM.value, "runtime")
        self._usage_source = make_source(SourceKind.SYSTEM.value, "usage")
        self._control_source = make_source(SourceKind.SYSTEM.value, "reply_control")
        self._session_execution_runtime = SessionActorRuntime(self._process_session_execution)
        self._confirm_approval_requests: dict[str, dict[str, Any]] = {}
        self._interaction_responses = InteractionResponseService(self.event_bus)
        self._client_thread_bridge = ClientThreadBridge(
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

    def _get_client_thread_bridge(self) -> ClientThreadBridge:
        bridge = getattr(self, "_client_thread_bridge", None)
        if isinstance(bridge, ClientThreadBridge):
            return bridge
        bridge = ClientThreadBridge(
            gateway_getter=lambda: getattr(self, "gateway", None),
            core_services_getter=lambda: getattr(self, "core_services", None),
        )
        self._client_thread_bridge = bridge
        return bridge

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

        thinking = {
            "enabled": thinking_override.get("enabled", default_enabled),
            "effort": thinking_override.get("effort", default_effort),
            "budget_tokens": self._safe_int(
                thinking_override.get("budget_tokens"),
                default_budget,
            ),
        }
        return {"thinking": thinking}

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
        await self._get_client_thread_bridge().publish_runtime_state(session_id, snapshot, turn_id=metadata["turn_id"])

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
        await self._get_client_thread_bridge().publish_runtime_usage(session_id, payload)

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
        await self._get_client_thread_bridge().publish_reasoning_event(
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
        await self._get_client_thread_bridge().publish_confirm_request(event, approval_context=approval_context)

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
                client_id = str(payload.get("client_id") or "").strip()
                if client_id:
                    context["client_id"] = client_id
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
        await self._get_client_thread_bridge().publish_confirm_resolution(payload, approval_context=approval_context)
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
            execution_target="core_only",
            title=operation_title,
            requested_by_client_id=session_row.client_id,
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
            decided_by_client_id = None
            decided_by_client_key = str(context.get("client_id") or "").strip()
            if decided_by_client_key:
                decided_by_client = core_services.client.get_by_client_id(decided_by_client_key)
                decided_by_client_id = getattr(decided_by_client, "id", None)
            approval = core_services.approval.decide_approval(
                approval_id=approval.approval_id,
                decision="approve" if accepted else "reject",
                reason=reason,
                decided_by_client_id=decided_by_client_id,
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
        await self._get_client_thread_bridge().publish_human_input_request(event)

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
        await self._get_client_thread_bridge().publish_human_input_resolution(payload)

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

    def _register_feishu_broadcast_targets(self):
        raw_chat_ids = self.config.get("feishu_broadcast_chat_ids") or []
        if isinstance(raw_chat_ids, str):
            chat_ids = [item.strip() for item in raw_chat_ids.split(",") if item.strip()]
        elif isinstance(raw_chat_ids, list):
            chat_ids = [str(item).strip() for item in raw_chat_ids if str(item).strip()]
        else:
            chat_ids = []

        default_chat_id = self.config.get("feishu_default_chat_id") or ""
        if default_chat_id:
            chat_ids.append(str(default_chat_id).strip())

        for chat_id in list(dict.fromkeys(chat_ids)):
            source = make_source(SourceKind.FEISHU.value, chat_id)
            self.session_manager.bind_runtime_session(
                source,
                session_id=f"feishu:chat:{chat_id}",
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

    async def _refresh_mode_runtime(self):
        self.mode_manager = AssistantModeManager(self.config)
        tools_manager_setter = getattr(self.tools_manager, "set_mode_manager", None)
        if callable(tools_manager_setter):
            tools_manager_setter(self.mode_manager)
        brain_setter = getattr(self.brain, "set_mode_manager", None)
        if callable(brain_setter):
            brain_setter(self.mode_manager)

    def _scheduled_job_route_context(self, task_record: dict[str, Any] | None = None) -> tuple[list[dict], dict[str, Any]]:
        tools = self.tools_manager.get_scheduled_job_tools()
        task_record = task_record or {}
        return tools, {
            "current_mode": "scheduled_task",
            "route_reason": "Scheduler claimed an assistant-owned background task.",
            "source_profile": "scheduled_tasks",
            "task_routing": {
                "preferred_capability_ref": str(task_record.get("preferred_capability_ref") or "").strip(),
                "preferred_agent_ids": list(task_record.get("preferred_agent_ids") or []),
                "preferred_agent_types": list(task_record.get("preferred_agent_types") or []),
                "agent_routing_policy": str(task_record.get("agent_routing_policy") or "balanced").strip() or "balanced",
            },
            "tool_bundle": [
                str(tool.get("function", {}).get("name", "")).strip()
                for tool in tools
                if str(tool.get("function", {}).get("name", "")).strip()
            ],
            "mcp_servers": [],
        }

    def _task_delivery(self, task_record: dict[str, Any]) -> tuple[str, EventTarget]:
        delivery = task_record.get("delivery_target") if isinstance(task_record.get("delivery_target"), dict) else {}
        session_id = str(delivery.get("session_id") or task_record.get("origin_session_id") or "").strip()
        return session_id, EventTarget(
            kind=str(delivery.get("kind") or TargetKind.CURRENT_SESSION.value),
            id=str(delivery.get("id") or ""),
        )

    def _task_source(self, task_record: dict[str, Any]):
        delivery = task_record.get("delivery_target") if isinstance(task_record.get("delivery_target"), dict) else {}
        source_kind = str(delivery.get("source_kind") or SourceKind.SYSTEM.value)
        source_id = str(delivery.get("source_id") or task_record.get("scope", {}).get("user_id") or "")
        return make_source(source_kind, source_id)

    def _task_operation_context(self, task_record: dict[str, Any]) -> tuple[object | None, object | None, object | None]:
        core_services = getattr(self, "core_services", None)
        if core_services is None:
            return None, None, None
        session_id, _ = self._task_delivery(task_record)
        if not session_id:
            return None, None, None
        session_row = core_services.session.get_by_session_id(session_id)
        if session_row is None:
            return None, None, None
        thread_row = core_services.thread.get_by_id(session_row.thread_id)
        workspace_row = core_services.workspace.get_by_id(session_row.workspace_id)
        if thread_row is None or workspace_row is None:
            return None, None, None
        return session_row, thread_row, workspace_row

    async def _publish_task_operation_update(
        self,
        operation,
        *,
        thread_id: str,
        phase: str = "",
        detail: str = "",
        error: dict[str, Any] | None = None,
    ) -> None:
        await self._get_client_thread_bridge().publish_task_operation_update(
            operation,
            thread_id=thread_id,
            phase=phase,
            detail=detail,
            error=error,
        )

    async def _create_scheduled_task_operation(self, task_record: dict[str, Any], *, operation_type: str, title: str):
        core_services = getattr(self, "core_services", None)
        if core_services is None:
            return None, None
        session_row, thread_row, workspace_row = self._task_operation_context(task_record)
        if session_row is None or thread_row is None or workspace_row is None:
            return None, None
        operation = core_services.operation.create_operation(
            thread_id=thread_row.id,
            workspace_id=workspace_row.id,
            operation_type=operation_type,
            execution_target="core_only",
            title=title,
            requested_by_client_id=session_row.client_id,
            requested_by_session_id=session_row.id,
            status="running",
            metadata={
                "workspace_id": getattr(workspace_row, "workspace_id", ""),
                "task_key": str(task_record.get("task_key") or ""),
                "task_summary": _normalize_task_summary(task_record),
                "preferred_capability_ref": str(task_record.get("preferred_capability_ref") or ""),
                "preferred_agent_ids": list(task_record.get("preferred_agent_ids") or []),
                "preferred_agent_types": list(task_record.get("preferred_agent_types") or []),
                "agent_routing_policy": str(task_record.get("agent_routing_policy") or "balanced") or "balanced",
                "source": "scheduled_task",
            },
        )
        remember_operation = getattr(self.task_manager, "remember_task_operation", None)
        if callable(remember_operation):
            await remember_operation(
                str(task_record.get("task_key") or ""),
                operation_id=operation.operation_id,
                status="running",
            )
        await self._publish_task_operation_update(
            operation,
            thread_id=thread_row.thread_id,
            phase="running",
            detail="Scheduled task execution started.",
        )
        return operation, thread_row.thread_id

    async def _ensure_scheduled_task_operation(
        self,
        task_record: dict[str, Any],
        *,
        operation_id: str = "",
        operation_type: str,
        title: str,
    ):
        normalized_operation_id = str(operation_id or "").strip()
        core_services = getattr(self, "core_services", None)
        if normalized_operation_id and core_services is not None:
            existing = core_services.operation.get_by_operation_id(normalized_operation_id)
            if existing is not None:
                existing = core_services.operation.update_status(
                    operation_id=existing.id,
                    status="running",
                    metadata={"scheduler_precreated": True},
                ) or existing
                remember_operation = getattr(self.task_manager, "remember_task_operation", None)
                if callable(remember_operation):
                    await remember_operation(
                        str(task_record.get("task_key") or ""),
                        operation_id=existing.operation_id,
                        status=existing.status,
                    )
                session_row, thread_row, _ = self._task_operation_context(task_record)
                thread_key = getattr(thread_row, "thread_id", "") if thread_row is not None else ""
                if thread_key:
                    await self._publish_task_operation_update(
                        existing,
                        thread_id=thread_key,
                        phase="running",
                        detail="Scheduled task execution started.",
                    )
                return existing, thread_key
        return await self._create_scheduled_task_operation(
            task_record,
            operation_type=operation_type,
            title=title,
        )

    def _can_deliver_task_update(self, session_id: str, target: EventTarget) -> bool:
        resolved_target = target
        if target.kind == TargetKind.CURRENT_SESSION.value and session_id:
            resolved_target = self.session_manager.get_default_target(session_id)
        if resolved_target.kind == TargetKind.WEB.value:
            return bool(self.gateway is not None and session_id and self.gateway.ws_manager.has_session(session_id))
        if resolved_target.kind == TargetKind.FEISHU.value:
            return bool(resolved_target.id)
        if resolved_target.kind == TargetKind.CLI.value:
            return bool(session_id)
        return False

    async def _emit_task_update(self, task_record: dict[str, Any], message: str) -> bool:
        session_id, target = self._task_delivery(task_record)
        if not session_id or not self._can_deliver_task_update(session_id, target):
            return False
        await self.speaker.emit_text(
            session_id,
            message,
            self._runtime_source,
            target=target,
            metadata={"activity_kind": "scheduled_task"},
        )
        return True

    async def _emit_pending_task_updates(self, session_id: str, target: EventTarget, source) -> None:
        peek_pending = getattr(self.task_manager, "peek_pending_delivery_messages", None)
        if callable(peek_pending):
            pending = await peek_pending(source=source)
        else:
            pending = await self.task_manager.collect_pending_delivery_messages(source=source)
        if not pending:
            return
        lines = ["以下是之前未送达的后台更新补发："]
        for item in pending[:6]:
            kind = str(item.get("kind") or "").strip()
            prefix = "提醒补发" if kind == "task_due" else "结果补发" if kind == "task_completion" else "后台补发"
            lines.append(f"- {prefix}：{item['message']}")
        await self.speaker.emit_text(
            session_id,
            "\n".join(lines),
            self._runtime_source,
            target=target,
        )
        acknowledge_pending = getattr(self.task_manager, "acknowledge_pending_delivery_messages", None)
        if callable(acknowledge_pending):
            await acknowledge_pending(
                source=source,
                event_ids=[
                    str(item.get("event_id") or "").strip()
                    for item in pending
                    if str(item.get("event_id") or "").strip()
                ],
            )

    def _recent_user_delivery(self) -> tuple[str, EventTarget] | None:
        list_recent = getattr(self.session_manager, "list_recent_bindings", None)
        if not callable(list_recent):
            return None
        for binding in list_recent():
            session_id = str(getattr(binding, "session_id", "") or "").strip()
            if not session_id or session_id.startswith("system:"):
                continue
            source = getattr(binding, "source", None)
            source_kind = str(getattr(source, "kind", "") or "").strip().lower()
            if source_kind not in {SourceKind.WEB.value, SourceKind.FEISHU.value, SourceKind.CLI.value}:
                continue
            target = getattr(binding, "default_target", None)
            if target is None:
                continue
            resolved_target = EventTarget(
                kind=str(getattr(target, "kind", "") or ""),
                id=str(getattr(target, "id", "") or ""),
                metadata=dict(getattr(target, "metadata", {}) or {}),
            )
            if self._can_deliver_task_update(session_id, resolved_target):
                return session_id, resolved_target
        return None


    def _recent_client_thread_bridge_metadata(self, *, workspace_ids: list[str] | None = None) -> dict[str, str]:
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
            if source_kind not in {SourceKind.WEB.value, SourceKind.FEISHU.value, SourceKind.CLI.value}:
                continue
            metadata = dict(getattr(binding, "metadata", {}) or {})
            thread_id = str(metadata.get("thread_id") or "").strip()
            if not thread_id:
                continue
            candidate = {
                "thread_id": thread_id,
                "workspace_id": str(metadata.get("workspace_id") or "").strip(),
                "client_id": str(metadata.get("client_id") or "").strip(),
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

    def _control_claim_valid(self, task_key: str, claim_token: str) -> bool:
        normalized_claim_token = str(claim_token or "").strip()
        if not normalized_claim_token:
            return True
        checker = getattr(self.task_manager, "has_current_claim", None)
        if not callable(checker):
            return True
        return bool(checker(task_key, normalized_claim_token))

    async def _handle_scheduled_reminder(self, task_key: str, claim_token: str = "", trace_id: str = "", operation_id: str = ""):
        if not self._control_claim_valid(task_key, claim_token):
            return
        task_record = self.task_manager.get_task_by_key(task_key)
        if task_record is None:
            return
        task_operation, operation_thread_id = await self._ensure_scheduled_task_operation(
            task_record,
            operation_id=operation_id,
            operation_type="scheduled_reminder_run",
            title=f"Scheduled Reminder: {_normalize_task_summary(task_record)}",
        )
        message = (
            f"Scheduled reminder: {_normalize_task_summary(task_record)}"
            f"\nDue: {task_record.get('next_run_at') or task_record.get('due_at') or 'now'}"
        )
        should_notify = str(task_record.get("notify_policy") or "on_due") != "silent"
        delivered = True
        token = bind_event_context(
            trace_id=trace_id,
            session_id=self._task_delivery(task_record)[0] or f"system:task:{task_key}",
            source=self._task_source(task_record),
            target=self._task_delivery(task_record)[1],
            job_id=task_key,
        )
        try:
            if should_notify:
                delivered = await self._emit_task_update(task_record, message)
            if task_operation is not None:
                core_services = getattr(self, "core_services", None)
                if core_services is not None:
                    task_operation = core_services.operation.update_status(
                        operation_id=task_operation.id,
                        status="succeeded",
                        result_summary=message,
                        metadata={
                            "delivered": bool(delivered or not should_notify),
                            "delivery_pending": bool(should_notify and not delivered),
                        },
                    ) or task_operation
                    remember_operation = getattr(self.task_manager, "remember_task_operation", None)
                    if callable(remember_operation):
                        await remember_operation(
                            task_key,
                            operation_id=task_operation.operation_id,
                            status=task_operation.status,
                        )
                    if operation_thread_id:
                        await self._publish_task_operation_update(
                            task_operation,
                            thread_id=operation_thread_id,
                            phase="completed",
                            detail=message,
                        )
            await self.task_manager.complete_due_notification(
                task_key,
                summary=message,
                delivered=(delivered or not should_notify),
                runtime_source="app.scheduled_reminder",
                delivery_channel="task_update",
            )
        finally:
            reset_event_context(token)

    async def _handle_scheduled_task(self, task_key: str, claim_token: str = "", trace_id: str = "", operation_id: str = ""):
        if not self._control_claim_valid(task_key, claim_token):
            return
        task_record = self.task_manager.get_task_by_key(task_key)
        if task_record is None:
            return
        task_operation, operation_thread_id = await self._ensure_scheduled_task_operation(
            task_record,
            operation_id=operation_id,
            operation_type="scheduled_task_run",
            title=f"Scheduled Task: {_normalize_task_summary(task_record)}",
        )

        tools, route_context = self._scheduled_job_route_context(task_record)
        summary = _normalize_task_summary(task_record)
        system_prompt = (
            "[Scheduled Job Mode]\n"
            "You are executing an assistant-owned scheduled background job, not a user TODO.\n"
            "Use only the allowed tools.\n"
            "Do the smallest reliable amount of work needed to complete the scheduled task.\n"
            "When the business task is truly complete, call manage_scheduled_tasks with action=complete and the exact task_key.\n"
            "If the work ran but the business task is not fully complete yet, do not mark it complete.\n"
            "Never use destructive or external-send behavior.\n"
            "Return a concise execution summary in plain text."
        )
        user_payload = {
            "task": task_record,
            "current_time": utcnow_iso(),
            "time_context": _task_time_context(task_record),
            "orchestration": task_record.get("orchestration") if isinstance(task_record.get("orchestration"), dict) else {},
            "routing": {
                "preferred_capability_ref": str(task_record.get("preferred_capability_ref") or "").strip(),
                "preferred_agent_ids": list(task_record.get("preferred_agent_ids") or []),
                "preferred_agent_types": list(task_record.get("preferred_agent_types") or []),
                "agent_routing_policy": str(task_record.get("agent_routing_policy") or "balanced").strip() or "balanced",
            },
        }
        task_source = self._task_source(task_record)
        task_session_id, task_target = self._task_delivery(task_record)
        token = bind_event_context(
            trace_id=trace_id,
            session_id=task_session_id or f"system:task:{task_key}",
            source=task_source,
            target=task_target,
            job_id=task_key,
        )
        try:
            result = await self.brain.run_background_turn(
                api_url=self.config.get("api_url") or "",
                api_key=self.config.get("api_key") or "",
                model=self.config.get("model") or "",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                tools=tools,
                session_id=task_session_id or f"system:task:{task_key}",
                source=task_source,
                route_context=route_context,
                adapter_options=Brain._build_adapter_options(self._build_model_options({})),
            )
        finally:
            reset_event_context(token)

        content = str(result.get("content") or "").strip() or f"Scheduled task completed: {summary}"
        completed_task_keys = {
            str(item).strip()
            for item in (result.get("completed_task_keys") or [])
            if str(item).strip()
        }
        completed_by_brain = task_key in completed_task_keys
        succeeded = result.get("status") == "ok" and not content.lower().startswith("error:")
        error_payload = result.get("error") if isinstance(result.get("error"), dict) else {}
        user_message = (
            f"Scheduled task completed: {summary}\n{content}"
            if succeeded and completed_by_brain
            else f"Scheduled task ran successfully and is awaiting completion confirmation: {summary}\n{content}"
            if succeeded
            else f"Scheduled task failed: {summary}\n{content}"
        )
        should_notify = str(task_record.get("notify_policy") or "on_completion") == "on_completion"
        delivered = True
        if should_notify:
            delivered = await self._emit_task_update(task_record, user_message)
        if task_operation is not None:
            core_services = getattr(self, "core_services", None)
            if core_services is not None:
                task_operation = core_services.operation.update_status(
                    operation_id=task_operation.id,
                    status="succeeded" if succeeded else "failed",
                    result_summary=user_message,
                    metadata={
                        "completed_by_brain": completed_by_brain,
                        "delivered": bool(delivered or not should_notify),
                        "last_error": error_payload if isinstance(error_payload, dict) else {},
                    },
                ) or task_operation
                remember_operation = getattr(self.task_manager, "remember_task_operation", None)
                if callable(remember_operation):
                    await remember_operation(
                        task_key,
                        operation_id=task_operation.operation_id,
                        status=task_operation.status,
                    )
                if operation_thread_id:
                    await self._publish_task_operation_update(
                        task_operation,
                        thread_id=operation_thread_id,
                        phase="completed" if succeeded else "failed",
                        detail=user_message,
                        error=error_payload if not succeeded and isinstance(error_payload, dict) else None,
                    )
        await self.task_manager.complete_task_run(
            task_key,
            succeeded=succeeded,
            summary=user_message,
            delivered=(delivered or not should_notify),
            completed=completed_by_brain,
            failure_category=str(error_payload.get("category") or "retryable"),
            failure_retryable=error_payload.get("retryable"),
            failure_code=str(error_payload.get("code") or "scheduled_task_run_failed"),
            failure_details=error_payload.get("details") if isinstance(error_payload.get("details"), dict) else {},
            runtime_source="app.scheduled_task",
            delivery_channel="task_update",
        )

    async def _handle_control_event(self, event):
        metadata = dict(getattr(event, "metadata", {}) or {})
        control_kind = str(metadata.get("control_kind") or "").strip().lower()
        payload = event.content if isinstance(event.content, dict) else {}
        task_key = str(payload.get("task_key") or "").strip()
        claim_token = str(payload.get("claim_token") or metadata.get("claim_token") or "").strip()
        operation_id = str(payload.get("operation_id") or metadata.get("operation_id") or "").strip()
        if control_kind == "reply_control":
            await self._handle_reply_control_event(event)
            return True
        if control_kind == "scheduled_task" and task_key:
            await self._handle_scheduled_task(
                task_key,
                claim_token=claim_token,
                trace_id=getattr(event, "event_id", ""),
                operation_id=operation_id,
            )
            return True
        if control_kind == "scheduled_reminder" and task_key:
            await self._handle_scheduled_reminder(
                task_key,
                claim_token=claim_token,
                trace_id=getattr(event, "event_id", ""),
                operation_id=operation_id,
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
                "agent_managed_mcp_servers": [],
                "runtime_native_tools": [],
                "summary": {
                    "configured_server_count": len(configured_servers),
                    "enabled_count": len(available_servers),
                    "partial_failure_count": 0,
                    "partial_failure_servers": [],
                    "agent_managed_server_count": 0,
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
                if runtime_payload.get("error") and not payload.get("error"):
                    payload["error"] = runtime_payload.get("error")
                if runtime_payload.get("command") and not payload.get("command"):
                    payload["command"] = runtime_payload.get("command")
                if runtime_payload.get("tool_count") is not None:
                    payload["tool_count"] = int(runtime_payload.get("tool_count") or 0)
            enriched_core_servers.append(payload)
        boundary["core_mcp_servers"] = enriched_core_servers
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

    async def get_runtime_debug(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id is required")
        session_debug = self.brain.get_session_debug_snapshot(session_id)
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
        await self._get_client_thread_bridge().publish_control_event(session_id, dict(payload or {}), turn_id=turn_id)

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

    def build_agent_connection_prompt(
        self,
        *,
        agent_id: str,
        agent_type: str,
        display_name: str,
        transport_profile: str,
        workspace_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            base_prompt = str(
                self.config.get_prompt("agent_connected")
                or self.config.get_prompt("agent_connection")
                or ""
            ).strip()
        except Exception:
            base_prompt = ""
        workspace_list = [str(item).strip() for item in (workspace_ids or []) if str(item).strip()]
        context = {
            "trigger": "agent_connected",
            "agent_id": str(agent_id or "").strip(),
            "agent_type": str(agent_type or "").strip(),
            "display_name": str(display_name or "").strip(),
            "transport_profile": str(transport_profile or "").strip(),
            "workspace_ids": workspace_list,
        }
        workspace_text = "、".join(workspace_list) if workspace_list else "未声明工作区"
        prompt_parts = []
        if base_prompt:
            prompt_parts.append(base_prompt)
        prompt_parts.append(
            "现在有一个新的 Agent 刚刚接入系统。\n"
            "请你像真实协作中的助手一样，主动发出第一条简短、自然、不生硬的连接消息，语气友好、专业，像在和一个刚上线的同事说话。\n"
            "这条消息需要做到三件事：1）表明你已经感知到它已连接；2）结合它的身份和工作区给出贴合上下文的欢迎或协作提示；3）说明你会等待它的能力快照或后续任务。\n"
            "不要输出 JSON、字段名清单、程序化枚举或过度模板化措辞。\n\n"
            f"本次接入的是 {context['display_name'] or context['agent_id'] or '未知 Agent'}"
            f"（agent_id={context['agent_id'] or 'unknown'}，类型={context['agent_type'] or 'unknown'}，"
            f"传输={context['transport_profile'] or 'unknown'}），当前声明的工作区有：{workspace_text}。"
        )
        prompt = "\n\n".join(prompt_parts).strip()
        return {
            "prompt_name": "agent_connected",
            "prompt": prompt,
            "context": context,
        }

    async def inject_agent_connection_event(
        self,
        *,
        agent_id: str,
        agent_type: str,
        display_name: str,
        transport_profile: str,
        workspace_ids: list[str] | None = None,
        connection_prompt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = (
            dict(connection_prompt)
            if isinstance(connection_prompt, dict) and connection_prompt
            else self.build_agent_connection_prompt(
                agent_id=agent_id,
                agent_type=agent_type,
                display_name=display_name,
                transport_profile=transport_profile,
                workspace_ids=workspace_ids,
            )
        )
        prompt_text = str(payload.get("prompt") or "").strip()
        if not prompt_text:
            return payload
        agent_key = str(agent_id or "").strip() or "unknown"
        agent_session_id = f"system:agent:{agent_key}"
        agent_target = make_target(
            TargetKind.INTERNAL.value,
            target_id=agent_key,
            trigger="agent_connected",
        )
        bridge_metadata = self._recent_client_thread_bridge_metadata(workspace_ids=workspace_ids)
        event = InboundEvent(
            session_id=agent_session_id,
            type=EventType.MESSAGE.value,
            role="user",
            content=prompt_text,
            source=make_source(
                SourceKind.SYSTEM.value,
                "agent_connection",
                display_name="Agent Connection",
                agent_id=agent_key,
            ),
            target=agent_target,
            metadata={
                "prompt_name": str(payload.get("prompt_name") or "agent_connected"),
                "trigger": "agent_connected",
                "agent_id": agent_key,
                "agent_type": str(agent_type or "").strip(),
                "display_name": str(display_name or "").strip(),
                "transport_profile": str(transport_profile or "").strip(),
                "workspace_ids": [str(item).strip() for item in (workspace_ids or []) if str(item).strip()],
                "transient": True,
                "connection_prompt": payload,
                "bridge_thread_id": str(bridge_metadata.get("thread_id") or ""),
                "bridge_workspace_id": str(bridge_metadata.get("workspace_id") or ""),
                "bridge_client_id": str(bridge_metadata.get("client_id") or ""),
                "bridge_session_id": str(bridge_metadata.get("bridged_session_id") or ""),
            },
        )
        bind_runtime_session = getattr(self.session_manager, "bind_runtime_session", None)
        if callable(bind_runtime_session):
            bind_runtime_session(
                make_source(SourceKind.SYSTEM.value, f"agent:{agent_key}", agent_id=agent_key),
                session_id=agent_session_id,
                default_target=agent_target,
                metadata={
                    "transient": True,
                    "trigger": "agent_connected",
                    "agent_id": agent_key,
                    "thread_id": str(bridge_metadata.get("thread_id") or ""),
                    "workspace_id": str(bridge_metadata.get("workspace_id") or ""),
                    "client_id": str(bridge_metadata.get("client_id") or ""),
                    "bridged_session_id": str(bridge_metadata.get("bridged_session_id") or ""),
                },
            )
        await self.event_bus.inbound_queue.put(event)
        logger.info(
            "Injected agent connection event into Core",
            extra={
                "context": {
                    "agent_id": agent_key,
                    "agent_type": str(agent_type or "").strip(),
                    "workspace_ids": [str(item).strip() for item in (workspace_ids or []) if str(item).strip()],
                    "trigger": "agent_connected",
                    "bridge_thread_id": str(bridge_metadata.get("thread_id") or ""),
                }
            },
        )
        return payload

    def _resolve_session_execution_request(self, event: InboundEvent) -> SessionExecutionRequest | None:
        effective_session_id = event.session_id
        is_agent_connection_reply = False
        if event.type == EventType.SIGNAL.value:
            if self._is_heartbeat_signal(event):
                delivery = self._recent_user_delivery()
                if delivery is None:
                    logger.info("Skipping heartbeat signal because no recent active session is available")
                    return None
                effective_session_id, target = delivery
            else:
                target = EventTarget(kind=TargetKind.CURRENT_SESSION.value)
            input_info = self._build_signal_input(event)
        else:
            event_metadata = dict(getattr(event, "metadata", {}) or {})
            is_agent_connection_reply = bool(
                event_metadata.get("trigger") == "agent_connected"
                and str(effective_session_id or "").strip().startswith("system:agent:")
            )
            input_info = {
                "role": event.role,
                "content": event.content,
                "metadata": event_metadata,
            }
            target = (
                EventTarget(kind=TargetKind.BROADCAST.value)
                if effective_session_id == "system:boot"
                else EventTarget(kind=TargetKind.INTERNAL.value, id=event_metadata.get("agent_id"))
                if is_agent_connection_reply
                else EventTarget(kind=TargetKind.CURRENT_SESSION.value)
            )
        return SessionExecutionRequest(
            session_id=effective_session_id,
            event=event,
            input_info=input_info,
            target=target,
            is_boot=effective_session_id == "system:boot" or is_agent_connection_reply,
        )

    def _enrich_request_procedure_context(self, request: SessionExecutionRequest) -> None:
        if self.core_services is None or self.core_domain is None:
            return
        metadata = dict(request.input_info.get("metadata") or {})
        session_row = self.core_services.session.get_by_session_id(request.session_id)
        if session_row is None:
            return
        thread_row = self.core_services.thread.get_by_id(session_row.thread_id)
        workspace_row = self.core_services.workspace.get_by_id(session_row.workspace_id)
        if thread_row is None or workspace_row is None:
            return
        if request.event.type == EventType.MESSAGE.value and request.event.role == "user":
            inference = self.core_services.procedure.infer_for_turn(
                principal_id=self.core_domain.principal.id,
                content=str(request.input_info.get("content") or ""),
                preferred_mode=str(metadata.get("preferred_mode") or workspace_row.base_mode or ""),
                workspace_id=str(getattr(workspace_row, "workspace_id", "") or ""),
            )
            self.core_services.thread.set_latest_inferred_procedure(
                thread_id=thread_row.id,
                procedure_id=str(inference.get("procedure_id") or ""),
                score=int(inference.get("score", 0) or 0),
                reason=str(inference.get("reason") or ""),
                inferred_at=str(inference.get("inferred_at") or ""),
            )
            refreshed_thread = self.core_services.thread.get_by_id(thread_row.id)
            if refreshed_thread is not None:
                thread_row = refreshed_thread
        context = self.core_services.procedure.get_thread_context(thread_row)
        pinned = context.get("pinned_procedure")
        effective = context.get("effective_procedure")
        if isinstance(pinned, dict):
            metadata["pinned_procedure_id"] = str(pinned.get("procedure_id") or "")
            metadata["pinned_procedure"] = dict(pinned)
        else:
            metadata.pop("pinned_procedure_id", None)
            metadata.pop("pinned_procedure", None)
        if isinstance(effective, dict):
            metadata["effective_procedure"] = dict(effective)
            metadata["effective_procedure_source"] = str(context.get("source") or "none")
        else:
            metadata.pop("effective_procedure", None)
            metadata["effective_procedure_source"] = "none"
        request.input_info["metadata"] = metadata

    async def _process_session_execution(self, request: SessionExecutionRequest) -> None:
        stream_id = ""
        turn_id = uuid4().hex
        answer_chunks: list[str] = []
        token = bind_event_context(
            trace_id=getattr(request.event, "event_id", ""),
            session_id=request.session_id,
            turn_id=turn_id,
            source=request.event.source,
            target=request.target,
            workspace_id=str((request.input_info.get("metadata") or {}).get("workspace_id") or ""),
            thread_id=str((request.input_info.get("metadata") or {}).get("thread_id") or ""),
            pinned_procedure_id=str((request.input_info.get("metadata") or {}).get("pinned_procedure_id") or ""),
        )
        reasoning_started = False
        reasoning_ended = False
        finish_reason = ""

        try:
            api_key = self.config.get("api_key") or ""
            api_url = self.config.get("api_url") or ""
            model = self.config.get("model") or ""
            model_options = self._build_model_options(getattr(request.event, "metadata", {}))

            self._enrich_request_procedure_context(request)

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
                await self._get_client_thread_bridge().publish_activity_event(
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
                    await self._get_client_thread_bridge().publish_message_delta(
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
            await self._get_client_thread_bridge().persist_and_publish_assistant_message(
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

    async def setup(self):
        await setup_app_runtime(self)

    async def run(self, *, on_ready=None, on_stopping=None):
        await run_app_runtime(self, on_ready=on_ready, on_stopping=on_stopping)

    async def shutdown(self):
        await shutdown_app_runtime(self)
