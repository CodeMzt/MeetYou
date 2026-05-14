from __future__ import annotations

import unittest

from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.config import RpiEndpointConfig
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.protocol import build_hello


class RpiProtocolTests(unittest.TestCase):
    def test_hello_uses_endpoint_ws_v4_and_single_executor(self):
        config = RpiEndpointConfig(endpoint_id="pi-lab", workspace_ids=["lab"])

        hello = build_hello(config)

        self.assertEqual(hello["schema"], "meetyou.endpoint.ws.v4")
        self.assertEqual(hello["type"], "endpoint.hello")
        self.assertEqual(hello["endpoint_id"], "rpi.pi-lab.executor")
        self.assertEqual(hello["payload"]["provider"]["provider_type"], "rpi")
        self.assertEqual(len(hello["payload"]["endpoints"]), 1)
        self.assertEqual(hello["payload"]["endpoints"][0]["roles"], ["execution"])


if __name__ == "__main__":
    unittest.main()

