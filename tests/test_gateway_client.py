from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlsplit

from clients.gateway_client import GatewayConversationClient


class GatewayConversationClientTests(unittest.TestCase):
    def test_client_ws_url_includes_stable_client_identity(self):
        client = GatewayConversationClient(
            base_url="http://127.0.0.1:8000",
            client_id="feishu-oc-test",
            client_type="feishu",
            display_name="Feishu OC Test",
            workspace_id="personal",
            thread_id="thr-1",
        )
        client.session_id = "sess-1"

        parsed = urlsplit(client._build_client_ws_url())
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.path, "/client/ws")
        self.assertEqual(query["thread_id"], ["thr-1"])
        self.assertEqual(query["session_id"], ["sess-1"])
        self.assertEqual(query["client_id"], ["feishu-oc-test"])
        self.assertEqual(query["client_type"], ["feishu"])
        self.assertEqual(query["display_name"], ["Feishu OC Test"])
        self.assertEqual(query["workspace_id"], ["personal"])


if __name__ == "__main__":
    unittest.main()
