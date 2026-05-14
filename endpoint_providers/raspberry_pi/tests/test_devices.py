from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.config import (
    DeviceConfig,
    RpiConfigError,
    RpiEndpointConfig,
    SecurityConfig,
    load_rpi_endpoint_config,
)
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.registry import build_default_registry
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.runtime.operation_runner import OperationRunner
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.runtime.result_models import OperationRequest


class DeviceConfigTests(unittest.TestCase):
    def _write_config(self, root: Path, devices: list[dict]) -> Path:
        path = root / "rpi.json"
        path.write_text(
            json.dumps(
                {
                    "security": {"gpio_allowed_pins": [17, 27, 22], "safe_shell_enabled": False},
                    "devices": devices,
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_device_config_loads_successfully(self):
        with TemporaryDirectory() as tmp:
            path = self._write_config(
                Path(tmp),
                [
                    {
                        "device_id": "desk_led",
                        "type": "led",
                        "name": "Desk LED",
                        "pin": 17,
                        "direction": "out",
                        "active_high": True,
                    },
                    {
                        "device_id": "button_1",
                        "type": "button",
                        "name": "Desk Button",
                        "pin": 22,
                        "direction": "in",
                        "active_high": False,
                        "pull": "up",
                    },
                ],
            )

            config = load_rpi_endpoint_config(str(path))

        self.assertEqual([device.device_id for device in config.devices], ["desk_led", "button_1"])
        self.assertEqual(config.devices[1].pull, "up")

    def test_duplicate_device_id_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write_config(
                Path(tmp),
                [
                    {"device_id": "desk_led", "type": "led", "name": "Desk LED", "pin": 17, "direction": "out"},
                    {"device_id": "desk_led", "type": "led", "name": "Other LED", "pin": 27, "direction": "out"},
                ],
            )

            with self.assertRaises(RpiConfigError) as raised:
                load_rpi_endpoint_config(str(path))

        self.assertEqual(raised.exception.code, "duplicate_device_id")

    def test_device_pin_outside_allowlist_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write_config(
                Path(tmp),
                [
                    {"device_id": "desk_led", "type": "led", "name": "Desk LED", "pin": 5, "direction": "out"},
                ],
            )

            with self.assertRaises(RpiConfigError) as raised:
                load_rpi_endpoint_config(str(path))

        self.assertEqual(raised.exception.code, "device_pin_not_allowed")


class DeviceCapabilityTests(unittest.IsolatedAsyncioTestCase):
    def _registry(self, devices: list[DeviceConfig]):
        config = RpiEndpointConfig(
            core_access_token="super-secret-token",
            security=SecurityConfig(
                gpio_allowed_pins=[17, 27, 22],
                gpio_write_default_duration_ms=0,
            ),
            devices=devices,
        )
        registry = build_default_registry(config, force_fake_gpio=True)
        return registry, OperationRunner(registry)

    def _desk_led(self, **overrides) -> DeviceConfig:
        values = {
            "device_id": "desk_led",
            "type": "led",
            "name": "Desk LED",
            "pin": 17,
            "direction": "out",
            "active_high": True,
        }
        values.update(overrides)
        return DeviceConfig(**values)

    async def test_device_list_does_not_expose_secrets(self):
        registry, runner = self._registry([self._desk_led()])

        final = await runner.run(
            OperationRequest(
                operation_id="op-device-list",
                call_id="call-device-list",
                capability_name="rpi.device.list",
                arguments={},
            )
        )

        self.assertTrue(final.succeeded)
        self.assertIn("rpi.device.list", registry.names())
        self.assertIn("desk_led", json.dumps(final.payload))
        self.assertNotIn("super-secret-token", json.dumps(final.payload))

    async def test_device_set_works_with_fake_gpio(self):
        registry, runner = self._registry([self._desk_led()])

        set_result = await runner.run(
            OperationRequest(
                operation_id="op-device-set",
                call_id="call-device-set",
                capability_name="rpi.device.set",
                arguments={"device_id": "desk_led", "value": True},
            )
        )
        status_result = await runner.run(
            OperationRequest(
                operation_id="op-device-status",
                call_id="call-device-status",
                capability_name="rpi.device.status",
                arguments={"device_id": "desk_led"},
            )
        )

        self.assertTrue(set_result.succeeded)
        self.assertEqual(set_result.payload["backend"], "fake")
        self.assertTrue(status_result.payload["value"])
        self.assertTrue(registry.get("rpi.device.set") is not None)

    async def test_device_pulse_resets_output_after_duration(self):
        _, runner = self._registry([self._desk_led(max_on_ms=100)])

        pulse_result = await runner.run(
            OperationRequest(
                operation_id="op-device-pulse",
                call_id="call-device-pulse",
                capability_name="rpi.device.pulse",
                arguments={"device_id": "desk_led", "duration_ms": 1},
            )
        )
        status_result = await runner.run(
            OperationRequest(
                operation_id="op-device-status-after-pulse",
                call_id="call-device-status-after-pulse",
                capability_name="rpi.device.status",
                arguments={"device_id": "desk_led"},
            )
        )

        self.assertTrue(pulse_result.succeeded)
        self.assertTrue(pulse_result.payload["reset_performed"])
        self.assertFalse(status_result.payload["value"])

    async def test_device_blink_enforces_count_limit(self):
        _, runner = self._registry([self._desk_led(max_on_ms=100)])

        final = await runner.run(
            OperationRequest(
                operation_id="op-device-blink-count",
                call_id="call-device-blink-count",
                capability_name="rpi.device.blink",
                arguments={"device_id": "desk_led", "count": 21, "interval_ms": 1},
            )
        )

        self.assertEqual(final.status, "failed")
        self.assertEqual(final.error["code"], "invalid_device_blink")

    async def test_device_blink_enforces_duration_limit(self):
        _, runner = self._registry([self._desk_led(max_on_ms=100)])

        final = await runner.run(
            OperationRequest(
                operation_id="op-device-blink-duration",
                call_id="call-device-blink-duration",
                capability_name="rpi.device.blink",
                arguments={"device_id": "desk_led", "count": 2, "interval_ms": 101},
            )
        )

        self.assertEqual(final.status, "failed")
        self.assertEqual(final.error["code"], "invalid_device_blink")

    async def test_input_device_cannot_be_set(self):
        _, runner = self._registry(
            [
                DeviceConfig(
                    device_id="button_1",
                    type="button",
                    name="Button",
                    pin=22,
                    direction="in",
                    active_high=False,
                    pull="up",
                )
            ]
        )

        final = await runner.run(
            OperationRequest(
                operation_id="op-device-set-button",
                call_id="call-device-set-button",
                capability_name="rpi.device.set",
                arguments={"device_id": "button_1", "value": True},
            )
        )

        self.assertEqual(final.status, "failed")
        self.assertEqual(final.error["code"], "device_permission_denied")

    async def test_button_read_uses_input_device(self):
        _, runner = self._registry(
            [
                DeviceConfig(
                    device_id="button_1",
                    type="button",
                    name="Button",
                    pin=22,
                    direction="in",
                    active_high=False,
                    pull="up",
                )
            ]
        )

        final = await runner.run(
            OperationRequest(
                operation_id="op-button-read",
                call_id="call-button-read",
                capability_name="rpi.button.read",
                arguments={"device_id": "button_1"},
            )
        )

        self.assertTrue(final.succeeded)
        self.assertFalse(final.payload["value"])
        self.assertTrue(final.payload["raw_value"])

    def test_relay_requires_confirmation_by_default(self):
        registry, _ = self._registry(
            [
                DeviceConfig(
                    device_id="relay_1",
                    type="relay",
                    name="Relay",
                    pin=27,
                    direction="out",
                    active_high=True,
                )
            ]
        )

        definitions = {item["tool_key"]: item for item in registry.tool_definitions()}

        self.assertTrue(definitions["rpi.device.set"]["requires_confirmation"])
        self.assertTrue(definitions["rpi.device.pulse"]["requires_confirmation"])
        self.assertTrue(definitions["rpi.device.blink"]["requires_confirmation"])

    def test_relay_confirmation_can_be_explicitly_disabled(self):
        registry, _ = self._registry(
            [
                DeviceConfig(
                    device_id="relay_1",
                    type="relay",
                    name="Relay",
                    pin=27,
                    direction="out",
                    active_high=True,
                    requires_confirmation=False,
                )
            ]
        )

        definitions = {item["tool_key"]: item for item in registry.tool_definitions()}

        self.assertFalse(definitions["rpi.device.set"]["requires_confirmation"])


if __name__ == "__main__":
    unittest.main()
