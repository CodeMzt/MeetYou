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


@dataclass(slots=True)
class RuntimePlatformDependencyBoundary:
    name: str
    owner: str
    reason: str
    surfaces: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "owner": self.owner,
            "reason": self.reason,
            "surfaces": list(self.surfaces),
        }


@dataclass(slots=True)
class RuntimePlatformBoundarySet:
    retained_in_core: tuple[RuntimePlatformDependencyBoundary, ...]
    delegated_to_endpoint_providers: tuple[RuntimePlatformDependencyBoundary, ...]

    def to_dict(self) -> dict[str, list[dict[str, object]]]:
        return {
            "retained_in_core": [item.to_dict() for item in self.retained_in_core],
            "delegated_to_endpoint_providers": [item.to_dict() for item in self.delegated_to_endpoint_providers],
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


def build_runtime_platform_boundaries() -> RuntimePlatformBoundarySet:
    return RuntimePlatformBoundarySet(
        retained_in_core=(
            RuntimePlatformDependencyBoundary(
                name="runtime_host_detection",
                owner="core/service_runtime",
                reason="Core 只保留运行宿主机的平台识别，用于装配 host sensing 适配器与运行时健康观测。",
                surfaces=(
                    "core/app.py::App.__init__",
                    "platform_layer/detector.py::detect_platform",
                ),
            ),
            RuntimePlatformDependencyBoundary(
                name="runtime_host_observability",
                owner="core/service_runtime",
                reason="宿主机时间、系统生命体征与后台状态属于服务端运行所需的少量 platform 感知。",
                surfaces=(
                    "tools/system_tools.py::get_current_system_time",
                    "tools/system_tools.py::get_sys_vitals",
                    "tools/system_tools.py::get_background_status",
                ),
            ),
            RuntimePlatformDependencyBoundary(
                name="runtime_host_proprioception",
                owner="core/service_runtime",
                reason="运行宿主机 UI 焦点与进程感知仅作为上下文输入，不再承载任何本地终端执行能力。",
                surfaces=(
                    "sensors/proprioceptor.py::Proprioceptor.run",
                    "platform_layer/base.py::PlatformAdapter",
                ),
            ),
        ),
        delegated_to_endpoint_providers=(
            RuntimePlatformDependencyBoundary(
                name="terminal_shell_execution",
                owner="desktop_client/local_backend",
                reason="Shell 属于终端专属能力，Core 只做审计与 capability dispatch，不再直接持有平台 shell 抽象。",
                surfaces=(
                    "tools/system_tools.py::exec_sys_cmd",
                    "desktop_client/execution.py::build_shell_exec_handler",
                ),
            ),
            RuntimePlatformDependencyBoundary(
                name="terminal_file_and_workspace_io",
                owner="desktop_client/local_backend",
                reason="本地文件读写与工作区分析依赖终端文件系统，必须下沉到客户端本地后端。",
                surfaces=(
                    "tools/document_tools.py::DocumentTools",
                    "desktop_client/execution.py::build_file_read_handler",
                    "desktop_client/execution.py::build_file_write_handler",
                    "desktop_client/execution.py::build_workspace_analyze_handler",
                ),
            ),
            RuntimePlatformDependencyBoundary(
                name="terminal_local_mcp_runtime",
                owner="desktop_client/local_backend",
                reason="本地 MCP 生命周期依赖终端环境与本地进程，必须由客户端本地后端托管。",
                surfaces=(
                    "desktop_client/mcp_runtime.py::DesktopClientMCPRuntime",
                    "desktop_client/runtime.py::DesktopClientRuntime",
                ),
            ),
        ),
    )
