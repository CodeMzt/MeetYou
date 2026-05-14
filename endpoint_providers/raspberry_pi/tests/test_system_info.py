from __future__ import annotations

import unittest
from unittest.mock import patch

from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.capabilities.gpio import FakeGPIOBackend
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.capabilities.system_info import collect_system_info
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.config import RpiEndpointConfig


class SystemInfoTests(unittest.TestCase):
    def test_collect_system_info_does_not_require_temperature(self):
        with patch(
            "endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.capabilities.system_info._cpu_temperature_c",
            return_value=None,
        ):
            payload = collect_system_info()

        self.assertIn("hostname", payload)
        self.assertIn("platform", payload)
        self.assertIn("python", payload)
        self.assertIn("cpu_temperature_c", payload)
        self.assertIsNone(payload["cpu_temperature_c"])

    def test_collect_system_info_reports_endpoint_and_gpio_metadata(self):
        payload = collect_system_info(
            config=RpiEndpointConfig(endpoint_id="pi-lab"),
            gpio_backend=FakeGPIOBackend(),
        )

        self.assertEqual(payload["endpoint"]["endpoint_id"], "pi-lab")
        self.assertIn("version", payload["endpoint"])
        self.assertIn("git_commit", payload["endpoint"])
        self.assertEqual(payload["gpio"]["backend"], "fake")
        self.assertTrue(payload["gpio"]["available"])


if __name__ == "__main__":
    unittest.main()
