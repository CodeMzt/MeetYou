from __future__ import annotations

import unittest

from endpoint_tool_sdk.protocol import (
    DEFAULT_ENDPOINT_TOOL_PROTOCOL_FEATURES,
    ENDPOINT_TOOL_PROTOCOL_SCHEMA,
    build_endpoint_capabilities_snapshot,
    build_endpoint_heartbeat,
    build_endpoint_hello,
    build_tool_call_cancel_message,
    build_tool_call_request,
)


class EndpointToolProtocolTests(unittest.TestCase):
    def test_endpoint_lifecycle_frames_use_endpoint_schema(self):
        hello = build_endpoint_hello(
            provider_id="desktop-main",
            provider_type="desktop",
            display_name="Desktop Main",
            transport_profile="desktop_wss",
            workspace_ids=["desktop-main"],
        )
        snapshot = build_endpoint_capabilities_snapshot(
            provider_id="desktop-main",
            capabilities=[{"tool_key": "file.read", "tool_id": "endpoint.desktop.desktop-main.executor.file.read"}],
            revision=2,
        )
        heartbeat = build_endpoint_heartbeat(provider_id="desktop-main", status="ready")

        self.assertEqual(hello["schema"], ENDPOINT_TOOL_PROTOCOL_SCHEMA)
        self.assertEqual(ENDPOINT_TOOL_PROTOCOL_SCHEMA, "meetyou.endpoint.ws.v4")
        self.assertEqual(hello["type"], "endpoint.hello")
        self.assertEqual(hello["endpoint_id"], "desktop.desktop-main.executor")
        self.assertEqual(hello["payload"]["provider"]["provider_id"], "desktop-main")
        self.assertEqual(hello["payload"]["endpoints"][0]["endpoint_id"], "desktop.desktop-main.ui")
        self.assertEqual(hello["payload"]["protocol"]["schema"], ENDPOINT_TOOL_PROTOCOL_SCHEMA)
        self.assertEqual(hello["payload"]["protocol"]["version"], 4)
        self.assertEqual(tuple(hello["payload"]["protocol"]["features"]), DEFAULT_ENDPOINT_TOOL_PROTOCOL_FEATURES)
        self.assertEqual(snapshot["type"], "endpoint.capabilities.snapshot")
        self.assertEqual(snapshot["payload"]["capabilities"][0]["tool_key"], "file.read")
        self.assertEqual(heartbeat["type"], "endpoint.heartbeat")

    def test_tool_call_request_targets_endpoint_and_tool_key(self):
        payload = build_tool_call_request(
            endpoint_id="desktop.desktop-main.executor",
            message_id="msg_1",
            operation_id="op_1",
            call_id="call_1",
            workspace_id="desktop-main",
            tool_id="endpoint.desktop.desktop-main.executor.shell.exec",
            tool_key="shell.exec",
            arguments={"cmd": "echo ok"},
        )

        self.assertEqual(payload["schema"], ENDPOINT_TOOL_PROTOCOL_SCHEMA)
        self.assertEqual(payload["type"], "tool.call.request")
        self.assertEqual(payload["endpoint_id"], "desktop.desktop-main.executor")
        self.assertEqual(payload["payload"]["tool_key"], "shell.exec")
        self.assertNotIn("target_endpoint_id", payload["payload"])
        self.assertNotIn("target_" + "agent_id", payload["payload"])

    def test_tool_call_cancel_uses_endpoint_protocol_schema(self):
        payload = build_tool_call_cancel_message(
            endpoint_id="desktop.desktop-main.executor",
            call_id="call_1",
            message_id="msg_cancel",
            reason="user requested stop",
        )

        self.assertEqual(payload["schema"], ENDPOINT_TOOL_PROTOCOL_SCHEMA)
        self.assertEqual(payload["type"], "tool.call.cancel")
        self.assertEqual(payload["endpoint_id"], "desktop.desktop-main.executor")
        self.assertEqual(payload["payload"]["call_id"], "call_1")
        self.assertEqual(payload["payload"]["reason"], "user requested stop")


if __name__ == "__main__":
    unittest.main()
