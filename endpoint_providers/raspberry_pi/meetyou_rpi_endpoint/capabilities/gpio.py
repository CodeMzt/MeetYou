from __future__ import annotations

import asyncio
import os
from typing import Any

from .base import (
    CapabilityContext,
    CapabilityDefinition,
    CapabilityError,
)
from ..security import validate_gpio_pin


class FakeGPIOBackend:
    def __init__(self):
        self.values: dict[int, bool] = {}

    async def read(self, pin: int) -> bool:
        return bool(self.values.get(int(pin), False))

    async def write(self, pin: int, value: bool, *, duration_ms: int | None = None) -> dict[str, Any]:
        normalized_pin = int(pin)
        normalized_value = bool(value)
        self.values[normalized_pin] = normalized_value
        reset_performed = False
        if duration_ms is not None and int(duration_ms) > 0:
            await asyncio.sleep(int(duration_ms) / 1000.0)
            self.values[normalized_pin] = False
            reset_performed = True
        return {
            "pin": normalized_pin,
            "value": normalized_value,
            "duration_ms": duration_ms,
            "reset_performed": reset_performed,
            "backend": "fake",
        }


class UnavailableGPIOBackend:
    async def read(self, pin: int) -> bool:
        del pin
        raise CapabilityError(
            "gpio_unavailable",
            "GPIO backend unavailable; install gpiozero on Raspberry Pi OS or run with fake GPIO for tests",
            retryable=False,
        )

    async def write(self, pin: int, value: bool, *, duration_ms: int | None = None) -> dict[str, Any]:
        del pin, value, duration_ms
        raise CapabilityError(
            "gpio_unavailable",
            "GPIO backend unavailable; install gpiozero on Raspberry Pi OS or run with fake GPIO for tests",
            retryable=False,
        )


class GpioZeroBackend:
    def __init__(self):
        try:
            from gpiozero import DigitalInputDevice, DigitalOutputDevice
        except Exception as exc:
            raise CapabilityError(
                "gpio_backend_import_failed",
                "gpiozero is not available in this environment",
                retryable=False,
            ) from exc
        self._input_cls = DigitalInputDevice
        self._output_cls = DigitalOutputDevice

    async def read(self, pin: int) -> bool:
        device = self._input_cls(int(pin))
        try:
            return bool(device.value)
        finally:
            device.close()

    async def write(self, pin: int, value: bool, *, duration_ms: int | None = None) -> dict[str, Any]:
        device = self._output_cls(int(pin))
        normalized_value = bool(value)
        reset_performed = False
        try:
            device.value = 1 if normalized_value else 0
            if duration_ms is not None and int(duration_ms) > 0:
                await asyncio.sleep(int(duration_ms) / 1000.0)
                device.value = 0
                reset_performed = True
            return {
                "pin": int(pin),
                "value": normalized_value,
                "duration_ms": duration_ms,
                "reset_performed": reset_performed,
                "backend": "gpiozero",
            }
        finally:
            device.close()


def build_gpio_backend(*, force_fake: bool = False):
    if force_fake or _env_truthy("MEETYOU_RPI_FAKE_GPIO"):
        return FakeGPIOBackend()
    try:
        return GpioZeroBackend()
    except CapabilityError:
        return UnavailableGPIOBackend()


async def handle_gpio_read(arguments: dict[str, Any], context: CapabilityContext) -> dict[str, Any]:
    backend = context.gpio_backend or UnavailableGPIOBackend()
    pin = validate_gpio_pin(arguments.get("pin"), context.config.security.gpio_allowed_pins)
    value = await backend.read(pin)
    return {"pin": pin, "value": bool(value)}


async def handle_gpio_write(arguments: dict[str, Any], context: CapabilityContext) -> dict[str, Any]:
    backend = context.gpio_backend or UnavailableGPIOBackend()
    pin = validate_gpio_pin(arguments.get("pin"), context.config.security.gpio_allowed_pins)
    raw_value = arguments.get("value")
    if isinstance(raw_value, bool):
        value = raw_value
    elif isinstance(raw_value, int) and raw_value in {0, 1}:
        value = bool(raw_value)
    elif isinstance(raw_value, str) and raw_value in {"0", "1"}:
        value = bool(int(raw_value))
    else:
        raise CapabilityError("invalid_gpio_value", "GPIO value must be boolean, 0, or 1")

    duration_ms = arguments.get("duration_ms")
    if duration_ms is None:
        duration_ms = context.config.security.gpio_write_default_duration_ms
    try:
        normalized_duration = int(duration_ms) if duration_ms is not None else None
    except (TypeError, ValueError) as exc:
        raise CapabilityError("invalid_gpio_duration", "GPIO duration_ms must be an integer") from exc
    if normalized_duration is not None:
        normalized_duration = max(0, min(normalized_duration, 60_000))
    return await backend.write(pin, value, duration_ms=normalized_duration)


def build_gpio_read_capability() -> CapabilityDefinition:
    return CapabilityDefinition(
        name="rpi.gpio.read",
        description="Raspberry Pi GPIO Read",
        input_schema={
            "type": "object",
            "properties": {"pin": {"type": "integer"}},
            "required": ["pin"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"pin": {"type": "integer"}, "value": {"type": "boolean"}},
            "required": ["pin", "value"],
        },
        risk_level="read",
        requires_confirmation=False,
        handler=handle_gpio_read,
        safe_parallel=False,
        tags=("rpi", "gpio", "read"),
    )


def build_gpio_write_capability() -> CapabilityDefinition:
    return CapabilityDefinition(
        name="rpi.gpio.write",
        description="Raspberry Pi GPIO Write",
        input_schema={
            "type": "object",
            "properties": {
                "pin": {"type": "integer"},
                "value": {"type": ["boolean", "integer", "string"]},
                "duration_ms": {"type": "integer"},
            },
            "required": ["pin", "value"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "pin": {"type": "integer"},
                "value": {"type": "boolean"},
                "duration_ms": {"type": ["integer", "null"]},
                "reset_performed": {"type": "boolean"},
                "backend": {"type": "string"},
            },
            "required": ["pin", "value", "reset_performed", "backend"],
        },
        risk_level="local_write",
        requires_confirmation=True,
        handler=handle_gpio_write,
        safe_parallel=False,
        tags=("rpi", "gpio", "write"),
    )


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}
