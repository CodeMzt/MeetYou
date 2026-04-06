from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from core.status import utcnow_iso


def _new_id() -> str:
    return uuid4().hex


class RuntimeCommandKind(str, Enum):
    LIFECYCLE = "lifecycle"


class RuntimeEventKind(str, Enum):
    LIFECYCLE = "lifecycle"
    HEALTH = "health"
    ERROR = "error"


class RuntimeErrorCategory(str, Enum):
    RUNTIME = "runtime"
    VALIDATION = "validation"
    DEPENDENCY = "dependency"


class RuntimeHealthStatus(str, Enum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    ERROR = "error"


class RuntimeCommand(BaseModel):
    command_id: str = Field(default_factory=_new_id)
    kind: str = RuntimeCommandKind.LIFECYCLE.value
    target: str
    operation: str
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)

    @classmethod
    def launcher(cls) -> "RuntimeCommand":
        return cls(target="launcher", operation="start")

    @classmethod
    def service(cls) -> "RuntimeCommand":
        return cls(target="service", operation="start")

    @classmethod
    def cil(cls) -> "RuntimeCommand":
        return cls(target="cil", operation="start")


class RuntimeEvent(BaseModel):
    event_id: str = Field(default_factory=_new_id)
    kind: str
    source: str
    action: str = ""
    status: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    emitted_at: str = Field(default_factory=utcnow_iso)


class RuntimeError(BaseModel):
    code: str
    category: str = RuntimeErrorCategory.RUNTIME.value
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str = Field(default_factory=utcnow_iso)

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        *,
        code: str = "runtime_unhandled",
        category: str | RuntimeErrorCategory = RuntimeErrorCategory.RUNTIME.value,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> "RuntimeError":
        resolved_category = category.value if isinstance(category, RuntimeErrorCategory) else str(category)
        payload = dict(details or {})
        payload.setdefault("exception_type", type(exc).__name__)
        return cls(
            code=code,
            category=resolved_category,
            message=str(exc) or type(exc).__name__,
            retryable=retryable,
            details=payload,
        )


class RuntimeComponentHealth(BaseModel):
    name: str
    status: str = RuntimeHealthStatus.STARTING.value
    detail: str = ""
    last_event: str = ""
    updated_at: str = Field(default_factory=utcnow_iso)


class RuntimeHealthCheck(BaseModel):
    name: str
    status: str = RuntimeHealthStatus.STARTING.value
    detail: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    observed_at: str = Field(default_factory=utcnow_iso)


class RuntimeTelemetrySignal(BaseModel):
    code: str
    component: str
    severity: str = "info"
    message: str
    context: dict[str, str] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str = Field(default_factory=utcnow_iso)


class RuntimeHealth(BaseModel):
    service: str = "meetyou-runtime"
    version: str = "service-runtime-v1alpha1"
    status: str = RuntimeHealthStatus.STARTING.value
    live: bool = True
    ready: bool = False
    degraded: bool = False
    components: list[RuntimeComponentHealth] = Field(default_factory=list)
    checks: list[RuntimeHealthCheck] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    telemetry: list[RuntimeTelemetrySignal] = Field(default_factory=list)
    errors: list[RuntimeError] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utcnow_iso)

    @classmethod
    def from_component_names(cls, names: list[str]) -> "RuntimeHealth":
        return cls(
            components=[RuntimeComponentHealth(name=name) for name in names],
        )

    def set_component(
        self,
        name: str,
        status: str | RuntimeHealthStatus,
        detail: str = "",
        last_event: str = "",
    ) -> None:
        resolved_status = status.value if isinstance(status, RuntimeHealthStatus) else str(status)
        for component in self.components:
            if component.name == name:
                component.status = resolved_status
                component.detail = detail
                component.last_event = last_event
                component.updated_at = utcnow_iso()
                self._sync_status()
                return
        self.components.append(
            RuntimeComponentHealth(
                name=name,
                status=resolved_status,
                detail=detail,
                last_event=last_event,
            )
        )
        self._sync_status()

    def record_error(self, error: RuntimeError) -> None:
        self.errors.append(error)
        self.status = RuntimeHealthStatus.ERROR.value
        self.ready = False
        self.degraded = True
        self.updated_at = utcnow_iso()

    def set_check(
        self,
        name: str,
        status: str | RuntimeHealthStatus,
        detail: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        resolved_status = status.value if isinstance(status, RuntimeHealthStatus) else str(status)
        payload = dict(metadata or {})
        for check in self.checks:
            if check.name == name:
                check.status = resolved_status
                check.detail = detail
                check.metadata = payload
                check.observed_at = utcnow_iso()
                self.updated_at = utcnow_iso()
                return
        self.checks.append(
            RuntimeHealthCheck(
                name=name,
                status=resolved_status,
                detail=detail,
                metadata=payload,
            )
        )
        self.updated_at = utcnow_iso()

    def replace_metrics(self, metrics: dict[str, Any] | None) -> None:
        self.metrics = dict(metrics or {})
        self.updated_at = utcnow_iso()

    def replace_telemetry(self, telemetry: list[RuntimeTelemetrySignal] | list[dict[str, Any]] | None) -> None:
        self.telemetry = [
            item if isinstance(item, RuntimeTelemetrySignal) else RuntimeTelemetrySignal(**item)
            for item in (telemetry or [])
        ]
        self.updated_at = utcnow_iso()

    def _sync_status(self) -> None:
        statuses = [component.status for component in self.components]
        if any(status == RuntimeHealthStatus.ERROR.value for status in statuses):
            self.status = RuntimeHealthStatus.ERROR.value
            self.ready = False
            self.degraded = True
        elif any(status == RuntimeHealthStatus.DEGRADED.value for status in statuses):
            self.status = RuntimeHealthStatus.DEGRADED.value
            self.ready = False
            self.degraded = True
        elif statuses and all(status == RuntimeHealthStatus.READY.value for status in statuses):
            self.status = RuntimeHealthStatus.READY.value
            self.ready = True
            self.degraded = False
        elif any(status == RuntimeHealthStatus.STOPPING.value for status in statuses):
            self.status = RuntimeHealthStatus.STOPPING.value
            self.ready = False
            self.degraded = False
        else:
            self.status = RuntimeHealthStatus.STARTING.value
            self.ready = False
            self.degraded = False
        self.updated_at = utcnow_iso()
