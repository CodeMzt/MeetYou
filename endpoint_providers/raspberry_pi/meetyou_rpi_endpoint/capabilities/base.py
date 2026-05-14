from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from endpoint_tool_sdk.tool_ids import build_endpoint_tool_id


class CapabilityError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = str(code or "capability_error")
        self.message = str(message or "Capability failed")
        self.retryable = retryable


class GPIOBackend(Protocol):
    async def read(self, pin: int, *, pull: str | None = None) -> bool:
        raise NotImplementedError

    async def write(self, pin: int, value: bool, *, duration_ms: int | None = None) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(slots=True)
class CapabilityContext:
    config: Any
    gpio_backend: GPIOBackend | None = None
    device_registry: Any | None = None


CapabilityHandler = Callable[[dict[str, Any], CapabilityContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: str
    requires_confirmation: bool
    handler: CapabilityHandler
    safe_parallel: bool = True
    tags: tuple[str, ...] = ("rpi",)

    def to_tool_definition(self, *, endpoint_id: str, workspace_ids: list[str], max_concurrency: int = 1) -> dict[str, Any]:
        return {
            "tool_id": build_endpoint_tool_id(endpoint_id, self.name),
            "tool_key": self.name,
            "kind": "tool",
            "title": self.description,
            "tags": list(self.tags),
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "safe_parallel": self.safe_parallel,
            "max_concurrency": max(1, int(max_concurrency)),
            "workspace_ids": list(workspace_ids or []),
            "input_schema": dict(self.input_schema or {}),
            "output_schema": dict(self.output_schema or {}),
        }
