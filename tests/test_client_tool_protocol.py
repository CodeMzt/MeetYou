from __future__ import annotations

import unittest

from client_tool_sdk.protocol import (
    CLIENT_TOOL_PROTOCOL_SCHEMA,
    build_client_heartbeat,
    build_client_hello,
    build_client_tools_snapshot,
    build_tool_call_request,
)


class ClientToolProtocolTests(unittest.TestCase):
    def test_endpoint_lifecycle_frames_use_endpoint_schema(self):
        hello = build_client_hello(
            client_id="desktop-main",
            client_type="desktop",
            display_name="Desktop Main",
            transport_profile="desktop_wss",
            workspace_ids=["desktop-main"],
        )
        snapshot = build_client_tools_snapshot(
            client_id="desktop-main",
            tools=[{"tool_key": "file.read", "tool_id": "client.desktop-main.file.read"}],
            revision=2,
        )
        heartbeat = build_client_heartbeat(client_id="desktop-main", status="ready")

        self.assertEqual(hello["schema"], CLIENT_TOOL_PROTOCOL_SCHEMA)
        self.assertEqual(CLIENT_TOOL_PROTOCOL_SCHEMA, "meetyou.endpoint.ws.v4")
        self.assertEqual(hello["type"], "endpoint.hello")
        self.assertEqual(hello["endpoint_id"], "desktop.desktop-main.executor")
        self.assertEqual(hello["payload"]["provider"]["provider_id"], "desktop-main")
        self.assertEqual(hello["payload"]["endpoints"][0]["endpoint_id"], "desktop.desktop-main.ui")
        self.assertEqual(snapshot["type"], "endpoint.capabilities.snapshot")
        self.assertEqual(snapshot["payload"]["capabilities"][0]["tool_key"], "file.read")
        self.assertEqual(heartbeat["type"], "endpoint.heartbeat")

    def test_tool_call_request_targets_endpoint_and_tool_key(self):
        payload = build_tool_call_request(
            client_id="desktop.desktop-main.executor",
            message_id="msg_1",
            operation_id="op_1",
            call_id="call_1",
            workspace_id="desktop-main",
            tool_id="client.desktop-main.shell.exec",
            tool_key="shell.exec",
            arguments={"cmd": "echo ok"},
        )

        self.assertEqual(payload["schema"], CLIENT_TOOL_PROTOCOL_SCHEMA)
        self.assertEqual(payload["type"], "tool.call.request")
        self.assertEqual(payload["endpoint_id"], "desktop.desktop-main.executor")
        self.assertEqual(payload["payload"]["tool_key"], "shell.exec")
        self.assertNotIn("target_endpoint_id", payload["payload"])
        self.assertNotIn("target_" + "agent_id", payload["payload"])


if __name__ == "__main__":
    unittest.main()
