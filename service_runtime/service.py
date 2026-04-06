from __future__ import annotations

import asyncio
import logging
from typing import Any

from cil.client import CILClient
from core.app import App
from core.background_status import build_system_issue_snapshot
from launcher import run_launcher
from service_runtime.boundaries import RuntimeModuleSet, build_default_runtime_boundaries
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
        self.events: list[RuntimeEvent] = []
        self.telemetry = RuntimeTelemetryRecorder()
        self._app_factory = app_factory or App
        self._cil_client_factory = cil_client_factory or CILClient
        self._launcher_runner = launcher_runner or run_launcher
        self._app: App | None = None
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
        self._app = self._build_app()
        await self._app.setup()
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
        try:
            await asyncio.gather(
                self._app.brain_processor(),
                self._app.heart.scheduler_processor(),
                self._app.heart.housekeeping_processor(),
                self._app.heart.heartbeat_processor(),
                self._app.proprioceptor.run(),
            )
        finally:
            self._mark_all_components(
                RuntimeHealthStatus.STOPPING,
                "Runtime stopping",
                "service.stop",
            )
            await self._app.shutdown()

    def _build_app(self) -> App:
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
            system_issue_candidates = issue_snapshot["system_issue_candidates"]
            delivery_degraded = bool(
                int(background_status.get("pending_delivery_count", 0) or 0) > 0
                or int(metrics.get("gateway_delivery_failures_total", 0) or 0) > 0
            )
            tool_degraded = int(metrics.get("tool_failures_total", 0) or 0) > 0
            background_degraded = bool(system_issue_candidates)

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
                "Gateway delivery pending or failed"
                if delivery_degraded
                else "Gateway delivery healthy",
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
                        "存在网关投递失败或待补发消息" if delivery_degraded else "网关投递正常",
                        {
                            "gateway_delivery_attempts_total": int(metrics.get("gateway_delivery_attempts_total", 0) or 0),
                            "gateway_delivery_failures_total": int(metrics.get("gateway_delivery_failures_total", 0) or 0),
                            "background_pending_delivery_count": int(metrics.get("background_pending_delivery_count", 0) or 0),
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
