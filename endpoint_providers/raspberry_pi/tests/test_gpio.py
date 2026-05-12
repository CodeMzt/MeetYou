from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()

