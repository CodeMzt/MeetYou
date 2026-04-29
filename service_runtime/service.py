from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from pathlib import Path
from typing import Any

from build_info import load_build_info
from cil.client import CILClient
from core.app import App
from core.background_status import build_system_issue_snapshot
from launcher import run_launcher
from service_runtime.boundaries import (
    RuntimeModuleSet,
    build_default_runtime_boundaries,
    build_runtime_platform_boundaries,
)
from service_runtime.models import (
    RuntimeCommand,
    RuntimeError,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeHealth,
    RuntimeTelemetrySignal,
    RuntimeHealthStatus,
)
from service_runtime.telemetry import RuntimeTelemetryRecorder

logger = logging.getLogger("meetyou.service_runtime")


class ServiceRuntime:
    def __init__(
        self,
        command: RuntimeCommand,
        *,
        app_factory=None,
        cil_client_factory=None,
        launcher_runner=None,
    ):
        self.command = command
        self.boundaries: RuntimeModuleSet = build_default_runtime_boundaries()
        self.health = RuntimeHealth.from_component_names(self.boundaries.names())
        self.health.build_info = load_build_info(
            Path(__file__).resolve().parents[1] / "core" / "build_info.json",
            component="core",
            package_version="0.0.0",
        )
        self.health.replace_platform_boundary(build_runtime_platform_boundaries().to_dict())
        self.events: list[RuntimeEvent] = []
        self.telemetry = RuntimeTelemetryRecorder()
        self._app_factory = app_factory or App
        self._cil_client_factory = cil_client_factory or CILClient
        self._launcher_runner = launcher_runner or run_launcher
        self._app: App | None = None
        self._restart_requested = False
        self._restart_task: asyncio.Task | None = None
        self._mark_all_components(
            RuntimeHealthStatus.STARTING,
            "Runtime skeleton created",
            "runtime.command.accepted",
        )

    async def build_health_snapshot(self) -> dict[str, Any]:
        await self._refresh_health_from_runtime()
        return self.health.model_dump(mode="json")

    async def run(self) -> None:
        self._emit_event(
            kind=RuntimeEventKind.LIFECYCLE,
            action=f"{self.command.target}.{self.command.operation}",
            status=self.health.status,
            payload={"command": self.command.model_dump()},
        )
        try:
            if self.command.target == "launcher":
                self._mark_all_components(
                    RuntimeHealthStatus.READY,
                    "Launcher bridge active",
                    "launcher.start",
                )
                self._launcher_runner()
                return
            if self.command.target == "cil":
                self._mark_component(
                    "delivery",
                    RuntimeHealthStatus.READY,
                    "CIL bridge active",
                    "cil.start",
                )
                self._mark_component(
                    "telemetry",
                    RuntimeHealthStatus.READY,
                    "Runtime telemetry active",
                    "cil.start",
                )
                await self._cil_client_factory().run()
                return
            if self.command.target == "service":
                await self._run_service()
                return
            raise ValueError(f"unsupported runtime target: {self.command.target}")
        except Exception as exc:
            runtime_error = RuntimeError.from_exception(exc, code="runtime_start_failed")
            self.health.record_error(runtime_error)
            self._emit_event(
                kind=RuntimeEventKind.ERROR,
                action=f"{self.command.target}.{self.command.operation}",
                status=self.health.status,
                payload={"error": runtime_error.model_dump()},
            )
            logger.exception(
                "Service runtime failed: %s: %s",
                runtime_error.code,
                runtime_error.message,
            )
            raise

    async def _run_service(self) -> None:
        while True:
            self._restart_requested = False
            self._app = self._build_app()
            runner = getattr(self._app, "run", None)
            if callable(runner):
                run_params = inspect.signature(runner).parameters
                if "on_ready" in run_params and "on_stopping" in run_params:
                    await runner(
                        on_ready=self._on_service_ready,
                        on_stopping=self._on_service_stopping,
                    )
                else:
                    await self._run_service_compat()
            else:
                await self._run_service_compat()
            if self._restart_task is not None:
                self._restart_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._restart_task
                self._restart_task = None
            if not self._restart_requested:
                return
            self._emit_event(
                kind=RuntimeEventKind.LIFECYCLE,
                action="service.restart",
                status=self.health.status,
                payload={"reason": "restart_requested"},
            )

    async def _run_service_compat(self) -> None:
        await self._app.setup()
        await self._on_service_ready()
        try:
            await asyncio.gather(
                self._app.brain_processor(),
                self._app.scheduler_processor(),
                self._app.heart.housekeeping_processor(),
                self._app.proprioceptor.run(),
            )
        finally:
            await self._on_service_stopping()
            await self._app.shutdown()

    async def _on_service_ready(self) -> None:
        self._mark_all_components(
            RuntimeHealthStatus.READY,
            "Service runtime active",
            "service.ready",
        )
        self._emit_event(
            kind=RuntimeEventKind.HEALTH,
            action="service.ready",
            status=self.health.status,
            payload=await self.build_health_snapshot(),
        )

    async def _on_service_stopping(self) -> None:
        self._mark_all_components(
            RuntimeHealthStatus.STOPPING,
            "Runtime stopping",
            "service.stop",
        )

    async def request_core_restart(self, *, reason: str = "", delay_seconds: int = 1, session_id: str = "") -> dict[str, Any]:
        if self.command.target != "service":
            return {"accepted": False, "reason": "unsupported_runtime_target"}
        if self._restart_requested:
            return {"accepted": True, "already_pending": True}
        self._restart_requested = True
        delay = max(0, min(int(delay_seconds or 0), 30))
        self._emit_event(
            kind=RuntimeEventKind.LIFECYCLE,
            action="service.restart.requested",
            status=self.health.status,
            payload={
                "reason": str(reason or ""),
                "delay_seconds": delay,
                "session_id": str(session_id or ""),
            },
        )

        async def _delayed_shutdown() -> None:
            await asyncio.sleep(delay)
            app = self._app
            event_bus = getattr(app, "event_bus", None)
            request_shutdown = getattr(event_bus, "request_shutdown", None)
            if callable(request_shutdown):
                request_shutdown()
                return
            stop = getattr(app, "stop", None)
            if callable(stop):
                result = stop()
                if inspect.isawaitable(result):
                    await result

        self._restart_task = asyncio.create_task(_delayed_shutdown())
        return {"accepted": True, "delay_seconds": delay, "reason": str(reason or "")}

    def _build_app(self) -> App:
        try:
            return self._app_factory(
                health_getter=self.build_health_snapshot,
                telemetry_recorder=self.telemetry,
                restart_requester=self.request_core_restart,
            )
        except TypeError:
            try:
                return self._app_factory(
                    health_getter=self.build_health_snapshot,
                    telemetry_recorder=self.telemetry,
                )
            except TypeError:
                return self._app_factory(health_getter=self.build_health_snapshot)

    def _emit_event(
        self,
        *,
        kind: str | RuntimeEventKind,
        action: str,
        status: str,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        resolved_kind = kind.value if isinstance(kind, RuntimeEventKind) else str(kind)
        event = RuntimeEvent(
            kind=resolved_kind,
            source="service_runtime",
            action=action,
            status=status,
            payload=dict(payload or {}),
            metadata=dict(metadata or {}),
        )
        self.events.append(event)
        return event

    def _mark_all_components(
        self,
        status: str | RuntimeHealthStatus,
        detail: str,
        last_event: str,
    ) -> None:
        for name in self.boundaries.names():
            self._mark_component(name, status, detail, last_event)

    def _mark_component(
        self,
        name: str,
        status: str | RuntimeHealthStatus,
        detail: str,
        last_event: str,
    ) -> None:
        self.health.set_component(name, status, detail, last_event)

    async def _refresh_health_from_runtime(self) -> None:
        metrics = self.telemetry.metrics_snapshot()
        checks: list[tuple[str, str, str, dict[str, Any]]] = []

        if self._app is not None:
            background_status = await self._app.get_background_status()
            self.telemetry.observe_background_status(background_status)
            metrics = {**metrics, **self.telemetry.metrics_snapshot()}
            issue_snapshot = build_system_issue_snapshot(background_status)
            get_core_mcp_diagnostics = getattr(self._app, "get_core_mcp_diagnostics", None)
            core_mcp_diagnostics = get_core_mcp_diagnostics() if callable(get_core_mcp_diagnostics) else {}
            core_mcp_summary = dict(core_mcp_diagnostics.get("summary") or {})
            core_mcp_config = dict(core_mcp_diagnostics.get("config") or {})
            system_issue_candidates = issue_snapshot["system_issue_candidates"]
            pending_delivery_count = int(background_status.get("pending_delivery_count", 0) or 0)
            gateway_delivery_failures = int(metrics.get("gateway_delivery_failures_total", 0) or 0)
            delivery_degraded = gateway_delivery_failures > 0
            tool_degraded = int(metrics.get("tool_failures_total", 0) or 0) > 0
            background_degraded = bool(system_issue_candidates)
            core_mcp_degraded = int(core_mcp_summary.get("partial_failure_count", 0) or 0) > 0
            metrics["core_mcp_configured_count"] = int(core_mcp_summary.get("configured_server_count", 0) or 0)
            metrics["core_mcp_enabled_count"] = int(core_mcp_summary.get("enabled_count", 0) or 0)
            metrics["core_mcp_partial_failures_count"] = int(core_mcp_summary.get("partial_failure_count", 0) or 0)
            metrics["heartbeat_idle_poke_enabled"] = bool(background_status.get("heartbeat_idle_poke_enabled"))
            metrics["heartbeat_idle_poke_after_seconds"] = int(background_status.get("heartbeat_idle_poke_after_seconds") or 0)
            metrics["heartbeat_idle_poke_cooldown_seconds"] = int(background_status.get("heartbeat_idle_poke_cooldown_seconds") or 0)
            metrics["heartbeat_idle_poke_eligible"] = bool(background_status.get("idle_poke_eligible"))

            self._mark_component(
                "background_jobs",
                RuntimeHealthStatus.DEGRADED if background_degraded else RuntimeHealthStatus.READY,
                "Background loop stalled or failed"
                if background_degraded
                else "Background jobs healthy",
                "background.health.refresh",
            )
            self._mark_component(
                "delivery",
                RuntimeHealthStatus.DEGRADED if delivery_degraded else RuntimeHealthStatus.READY,
                "Gateway delivery failures detected"
                if delivery_degraded
                else (
                    "Gateway delivery has pending redelivery work"
                    if pending_delivery_count > 0
                    else "Gateway delivery healthy"
                ),
                "delivery.health.refresh",
            )
            self._mark_component(
                "tool_execution",
                RuntimeHealthStatus.READY,
                "Tool execution runtime active",
                "tool.health.refresh",
            )
            self._mark_component(
                "session_execution",
                RuntimeHealthStatus.READY,
                "Session execution runtime active",
                "session.health.refresh",
            )
            self._mark_component(
                "telemetry",
                RuntimeHealthStatus.READY,
                "Telemetry runtime active",
                "telemetry.health.refresh",
            )

            checks.extend(
                [
                    (
                        "background_loops",
                        RuntimeHealthStatus.DEGRADED.value if background_degraded else RuntimeHealthStatus.READY.value,
                        "检测到后台停滞或失败" if background_degraded else "后台循环正常",
                        issue_snapshot,
                    ),
                    (
                        "tool_execution",
                        RuntimeHealthStatus.DEGRADED.value if tool_degraded else RuntimeHealthStatus.READY.value,
                        "最近存在工具失败" if tool_degraded else "工具执行正常",
                        {
                            "tool_calls_total": int(metrics.get("tool_calls_total", 0) or 0),
                            "tool_failures_total": int(metrics.get("tool_failures_total", 0) or 0),
                        },
                    ),
                    (
                        "gateway_delivery",
                        RuntimeHealthStatus.DEGRADED.value if delivery_degraded else RuntimeHealthStatus.READY.value,
                        (
                            "存在网关投递失败"
                            if delivery_degraded
                            else ("存在待补发消息，但服务仍可用" if pending_delivery_count > 0 else "网关投递正常")
                        ),
                        {
                            "gateway_delivery_attempts_total": int(metrics.get("gateway_delivery_attempts_total", 0) or 0),
                            "gateway_delivery_failures_total": gateway_delivery_failures,
                            "background_pending_delivery_count": int(metrics.get("background_pending_delivery_count", 0) or 0),
                        },
                    ),
                    (
                        "core_mcp",
                        RuntimeHealthStatus.DEGRADED.value if core_mcp_degraded else RuntimeHealthStatus.READY.value,
                        "存在 Core MCP 部分失败，需要检查配置、鉴权或 server 启动状态"
                        if core_mcp_degraded
                        else "Core MCP 诊断可见",
                        {
                            "config_status": str(core_mcp_config.get("status") or ""),
                            "config_path": str(core_mcp_config.get("path") or ""),
                            "configured_server_count": int(core_mcp_summary.get("configured_server_count", 0) or 0),
                            "enabled_count": int(core_mcp_summary.get("enabled_count", 0) or 0),
                            "partial_failure_count": int(core_mcp_summary.get("partial_failure_count", 0) or 0),
                            "partial_failure_servers": list(core_mcp_summary.get("partial_failure_servers") or []),
                        },
                    ),
                    (
                        "heartbeat_idle_poke",
                        RuntimeHealthStatus.READY.value,
                        "Idle heartbeat proactive poke configuration visible",
                        {
                            "enabled": bool(background_status.get("heartbeat_idle_poke_enabled")),
                            "eligible": bool(background_status.get("idle_poke_eligible")),
                            "after_seconds": int(background_status.get("heartbeat_idle_poke_after_seconds") or 0),
                            "cooldown_seconds": int(background_status.get("heartbeat_idle_poke_cooldown_seconds") or 0),
                            "context_compaction_enabled": bool(background_status.get("heartbeat_idle_context_compaction_enabled")),
                            "last_idle_poke_at": str(background_status.get("last_idle_poke_at") or ""),
                            "last_proactive_delivery_at": str(background_status.get("last_proactive_delivery_at") or ""),
                            "last_proactive_delivery_status": str(background_status.get("last_proactive_delivery_status") or ""),
                        },
                    ),
                ]
            )
            if system_issue_candidates:
                checks.append(
                    (
                        "heartbeat_alignment",
                        RuntimeHealthStatus.DEGRADED.value,
                        "心跳与健康检查共识存在后台异常候选",
                        {
                            **issue_snapshot,
                            "source": "shared.system_issue_candidates",
                        },
                    )
                )

        self.health.replace_metrics(metrics)
        for name, status, detail, metadata in checks:
            self.health.set_check(name, status, detail, metadata)
        self.health.replace_telemetry(
            [
                item if isinstance(item, RuntimeTelemetrySignal) else RuntimeTelemetrySignal(**item)
                for item in self.telemetry.recent_signals()
            ]
        )
        self.health.live = self.health.status != RuntimeHealthStatus.STOPPING.value
