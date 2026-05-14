from __future__ import annotations

import asyncio
from typing import Any

from .base import (
    CapabilityContext,
    CapabilityDefinition,
    CapabilityError,
)
from .gpio import UnavailableGPIOBackend
from ..devices import DeviceRegistry, device_public_dict
from ..security import validate_gpio_pin


DEFAULT_DEVICE_MAX_ON_MS = 5_000
MAX_BLINK_COUNT = 20
MAX_BLINK_INTERVAL_MS = 10_000
MAX_BLINK_TOTAL_MS = 60_000


async def handle_device_list(arguments: dict[str, Any], context: CapabilityContext) -> dict[str, Any]:
    del arguments
    registry = _device_registry(context)
    return {"devices": [device_public_dict(device) for device in registry.list()]}


async def handle_device_status(arguments: dict[str, Any], context: CapabilityContext) -> dict[str, Any]:
    device = _require_device(arguments.get("device_id"), context)
    backend = _gpio_backend(context)
    _validate_device_pin(device, context)
    raw_value = await backend.read(device.pin, pull=device.pull)
    payload = device_public_dict(device)
    payload.update(
        {
            "value": _logical_value(device, raw_value),
            "raw_value": bool(raw_value),
        }
    )
    return payload


async def handle_device_set(arguments: dict[str, Any], context: CapabilityContext) -> dict[str, Any]:
    device = _require_output_device(arguments.get("device_id"), context)
    value = _parse_bool(arguments.get("value"), code="invalid_device_value", label="device value")
    result = await _write_logical(device, value, context)
    payload = device_public_dict(device)
    payload.update(
        {
            "value": value,
            "raw_value": _physical_value(device, value),
            "backend": str(result.get("backend") or "unknown"),
        }
    )
    return payload


async def handle_device_pulse(arguments: dict[str, Any], context: CapabilityContext) -> dict[str, Any]:
    device = _require_output_device(arguments.get("device_id"), context)
    duration_ms = _duration_ms(
        arguments.get("duration_ms"),
        code="invalid_device_duration",
        label="duration_ms",
        maximum=device.max_on_ms or DEFAULT_DEVICE_MAX_ON_MS,
    )
    on_result = await _write_logical(device, True, context)
    try:
        await asyncio.sleep(duration_ms / 1000.0)
    finally:
        off_result = await _write_logical(device, False, context)
    payload = device_public_dict(device)
    payload.update(
        {
            "value": False,
            "duration_ms": duration_ms,
            "reset_performed": True,
            "backend": str(off_result.get("backend") or on_result.get("backend") or "unknown"),
        }
    )
    return payload


async def handle_device_blink(arguments: dict[str, Any], context: CapabilityContext) -> dict[str, Any]:
    device = _require_output_device(arguments.get("device_id"), context)
    count = _bounded_int(
        arguments.get("count"),
        code="invalid_device_blink",
        label="count",
        minimum=1,
        maximum=MAX_BLINK_COUNT,
    )
    interval_ms = _bounded_int(
        arguments.get("interval_ms"),
        code="invalid_device_blink",
        label="interval_ms",
        minimum=1,
        maximum=MAX_BLINK_INTERVAL_MS,
    )
    per_on_max = device.max_on_ms or DEFAULT_DEVICE_MAX_ON_MS
    if interval_ms > per_on_max:
        raise CapabilityError(
            "invalid_device_blink",
            f"interval_ms must be <= {per_on_max} for device {device.device_id}",
        )
    conservative_total_ms = count * interval_ms * 2
    if conservative_total_ms > MAX_BLINK_TOTAL_MS:
        raise CapabilityError(
            "invalid_device_blink",
            f"blink total duration must be <= {MAX_BLINK_TOTAL_MS} ms",
        )

    last_result: dict[str, Any] = {}
    try:
        for index in range(count):
            last_result = await _write_logical(device, True, context)
            await asyncio.sleep(interval_ms / 1000.0)
            last_result = await _write_logical(device, False, context)
            if index < count - 1:
                await asyncio.sleep(interval_ms / 1000.0)
    finally:
        last_result = await _write_logical(device, False, context)

    payload = device_public_dict(device)
    payload.update(
        {
            "value": False,
            "count": count,
            "interval_ms": interval_ms,
            "max_total_duration_ms": conservative_total_ms,
            "backend": str(last_result.get("backend") or "unknown"),
        }
    )
    return payload


async def handle_button_read(arguments: dict[str, Any], context: CapabilityContext) -> dict[str, Any]:
    device = _require_device(arguments.get("device_id"), context)
    if device.direction != "in" or device.type != "button":
        raise CapabilityError(
            "device_permission_denied",
            f"device {device.device_id} is not a button input device",
        )
    return await handle_device_status({"device_id": device.device_id}, context)


