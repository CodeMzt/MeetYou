from __future__ import annotations

from typing import Iterable

from .config import DeviceConfig, RpiConfigError


class DeviceRegistry:
    def __init__(self, devices: Iterable[DeviceConfig], *, allowed_pins: list[int]):
        self._allowed_pins = {int(pin) for pin in allowed_pins}
        self._devices: dict[str, DeviceConfig] = {}
        for device in devices or []:
            self._register(device)

    @classmethod
    def from_config(cls, config) -> "DeviceRegistry":
        return cls(
            getattr(config, "devices", []),
            allowed_pins=list(getattr(getattr(config, "security", None), "gpio_allowed_pins", []) or []),
        )

    def list(self) -> list[DeviceConfig]:
        return [self._devices[device_id] for device_id in sorted(self._devices)]

    def get(self, device_id: str) -> DeviceConfig | None:
        return self._devices.get(str(device_id or "").strip())

    def requires_confirmation_for_writes(self) -> bool:
        return any(
            device.direction == "out" and device.effective_requires_confirmation
            for device in self._devices.values()
        )

    def _register(self, device: DeviceConfig) -> None:
        device_id = str(device.device_id or "").strip()
        if not device_id:
            raise RpiConfigError("invalid_device_id", "device_id is required")
        if device_id in self._devices:
            raise RpiConfigError("duplicate_device_id", f"duplicate Raspberry Pi device_id: {device_id}")
        if int(device.pin) not in self._allowed_pins:
            raise RpiConfigError(
                "device_pin_not_allowed",
                f"device {device_id} pin {int(device.pin)} is not listed in security.gpio_allowed_pins",
            )
        if device.direction not in {"in", "out"}:
            raise RpiConfigError("invalid_device_direction", f"device {device_id} direction must be in or out")
        if device.direction == "in" and device.type in {"led", "relay", "output"}:
            raise RpiConfigError("device_direction_mismatch", f"device {device_id} type {device.type} requires direction=out")
        if device.direction == "out" and device.type in {"button", "input"}:
            raise RpiConfigError("device_direction_mismatch", f"device {device_id} type {device.type} requires direction=in")
        self._devices[device_id] = device


def device_public_dict(device: DeviceConfig) -> dict[str, object]:
    payload: dict[str, object] = {
        "device_id": device.device_id,
        "type": device.type,
        "name": device.name,
        "pin": int(device.pin),
        "direction": device.direction,
        "active_high": bool(device.active_high),
    }
    if device.max_on_ms is not None:
        payload["max_on_ms"] = int(device.max_on_ms)
    if device.direction == "out":
        payload["requires_confirmation"] = device.effective_requires_confirmation
    if device.pull is not None:
        payload["pull"] = device.pull
    return payload
