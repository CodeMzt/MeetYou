from __future__ import annotations

import asyncio
import os
from pathlib import Path
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

    async def read(self, pin: int, *, pull: str | None = None) -> bool:
        normalized_pin = int(pin)
        if normalized_pin in self.values:
            return bool(self.values[normalized_pin])
        return str(pull or "").strip().lower() == "up"

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
    def __init__(
        self,
        *,
        code: str = "gpio_unavailable",
        message: str = "GPIO backend unavailable; install gpiozero/lgpio on Raspberry Pi OS or run with fake GPIO for tests",
    ):
        self.code = code
        self.message = message

    async def read(self, pin: int, *, pull: str | None = None) -> bool:
        del pin, pull
        raise CapabilityError(
            self.code,
            self.message,
            retryable=False,
        )

    async def write(self, pin: int, value: bool, *, duration_ms: int | None = None) -> dict[str, Any]:
        del pin, value, duration_ms
        raise CapabilityError(
            self.code,
            self.message,
            retryable=False,
        )


class GpioZeroBackend:
    def __init__(self, *, pin_factory_name: str | None = None, working_dir: str | None = None):
        try:
            from gpiozero import Device, DigitalInputDevice, DigitalOutputDevice
        except Exception as exc:
            raise CapabilityError(
                "gpio_backend_import_failed",
                "gpiozero is not available in this environment; install gpiozero and lgpio on Raspberry Pi OS",
                retryable=False,
            ) from exc
        self._pin_factory_name = _configure_gpiozero_pin_factory(
            Device,
            pin_factory_name,
            working_dir=working_dir,
        )
        self._input_cls = DigitalInputDevice
        self._output_cls = DigitalOutputDevice

    async def read(self, pin: int, *, pull: str | None = None) -> bool:
        device = self._open_input(pin, pull=pull)
        try:
            pin_obj = getattr(device, "pin", None)
            raw_state = getattr(pin_obj, "state", None)
            if raw_state is not None:
                return bool(raw_state)
            return bool(device.value)
        finally:
            device.close()

    async def write(self, pin: int, value: bool, *, duration_ms: int | None = None) -> dict[str, Any]:
        device = self._open_output(pin)
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
                "backend": f"gpiozero:{self._pin_factory_name}",
            }
        finally:
            device.close()

    def _open_input(self, pin: int, *, pull: str | None = None):
        try:
            pull_up = _gpiozero_pull_up(pull)
            kwargs: dict[str, Any] = {"pull_up": pull_up}
            if pull_up is None:
                kwargs["active_state"] = True
            return self._input_cls(int(pin), **kwargs)
        except Exception as exc:
            raise _gpiozero_runtime_error(exc, pin=pin, factory_name=self._pin_factory_name) from exc

    def _open_output(self, pin: int):
        try:
            return self._output_cls(int(pin))
        except Exception as exc:
            raise _gpiozero_runtime_error(exc, pin=pin, factory_name=self._pin_factory_name) from exc


def build_gpio_backend(*, force_fake: bool = False, working_dir: str | None = None):
    if force_fake or _env_truthy("MEETYOU_RPI_FAKE_GPIO"):
        return FakeGPIOBackend()
    try:
        return GpioZeroBackend(
            pin_factory_name=_select_gpio_pin_factory_name(),
            working_dir=working_dir,
        )
    except CapabilityError as exc:
        return UnavailableGPIOBackend(code=exc.code, message=exc.message)


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


def _select_gpio_pin_factory_name() -> str:
    configured = str(
        os.environ.get("MEETYOU_RPI_GPIO_PIN_FACTORY")
        or os.environ.get("GPIOZERO_PIN_FACTORY")
        or ""
    ).strip().lower()
    if configured:
        return configured
    if _looks_like_raspberry_pi():
        return "lgpio"
    return "default"


def _configure_gpiozero_pin_factory(Device, pin_factory_name: str | None, *, working_dir: str | None = None) -> str:
    name = str(pin_factory_name or "default").strip().lower() or "default"
    if name in {"default", "auto"}:
        return _pin_factory_label(getattr(Device, "pin_factory", None))
    if name == "lgpio":
        _ensure_lgpio_working_dir(working_dir)
        try:
            from gpiozero.pins.lgpio import LGPIOFactory
        except Exception as exc:
            raise CapabilityError(
                "gpio_lgpio_unavailable",
                (
                    "GPIO lgpio backend is unavailable; on Raspberry Pi 5 install python3-lgpio "
                    "or pip package lgpio, then set MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio. "
                    f"Import error: {type(exc).__name__}: {exc}"
                ),
                retryable=False,
            ) from exc
        try:
            Device.pin_factory = LGPIOFactory()
        except Exception as exc:
            raise CapabilityError(
                "gpio_lgpio_init_failed",
                f"GPIO lgpio backend failed to initialize: {exc}",
                retryable=False,
            ) from exc
        return "lgpio"
    raise CapabilityError(
        "gpio_pin_factory_unsupported",
        f"Unsupported GPIO pin factory: {name}",
        retryable=False,
    )


def _gpiozero_runtime_error(exc: Exception, *, pin: int, factory_name: str) -> CapabilityError:
    return CapabilityError(
        "gpio_backend_error",
        (
            f"GPIO backend gpiozero:{factory_name} failed for BCM pin {int(pin)}: {exc}. "
            "On Raspberry Pi 5 use lgpio: install python3-lgpio or pip package lgpio, "
            "and set MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio."
        ),
        retryable=False,
    )


def _pin_factory_label(pin_factory) -> str:
    if pin_factory is None:
        return "default"
    return pin_factory.__class__.__name__


def _looks_like_raspberry_pi() -> bool:
    for path in (Path("/proc/device-tree/model"), Path("/sys/firmware/devicetree/base/model")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if "raspberry pi" in text:
            return True
    return False


def _gpiozero_pull_up(pull: str | None) -> bool | None:
    normalized = str(pull or "").strip().lower()
    if normalized == "up":
        return True
    if normalized == "down":
        return False
    if normalized == "none":
        return None
    return None


def _ensure_lgpio_working_dir(working_dir: str | None) -> None:
    candidate = str(working_dir or "").strip()
    if not candidate:
        return
    path = Path(candidate)
    try:
        path.mkdir(parents=True, exist_ok=True)
        os.chdir(path)
    except OSError as exc:
        raise CapabilityError(
            "gpio_working_dir_unavailable",
            f"GPIO lgpio working directory is not usable: {path}: {exc}",
            retryable=False,
        ) from exc
