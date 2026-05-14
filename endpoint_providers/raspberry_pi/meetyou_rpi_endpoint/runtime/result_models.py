from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from endpoint_tool_sdk.protocol import utcnow_iso


@dataclass(frozen=True, slots=True)
class OperationRequest:
    operation_id: str
    call_id: str
    capability_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int | float | None = None
    correlation_id: str = ""


@dataclass(frozen=True, slots=True)
class OperationEvent:
    operation_id: str
    call_id: str
    capability_name: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    seq: int = 0
    timestamp: str = field(default_factory=utcnow_iso)

    @property
    def event_type(self) -> str:
        if self.status == "completed":
            return "operation.completed"
        if self.status == "failed":
            return "operation.failed"
        if self.status == "cancelled":
            return "operation.cancelled"
        return "operation.progress"

    def to_payload(self, *, endpoint_id: str = "") -> dict[str, Any]:
        payload = {
            "operation_id": self.operation_id,
            "call_id": self.call_id,
            "endpoint_id": endpoint_id,
            "capability_name": self.capability_name,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "status": self.status,
            "payload": dict(self.payload or {}),
        }
        if self.error is not None:
            payload["error"] = dict(self.error)
        return payload


@dataclass(frozen=True, slots=True)
class OperationFinal:
    operation_id: str
    call_id: str
    capability_name: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    seq: int = 0
    timestamp: str = field(default_factory=utcnow_iso)

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"

    def to_summary(self) -> dict[str, Any]:
        summary = {
            "operation_id": self.operation_id,
            "call_id": self.call_id,
            "capability_name": self.capability_name,
            "status": self.status,
            "seq": self.seq,
            "timestamp": self.timestamp,
        }
        if self.payload:
            summary["payload"] = dict(self.payload)
        if self.error is not None:
            summary["error"] = dict(self.error)
        return summary
