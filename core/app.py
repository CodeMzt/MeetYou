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
from core.event_bus import EventBus
from core.exceptions import ConfigError, ExceptionRouter, MeetYouError
from core.heart import Heart
from core.io_protocol import (
    EventTarget,
    EventType,
    InboundEvent,
    OutboundEvent,
    SourceKind,
    StreamEventType,
    TargetKind,
    make_source,
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
    "cmd_policy_path",
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
    "tavily_api_key",
    "tools_schema_path",
}


class App:
    def __init__(self, health_getter=None, telemetry_recorder=None):
        setup_logger(enable_console=True, component="gateway")

        self.event_bus = EventBus()
        self.exception_router = ExceptionRouter()
        self.config = ConfigManager()
        self.platform = detect_platform()
        self.status_manager = StatusManager()
        self.mode_manager = AssistantModeManager(self.config)

        self.main_adapter = create_adapter(self._get_main_provider())
        self.heart_adapter = create_adapter(self._get_heart_provider())

        self.memory = Memory()
        self.task_manager = TaskManager(self.memory)
        self.mcp_manager = MCPManager()
        system_tools.init_system_tools(
            self.platform,
            self.event_bus,
            self.config.get("cmd_policy_path") or "user/cmd_policy.json",
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
        self._session_execution_runtime = SessionActorRuntime(self._process_session_execution)

        self.exception_router.on_system_error(self._log_error)
        self.exception_router.on_user_error(self._display_error)
        self.event_bus.subscribe(self.event_bus.CONFIRM_REQUEST, self._handle_confirm_request)
        self.event_bus.subscribe(self.event_bus.CONFIRM_RESPONSE, self._handle_confirm_response)
        self.event_bus.subscribe(self.event_bus.HUMAN_INPUT_REQUEST, self._handle_human_input_request)
        self.event_bus.subscribe(self.event_bus.HUMAN_INPUT_RESPONSE, self._handle_human_input_response)

        logger.info("Service runtime dependencies initialized")

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

    async def _handle_confirm_request(self, event):
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

    async def _handle_confirm_response(self, payload):
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
            self.session_manager.get_or_create_session(
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

    def _scheduled_job_route_context(self) -> tuple[list[dict], dict[str, Any]]:
        tools = self.tools_manager.get_scheduled_job_tools()
        return tools, {
            "current_mode": "scheduled_task",
            "route_reason": "Scheduler claimed an assistant-owned background task.",
            "source_profile": "scheduled_tasks",
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

    async def _handle_scheduled_reminder(self, task_key: str, claim_token: str = "", trace_id: str = ""):
        if not self._control_claim_valid(task_key, claim_token):
            return
        task_record = self.task_manager.get_task_by_key(task_key)
        if task_record is None:
            return
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
            await self.task_manager.complete_due_notification(
                task_key,
                summary=message,
                delivered=(delivered or not should_notify),
                runtime_source="app.scheduled_reminder",
                delivery_channel="task_update",
            )
        finally:
            reset_event_context(token)

    async def _handle_scheduled_task(self, task_key: str, claim_token: str = "", trace_id: str = ""):
        if not self._control_claim_valid(task_key, claim_token):
            return
        task_record = self.task_manager.get_task_by_key(task_key)
        if task_record is None:
            return

        tools, route_context = self._scheduled_job_route_context()
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
        if control_kind == "scheduled_task" and task_key:
            await self._handle_scheduled_task(task_key, claim_token=claim_token, trace_id=getattr(event, "event_id", ""))
            return True
        if control_kind == "scheduled_reminder" and task_key:
            await self._handle_scheduled_reminder(task_key, claim_token=claim_token, trace_id=getattr(event, "event_id", ""))
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

    def get_runtime_state(self, session_id: str = "") -> dict[str, Any]:
        return {
            "global_state": self.status_manager.get_global(),
            "heartbeat_state": self.status_manager.get_heartbeat(),
            "session_state": self.brain.get_session_runtime_snapshot(session_id) if session_id else None,
        }

    async def get_runtime_debug(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id is required")
        session_debug = self.brain.get_session_debug_snapshot(session_id)
        route_snapshot = dict(session_debug.get("route") or {})
        event_bus = getattr(self, "event_bus", None)
        tool_debug_getter = getattr(self.tools_manager, "get_route_debug_snapshot", None)
        route_authorization = (
            tool_debug_getter(route_snapshot)
            if callable(tool_debug_getter)
            else {"visible_tools": [], "candidate_tools": [], "authorization_preview": []}
        )
        background_status = await self.heart.get_background_status()
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
                    "pending": bool(
                        getattr(event_bus, "has_pending_confirmation", False)
                        and getattr(event_bus, "pending_confirmation_session_id", "") == session_id
                    ),
                    "request_id": (
                        getattr(event_bus, "pending_request_id", "")
                        if getattr(event_bus, "pending_confirmation_session_id", "") == session_id
                        else ""
                    ),
                },
            },
            "object_operations": [
                dict(item)
                for item in session_debug.get("object_operations", [])
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
            "updated_at": str(session_debug.get("updated_at") or utcnow_iso()),
        }

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

        binding = self.session_manager.get_binding(session_id)
        if binding is None:
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

    @staticmethod
    def _build_boot_event(start_prompt: str, source) -> InboundEvent:
        return InboundEvent(
            session_id="system:boot",
            type=EventType.MESSAGE.value,
            role="user",
            content=start_prompt,
            source=source,
            target=EventTarget(kind=TargetKind.BROADCAST.value),
            metadata={"transient": True, "boot_event": True},
        )

    def _resolve_session_execution_request(self, event: InboundEvent) -> SessionExecutionRequest | None:
        effective_session_id = event.session_id
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
            input_info = {
                "role": event.role,
                "content": event.content,
                "metadata": dict(getattr(event, "metadata", {}) or {}),
            }
            target = (
                EventTarget(kind=TargetKind.BROADCAST.value)
                if effective_session_id == "system:boot"
                else EventTarget(kind=TargetKind.CURRENT_SESSION.value)
            )
        return SessionExecutionRequest(
            session_id=effective_session_id,
            event=event,
            input_info=input_info,
            target=target,
            is_boot=effective_session_id == "system:boot",
        )

    async def _process_session_execution(self, request: SessionExecutionRequest) -> None:
        stream_id = ""
        turn_id = uuid4().hex
        token = bind_event_context(
            trace_id=getattr(request.event, "event_id", ""),
            session_id=request.session_id,
            turn_id=turn_id,
            source=request.event.source,
            target=request.target,
        )
        reasoning_started = False
        reasoning_ended = False

        try:
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

            self.brain.set_session_runtime_state(
                request.session_id,
                RuntimeStatus.IDLE.value,
                detail="",
                active_tools=[],
                stream_id=stream_id,
                turn_id=turn_id,
            )
            await self._emit_runtime_status_event(request.session_id, request.target, turn_id)
            await self.speaker.emit_stream_end(
                request.session_id,
                self._brain_source,
                stream_id,
                target=request.target,
                stream_channel="answer",
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
            )
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
        tools_schema_path = self.config.get("tools_schema_path") or "user/tools.json"
        mcp_servers = self.config.get_mcp_servers()

        self.status_manager.set_global(RuntimeStatus.INITIALIZING.value, "Starting up")
        await self.memory.init_memory(self.config)
        await self.tools_manager.init_tools(tools_schema_path, mcp_servers)
        await self._refresh_brain_runtime()
        await self.heart.init_heart()
        system_tools.set_background_status_provider(self.heart.get_background_status)

        host = self.config.get("gateway_host") or "127.0.0.1"
        port = int(self.config.get("gateway_port") or 8000)
        gateway_access_token = str(self.config.get("gateway_access_token") or "").strip()
        if host not in {"127.0.0.1", "localhost", "::1"} and not gateway_access_token:
            raise ConfigError("非本地 gateway_host 必须配置 gateway_access_token")
        self.gateway = FastAPIGateway(
            self.event_bus,
            self.session_manager,
            config_snapshot_getter=self.get_config_snapshot,
            config_item_getter=self.get_config_entry,
            config_updater=self.apply_config_updates,
            memory_snapshot_getter=self.get_memory_snapshot,
            memory_graph_getter=self.get_memory_graph,
            runtime_state_getter=self.get_runtime_state,
            runtime_usage_getter=self.get_runtime_usage,
            runtime_debug_getter=self.get_runtime_debug,
            health_getter=self._health_getter,
            ws_delivery_observer=(
                self._telemetry_recorder.observe_gateway_delivery
                if self._telemetry_recorder is not None
                else None
            ),
            access_token=gateway_access_token,
            cors_origins=self.config.get("gateway_cors_origins") or [],
        )
        self.speaker.register_adapter(TargetKind.WEB.value, self.gateway.output_adapter)
        await self.gateway.start(host=host, port=port)

        if self.config.get_bool("enable_feishu_bot"):
            self.feishu_input = FeishuInputAdapter(
                self.event_bus,
                self.session_manager,
                self.config,
            )
            self.feishu_output = FeishuOutputAdapter(self.config)
            await self.feishu_output.init()
            self.speaker.register_adapter(TargetKind.FEISHU.value, self.feishu_output)
            self._register_feishu_broadcast_targets()
            await self.feishu_input.run()

        self.status_manager.set_global(RuntimeStatus.IDLE.value, "")
        logger.info("Service runtime initialized")

        try:
            start_prompt = self.config.get_prompt("start")
            boot_source = make_source(SourceKind.SYSTEM.value, "boot")
            await self.event_bus.inbound_queue.put(self._build_boot_event(start_prompt, boot_source))
            logger.info("Boot wake-up event injected")
        except Exception as exc:
            logger.warning("Failed to inject boot wake-up event (non-fatal): %s", exc)

    async def run(self):
        await self.setup()
        try:
            await asyncio.gather(
                self.brain_processor(),
                self.heart.scheduler_processor(),
                self.heart.housekeeping_processor(),
                self.heart.heartbeat_processor(),
                self.proprioceptor.run(),
            )
        finally:
            await self.shutdown()

    async def shutdown(self):
        logger.info("Shutting down...")
        self.status_manager.set_global(RuntimeStatus.SHUTTING_DOWN.value, "Shutting down")
        self.event_bus.request_shutdown()
        await self._session_execution_runtime.shutdown()
        if self.gateway is not None:
            await self.gateway.stop()
        if self.feishu_input is not None:
            await self.feishu_input.close()
        if self.feishu_output is not None:
            await self.feishu_output.close()
        await self.mcp_manager.close_mcp_servers()
        await self.brain.close_brain()
        await self.heart.close_heart()
        await self.memory.close_memory()
        logger.info("All resources released")
