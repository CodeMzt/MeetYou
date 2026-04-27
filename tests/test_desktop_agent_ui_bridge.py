from __future__ import annotations

import unittest
from types import SimpleNamespace

from desktop_client.config import DesktopClientConfig
from desktop_client.core_client import DesktopCoreClient
from desktop_client.desktop_api import DESKTOP_WS_PATH, LOCAL_BRIDGE_STATUS_PATH


class DesktopEndpointBridgeTests(unittest.TestCase):
    def test_local_desktop_ws_bridges_to_endpoint_ws(self):
        config = DesktopClientConfig(
            core_base_url="https://core.example.test",
            gateway_access_token="core-token",
            local_bridge_access_token="local-token",
        )
        request = SimpleNamespace(rel_url=SimpleNamespace(query_string="thread_id=thr_1&access_token=local-token"))
        core_client = DesktopCoreClient(config)

        url = core_client._build_core_ws_url(request, local_access_token="local-token")

        self.assertEqual(url, "wss://core.example.test/endpoint/ws?thread_id=thr_1")

    def test_desktop_local_surface_keeps_ui_paths_stable(self):
        self.assertEqual(LOCAL_BRIDGE_STATUS_PATH, "/desktop/status")
        self.assertEqual(DESKTOP_WS_PATH, "/desktop/ws")


if __name__ == "__main__":
    unittest.main()
