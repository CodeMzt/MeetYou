from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.capabilities.base import CapabilityError
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.capabilities.gpio import (
    GpioZeroBackend,
    UnavailableGPIOBackend,
    _configure_gpiozero_pin_factory,
    _ensure_lgpio_working_dir,
    _select_gpio_pin_factory_name,
)
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.config import (
    RpiEndpointConfig,
    SecurityConfig,
)
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.registry import build_default_registry
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.runtime.operation_runner import OperationRunner
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.runtime.result_models import OperationRequest


class GPIOTests(unittest.IsolatedAsyncioTestCase):
    def _runner(self):
        config = RpiEndpointConfig(
            security=SecurityConfig(
                gpio_allowed_pins=[17],
                gpio_write_default_duration_ms=0,
            )
        )
        registry = build_default_registry(config, force_fake_gpio=True)
        return OperationRunner(registry), registry

    async def test_rejects_pins_not_in_allowlist(self):
        runner, _ = self._runner()

        final = await runner.run(
            OperationRequest(
                operation_id="op-gpio-deny",
                call_id="call-gpio-deny",
                capability_name="rpi.gpio.read",
                arguments={"pin": 27},
            )
        )

        self.assertEqual(final.status, "failed")
        self.assertEqual(final.error["code"], "gpio_pin_not_allowed")

    async def test_fake_backend_write_then_read(self):
        runner, _ = self._runner()

        write_result = await runner.run(
            OperationRequest(
                operation_id="op-gpio-write",
                call_id="call-gpio-write",
                capability_name="rpi.gpio.write",
                arguments={"pin": 17, "value": True, "duration_ms": 0},
            )
        )
        read_result = await runner.run(
            OperationRequest(
                operation_id="op-gpio-read",
                call_id="call-gpio-read",
                capability_name="rpi.gpio.read",
                arguments={"pin": 17},
            )
        )

        self.assertTrue(write_result.succeeded)
        self.assertEqual(write_result.payload["backend"], "fake")
        self.assertTrue(read_result.payload["value"])

    async def test_fake_backend_duration_write_resets_low(self):
        runner, _ = self._runner()

        write_result = await runner.run(
            OperationRequest(
                operation_id="op-gpio-pulse",
                call_id="call-gpio-pulse",
                capability_name="rpi.gpio.write",
                arguments={"pin": 17, "value": True, "duration_ms": 1},
            )
        )
        read_result = await runner.run(
            OperationRequest(
                operation_id="op-gpio-read-after-pulse",
                call_id="call-gpio-read-after-pulse",
                capability_name="rpi.gpio.read",
                arguments={"pin": 17},
            )
        )

        self.assertTrue(write_result.succeeded)
        self.assertTrue(write_result.payload["reset_performed"])
        self.assertFalse(read_result.payload["value"])

    async def test_unavailable_backend_preserves_reason(self):
        backend = UnavailableGPIOBackend(code="gpio_lgpio_unavailable", message="install lgpio")

        with self.assertRaises(CapabilityError) as raised:
            await backend.write(17, True)

        self.assertEqual(raised.exception.code, "gpio_lgpio_unavailable")
        self.assertIn("install lgpio", raised.exception.message)

    async def test_default_unavailable_backend_message_names_gpiozero_and_lgpio(self):
        backend = UnavailableGPIOBackend()

        with self.assertRaises(CapabilityError) as raised:
            await backend.read(17)

        self.assertEqual(raised.exception.code, "gpio_unavailable")
        self.assertIn("gpiozero", raised.exception.message)
        self.assertIn("lgpio", raised.exception.message)

    async def test_gpiozero_read_sets_active_state_for_floating_inputs(self):
        calls: list[dict] = []

        class FakeInput:
            def __init__(self, pin, **kwargs):
                calls.append({"pin": pin, "kwargs": dict(kwargs)})
                self.pin = SimpleNamespace(state=True)
                self.value = False
                self.closed = False

            def close(self):
                self.closed = True

        backend = object.__new__(GpioZeroBackend)
        backend._input_cls = FakeInput
        backend._pin_factory_name = "lgpio"

        value = await backend.read(17)

        self.assertTrue(value)
        self.assertEqual(calls, [{"pin": 17, "kwargs": {"pull_up": None, "active_state": True}}])

    def test_gpiozero_pull_configured_inputs_do_not_override_active_state(self):
        calls: list[dict] = []

        class FakeInput:
            def __init__(self, pin, **kwargs):
                calls.append({"pin": pin, "kwargs": dict(kwargs)})

        backend = object.__new__(GpioZeroBackend)
        backend._input_cls = FakeInput
        backend._pin_factory_name = "lgpio"

        backend._open_input(17, pull="up")
        backend._open_input(27, pull="down")

        self.assertEqual(
            calls,
            [
                {"pin": 17, "kwargs": {"pull_up": True}},
                {"pin": 27, "kwargs": {"pull_up": False}},
            ],
        )

    def test_gpio_pin_factory_env_override(self):
        with patch.dict("os.environ", {"MEETYOU_RPI_GPIO_PIN_FACTORY": "lgpio"}, clear=True):
            self.assertEqual(_select_gpio_pin_factory_name(), "lgpio")

    def test_gpio_pin_factory_defaults_to_lgpio_on_raspberry_pi(self):
        with patch.dict("os.environ", {}, clear=True), patch(
            "endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.capabilities.gpio._looks_like_raspberry_pi",
            return_value=True,
        ):
            self.assertEqual(_select_gpio_pin_factory_name(), "lgpio")

    def test_lgpio_import_error_includes_underlying_exception(self):
        class Device:
            pin_factory = None

        with patch.dict("sys.modules", {"gpiozero.pins.lgpio": None}):
            with self.assertRaises(CapabilityError) as raised:
                _configure_gpiozero_pin_factory(Device, "lgpio", working_dir=None)

        self.assertEqual(raised.exception.code, "gpio_lgpio_unavailable")
        self.assertIn("Import error:", raised.exception.message)

    def test_lgpio_working_dir_changes_to_writable_directory(self):
        import os
        import tempfile

        original = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                _ensure_lgpio_working_dir(temp_dir)
                self.assertEqual(os.getcwd(), temp_dir)
            finally:
                os.chdir(original)


if __name__ == "__main__":
    unittest.main()
