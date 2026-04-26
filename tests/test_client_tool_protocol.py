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
    def test_client_lifecycle_frames_use_client_schema(self):
        hello = build_client_hello(
            client_id="desktop-main",
            client_type="desktop",
            display_name="Desktop Main",
            transport_profile="desktop_wss",
            workspace_ids=["desktop-main"],
            available_tools=["file.read"],
            executable_tools=["file.read"],
        )
        snapshot = build_client_tools_snapshot(
            client_id="desktop-main",
            tools=[{"tool_key": "file.read", "tool_id": "client.desktop-main.file.read"}],
            revision=2,
        )
        heartbeat = build_client_heartbeat(client_id="desktop-main", status="ready")

        self.assertEqual(hello["schema"], CLIENT_TOOL_PROTOCOL_SCHEMA)
        self.assertEqual(hello["type"], "client.hello")
        self.assertEqual(hello["client_id"], "desktop-main")
        self.assertEqual(hello["payload"]["available_tools"], ["file.read"])
        self.assertEqual(snapshot["type"], "client.tools.snapshot")
        self.assertEqual(snapshot["payload"]["tools"][0]["tool_key"], "file.read")
        self.assertEqual(heartbeat["type"], "client.heartbeat")

    def test_tool_call_request_targets_client_and_tool_key(self):
        payload = build_tool_call_request(
            client_id="desktop-main",
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
        self.assertEqual(payload["client_id"], "desktop-main")
        self.assertEqual(payload["payload"]["tool_key"], "shell.exec")
        self.assertNotIn("target_agent_id", payload["payload"])


if __name__ == "__main__":
    unittest.main()
