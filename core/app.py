"""
Application wiring and lifecycle management.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Any
from uuid import uuid4

from adapters.base import create_adapter
from core.assistant_modes import AssistantModeManager
from core.brain import Brain, BrainOutputEvent
from core.config import ConfigManager
from core.context import ContextManager
from core.event_bus import EventBus
from core.exceptions import ExceptionRouter, MeetYouError
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
from core.session_manager import SessionManager
from core.speaker import Speaker
from core.status import RuntimeStatus, StatusManager
from core.tools_manager import ToolsManager
from gateway.api import FastAPIGateway
from platform_layer.detector import detect_platform
from sensors.feishu_input_adapter import FeishuInputAdapter
from sensors.feishu_output_adapter import FeishuOutputAdapter
from sensors.proprioceptor import Proprioceptor
from tools import system_tools
from tools.mcp import MCPManager
from tools.memory import Memory

logger = logging.getLogger("meetyou.app")

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
    "heartbeat_interval",
    "heart_model",
    "heartbeat_path",
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
    "source_profiles",
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
    def __init__(self):
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
        )
        self.brain = Brain(
            self.main_adapter,
            self.tools_manager,
            self.context_manager,
            self.event_bus,
            self.exception_router,
            mode_manager=self.mode_manager,
        )
        self.heart = Heart(
            self.heart_adapter,
            self.config,
            self.tools_manager,
            self.memory,
            self.event_bus,
            self.exception_router,
            status_callback=self._update_heartbeat_status,
        )

        self.session_manager = SessionManager()
        self.speaker = Speaker(self.session_manager)
        self.gateway: FastAPIGateway | None = None
        self.feishu_input: FeishuInputAdapter | None = None
        self.feishu_output: FeishuOutputAdapter | None = None
        self.proprioceptor = Proprioceptor(self.platform, self.context_manager, self.event_bus)

        self._brain_source = make_source(SourceKind.SYSTEM.value, "brain")
        self._runtime_source = make_source(SourceKind.SYSTEM.value, "runtime")
        self._usage_source = make_source(SourceKind.SYSTEM.value, "usage")

        self.exception_router.on_system_error(self._log_error)
        self.exception_router.on_user_error(self._display_error)
        self.event_bus.subscribe(self.event_bus.CONFIRM_REQUEST, self._handle_confirm_request)
        self.event_bus.subscribe(self.event_bus.CONFIRM_RESPONSE, self._handle_confirm_response)

        logger.info("Gateway runtime dependencies initialized")

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

    def get_runtime_usage(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id is required")
        snapshot = self.brain.get_session_usage_snapshot(session_id)
        if snapshot is None:
            raise ValueError(f"Session not found: {session_id}")
        return snapshot

    async def apply_config_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        applied_keys, warnings = self.config.apply_updates(updates)
        if not applied_keys:
            return {
                "applied_keys": [],
                "reloaded_components": [],
                "restart_required_keys": [],
                "warnings": warnings,
            }

        self.config.reload()
        reloaded_components: set[str] = set()
        restart_required = sorted(_RESTART_REQUIRED_KEYS.intersection(applied_keys))

        if "enable_gateway" in applied_keys:
            warnings.append("enable_gateway is ignored in the gateway-only runtime.")

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
            reloaded_components.add("mode_manager")

        if restart_required:
            warnings.append(
                "The following keys were written, but require a gateway restart to fully take effect: "
                + ", ".join(restart_required)
            )

        return {
            "applied_keys": applied_keys,
            "reloaded_components": sorted(reloaded_components),
            "restart_required_keys": restart_required,
            "warnings": warnings,
        }

    async def brain_processor(self):
        shutdown = self.event_bus.shutdown_event
        queue = self.event_bus.inbound_queue

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

            if event.type == EventType.SIGNAL.value:
                input_info = {
                    "role": "system",
                    "content": f"系统后台心跳捕获到重要潜意识事务，请立刻作为内部处理：{event.content}",
                }
            else:
                input_info = {
                    "role": event.role,
                    "content": event.content,
                    "metadata": dict(getattr(event, "metadata", {}) or {}),
                }

            is_boot = event.session_id == "system:boot"
            target = (
                EventTarget(kind=TargetKind.BROADCAST.value)
                if is_boot
                else EventTarget(kind=TargetKind.CURRENT_SESSION.value)
            )
            token = bind_event_context(
                session_id=event.session_id,
                source=event.source,
                target=target,
            )

            stream_id = ""
            turn_id = uuid4().hex
            reasoning_started = False
            reasoning_ended = False

            try:
                api_key = self.config.get("api_key") or ""
                api_url = self.config.get("api_url") or ""
                model = self.config.get("model") or ""
                model_options = self._build_model_options(getattr(event, "metadata", {}))

                stream_id = await self.speaker.emit_stream_start(
                    event.session_id,
                    self._brain_source,
                    target=target,
                    stream_channel="answer",
                )

                async def emit_tool_activity(phase: str, content: str, metadata: dict | None = None):
                    metadata = metadata or {}
                    await self.speaker.emit_status(
                        event.session_id,
                        content,
                        make_source(SourceKind.SYSTEM.value, "search"),
                        target=target,
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
                        event.session_id,
                        status,
                        detail=detail,
                        active_tools=active_tools or [],
                        stream_id=stream_id,
                        turn_id=turn_id,
                    )
                    await self._emit_runtime_status_event(event.session_id, target, turn_id)

                self.brain.set_session_runtime_state(
                    event.session_id,
                    RuntimeStatus.THINKING.value,
                    detail="Starting turn",
                    active_tools=[],
                    stream_id=stream_id,
                    turn_id=turn_id,
                )
                await self._emit_runtime_status_event(event.session_id, target, turn_id)

                async for output in self.brain.input_brain(
                    event.session_id,
                    input_info,
                    api_key,
                    api_url,
                    model,
                    tool_activity_callback=emit_tool_activity,
                    model_options=model_options,
                    phase_callback=phase_callback,
                ):
                    if not isinstance(output, BrainOutputEvent):
                        continue

                    if output.type == "reasoning_text" and output.text:
                        if not reasoning_started:
                            await self._emit_reasoning_stream_event(
                                event.session_id,
                                stream_id,
                                StreamEventType.START.value,
                                "",
                                target,
                                turn_id,
                            )
                            reasoning_started = True
                        await self._emit_reasoning_stream_event(
                            event.session_id,
                            stream_id,
                            StreamEventType.CHUNK.value,
                            output.text,
                            target,
                            turn_id,
                        )
                    elif output.type == "answer_text" and output.text:
                        if reasoning_started and not reasoning_ended:
                            await self._emit_reasoning_stream_event(
                                event.session_id,
                                stream_id,
                                StreamEventType.END.value,
                                "",
                                target,
                                turn_id,
                            )
                            reasoning_ended = True
                        await self.speaker.emit_stream_chunk(
                            event.session_id,
                            output.text,
                            self._brain_source,
                            stream_id,
                            target=target,
                            stream_channel="answer",
                        )
                    elif output.type == "usage" and output.usage:
                        await self._emit_usage_event(event.session_id, output.usage, target, turn_id)

                if reasoning_started and not reasoning_ended:
                    await self._emit_reasoning_stream_event(
                        event.session_id,
                        stream_id,
                        StreamEventType.END.value,
                        "",
                        target,
                        turn_id,
                    )

                self.brain.set_session_runtime_state(
                    event.session_id,
                    RuntimeStatus.IDLE.value,
                    detail="",
                    active_tools=[],
                    stream_id=stream_id,
                    turn_id=turn_id,
                )
                await self._emit_runtime_status_event(event.session_id, target, turn_id)
                await self.speaker.emit_stream_end(
                    event.session_id,
                    self._brain_source,
                    stream_id,
                    target=target,
                    stream_channel="answer",
                )
            except Exception as exc:
                logger.error("Brain processing error: %s\n%s", exc, traceback.format_exc())
                self.brain.set_session_runtime_state(
                    event.session_id,
                    RuntimeStatus.ERROR.value,
                    detail=str(exc),
                    active_tools=[],
                    stream_id=stream_id,
                    turn_id=turn_id,
                )
                await self._emit_runtime_status_event(event.session_id, target, turn_id)
                await self.speaker.emit_error(
                    event.session_id,
                    str(exc),
                    self._brain_source,
                    target=target,
                    stream_id=stream_id,
                    metadata={"turn_id": turn_id, "stream_channel": "answer"},
                )
            finally:
                reset_event_context(token)
                if is_boot:
                    await self.brain.close_session(event.session_id)

    async def setup(self):
        tools_schema_path = self.config.get("tools_schema_path") or "user/tools.json"
        mcp_servers = self.config.get_mcp_servers()

        self.status_manager.set_global(RuntimeStatus.INITIALIZING.value, "Starting up")
        await self.memory.init_memory(self.config)
        await self.tools_manager.init_tools(tools_schema_path, mcp_servers)
        await self._refresh_brain_runtime()
        await self.heart.init_heart()

        if not self.config.get_bool("enable_gateway", True):
            logger.warning("enable_gateway=false is ignored in the gateway-only runtime.")

        host = self.config.get("gateway_host") or "127.0.0.1"
        port = int(self.config.get("gateway_port") or 8000)
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
        logger.info("Gateway runtime initialized")

        try:
            start_prompt = self.config.get_prompt("start")
            boot_source = make_source(SourceKind.SYSTEM.value, "boot")
            await self.event_bus.inbound_queue.put(
                InboundEvent(
                    session_id="system:boot",
                    type=EventType.MESSAGE.value,
                    role="user",
                    content=start_prompt,
                    source=boot_source,
                    target=EventTarget(kind=TargetKind.BROADCAST.value),
                )
            )
            logger.info("Boot wake-up event injected")
        except Exception as exc:
            logger.warning("Failed to inject boot wake-up event (non-fatal): %s", exc)

    async def run(self):
        await self.setup()
        try:
            await asyncio.gather(
                self.brain_processor(),
                self.heart.heartbeat_processor(),
                self.proprioceptor.run(),
            )
        finally:
            await self.shutdown()

    async def shutdown(self):
        logger.info("Shutting down...")
        self.status_manager.set_global(RuntimeStatus.SHUTTING_DOWN.value, "Shutting down")
        self.event_bus.request_shutdown()
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