def build_device_list_capability() -> CapabilityDefinition:
    return CapabilityDefinition(
        name="rpi.device.list",
        description="Raspberry Pi Device List",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={
            "type": "object",
            "properties": {"devices": {"type": "array"}},
            "required": ["devices"],
        },
        risk_level="read",
        requires_confirmation=False,
        handler=handle_device_list,
        safe_parallel=True,
        tags=("rpi", "device", "read"),
    )


def build_device_status_capability() -> CapabilityDefinition:
    return CapabilityDefinition(
        name="rpi.device.status",
        description="Raspberry Pi Device Status",
        input_schema={
            "type": "object",
            "properties": {"device_id": {"type": "string"}},
            "required": ["device_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        risk_level="read",
        requires_confirmation=False,
        handler=handle_device_status,
        safe_parallel=False,
        tags=("rpi", "device", "read"),
    )


def build_device_set_capability(*, requires_confirmation: bool) -> CapabilityDefinition:
    return CapabilityDefinition(
        name="rpi.device.set",
        description="Raspberry Pi Device Set",
        input_schema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "value": {"type": ["boolean", "integer", "string"]},
            },
            "required": ["device_id", "value"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        risk_level="local_write",
        requires_confirmation=requires_confirmation,
        handler=handle_device_set,
        safe_parallel=False,
        tags=("rpi", "device", "write"),
    )


def build_device_pulse_capability(*, requires_confirmation: bool) -> CapabilityDefinition:
    return CapabilityDefinition(
        name="rpi.device.pulse",
        description="Raspberry Pi Device Pulse",
        input_schema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "duration_ms": {"type": "integer"},
            },
            "required": ["device_id", "duration_ms"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        risk_level="local_write",
        requires_confirmation=requires_confirmation,
        handler=handle_device_pulse,
        safe_parallel=False,
        tags=("rpi", "device", "write"),
    )


def build_device_blink_capability(*, requires_confirmation: bool) -> CapabilityDefinition:
    return CapabilityDefinition(
        name="rpi.device.blink",
        description="Raspberry Pi Device Blink",
        input_schema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "count": {"type": "integer"},
                "interval_ms": {"type": "integer"},
            },
            "required": ["device_id", "count", "interval_ms"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        risk_level="local_write",
        requires_confirmation=requires_confirmation,
        handler=handle_device_blink,
        safe_parallel=False,
        tags=("rpi", "device", "write"),
    )


def build_button_read_capability() -> CapabilityDefinition:
    return CapabilityDefinition(
        name="rpi.button.read",
        description="Raspberry Pi Button Read",
        input_schema={
            "type": "object",
            "properties": {"device_id": {"type": "string"}},
            "required": ["device_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        risk_level="read",
        requires_confirmation=False,
        handler=handle_button_read,
        safe_parallel=False,
        tags=("rpi", "device", "button", "read"),
    )


def _device_registry(context: CapabilityContext) -> DeviceRegistry:
    registry = context.device_registry
    if isinstance(registry, DeviceRegistry):
        return registry
    return DeviceRegistry.from_config(context.config)


def _gpio_backend(context: CapabilityContext):
    return context.gpio_backend or UnavailableGPIOBackend()


def _require_device(device_id: Any, context: CapabilityContext):
    normalized = str(device_id or "").strip()
    if not normalized:
        raise CapabilityError("invalid_device_id", "device_id is required")
    device = _device_registry(context).get(normalized)
    if device is None:
        raise CapabilityError("device_not_found", f"unknown Raspberry Pi device_id: {normalized}")
    return device


def _require_output_device(device_id: Any, context: CapabilityContext):
    device = _require_device(device_id, context)
    if device.direction != "out":
        raise CapabilityError(
            "device_permission_denied",
            f"device {device.device_id} has direction={device.direction}; write operation requires direction=out",
        )
    return device


def _validate_device_pin(device, context: CapabilityContext) -> int:
    return validate_gpio_pin(device.pin, context.config.security.gpio_allowed_pins)


async def _write_logical(device, value: bool, context: CapabilityContext) -> dict[str, Any]:
    backend = _gpio_backend(context)
    pin = _validate_device_pin(device, context)
    return await backend.write(pin, _physical_value(device, value), duration_ms=0)


def _logical_value(device, raw_value: bool) -> bool:
    raw = bool(raw_value)
    return raw if device.active_high else not raw


def _physical_value(device, logical_value: bool) -> bool:
    value = bool(logical_value)
    return value if device.active_high else not value


def _parse_bool(value: Any, *, code: str, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "high"}:
            return True
        if normalized in {"0", "false", "no", "off", "low"}:
            return False
    raise CapabilityError(code, f"{label} must be boolean, 0, 1, on, or off")


def _duration_ms(value: Any, *, code: str, label: str, maximum: int) -> int:
    return _bounded_int(value, code=code, label=label, minimum=1, maximum=int(maximum))


def _bounded_int(value: Any, *, code: str, label: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise CapabilityError(code, f"{label} must be an integer") from exc
    if number < minimum or number > maximum:
        raise CapabilityError(code, f"{label} must be between {minimum} and {maximum}")
    return number
