from __future__ import annotations

import unittest

from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.capabilities.system_info import collect_system_info


class SystemInfoTests(unittest.TestCase):
    def test_collect_system_info_does_not_require_temperature(self):
        payload = collect_system_info()

        self.assertIn("hostname", payload)
        self.assertIn("platform", payload)
        self.assertIn("python", payload)
        self.assertIn("cpu_temperature_c", payload)


if __name__ == "__main__":
    unittest.main()

