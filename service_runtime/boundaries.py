from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RuntimeModuleBoundary:
    name: str
    responsibility: str
    inbound_commands: tuple[str, ...]
    outbound_events: tuple[str, ...]
    dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "responsibility": self.responsibility,
            "inbound_commands": list(self.inbound_commands),
            "outbound_events": list(self.outbound_events),
            "dependencies": list(self.dependencies),
        }


@dataclass(slots=True)
class RuntimeModuleSet:
    session_execution: RuntimeModuleBoundary
    background_jobs: RuntimeModuleBoundary
    tool_execution: RuntimeModuleBoundary
    delivery: RuntimeModuleBoundary
    telemetry: RuntimeModuleBoundary

    def all(self) -> list[RuntimeModuleBoundary]:
        return [
            self.session_execution,
            self.background_jobs,
            self.tool_execution,
            self.delivery,
            self.telemetry,
        ]

    def names(self) -> list[str]:
        return [boundary.name for boundary in self.all()]

    def to_dict(self) -> dict[str, dict]:
        return {
            boundary.name: boundary.to_dict()
            for boundary in self.all()
        }


def build_default_runtime_boundaries() -> RuntimeModuleSet:
    return RuntimeModuleSet(
        session_execution=RuntimeModuleBoundary(
            name="session_execution",
            responsibility="Run session-scoped turns and preserve in-session ordering.",
            inbound_commands=("session.start", "session.resume", "session.cancel"),
            outbound_events=("session.accepted", "session.completed", "session.failed"),
            dependencies=("tool_execution", "delivery", "telemetry"),
        ),
        background_jobs=RuntimeModuleBoundary(
            name="background_jobs",
            responsibility="Run scheduler, heartbeat, housekeeping, and autonomous jobs.",
            inbound_commands=("job.enqueue", "job.retry", "job.cancel"),
            outbound_events=("job.started", "job.completed", "job.failed"),
            dependencies=("tool_execution", "delivery", "telemetry"),
        ),
        tool_execution=RuntimeModuleBoundary(
            name="tool_execution",
            responsibility="Resolve tools, apply policy, and wrap execution results.",
            inbound_commands=("tool.call", "tool.timeout", "tool.cancel"),
            outbound_events=("tool.succeeded", "tool.failed"),
            dependencies=("telemetry",),
        ),
        delivery=RuntimeModuleBoundary(
            name="delivery",
            responsibility="Deliver runtime events to gateway, websocket, and adapters.",
            inbound_commands=("delivery.enqueue", "delivery.flush", "delivery.retry"),
            outbound_events=("delivery.sent", "delivery.failed"),
            dependencies=("telemetry",),
        ),
        telemetry=RuntimeModuleBoundary(
            name="telemetry",
            responsibility="Publish health, metrics, and structured runtime diagnostics.",
            inbound_commands=("telemetry.capture", "health.refresh"),
            outbound_events=("health.updated", "runtime.error"),
        ),
    )
