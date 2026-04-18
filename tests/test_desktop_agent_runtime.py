from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from core.credential_transport import encrypt_json_payload
from desktop_agent.config import DesktopAgentConfig, load_desktop_agent_config
from desktop_agent.protocol import build_capabilities_snapshot, build_heartbeat, build_hello, build_static_capabilities
from desktop_agent.runtime import DesktopAgentRuntime


class DesktopAgentRuntimeTests(unittest.TestCase):
    def test_load_desktop_agent_config_from_file_and_env(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "desktop_agent.json"
            config_path.write_text(
                json.dumps(
                    {
                        "core_base_url": "http://192.168.1.50:8000",
                        "agent_id": "desktop-main-agent",
                        "display_name": "Desktop Main Agent",
                        "workspace_ids": ["personal", "study"],
                    }
                ),
                encoding="utf-8",
            )
            old = os.environ.get("MEETYOU_AGENT_ACCESS_TOKEN")
            old_gateway = os.environ.get("MEETYOU_GATEWAY_ACCESS_TOKEN")
            os.environ["MEETYOU_AGENT_ACCESS_TOKEN"] = "agent-secret"
            os.environ.pop("MEETYOU_GATEWAY_ACCESS_TOKEN", None)
            previous_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                config = load_desktop_agent_config(str(config_path))
            finally:
                os.chdir(previous_cwd)
                if old is None:
                    os.environ.pop("MEETYOU_AGENT_ACCESS_TOKEN", None)
                else:
                    os.environ["MEETYOU_AGENT_ACCESS_TOKEN"] = old
                if old_gateway is None:
                    os.environ.pop("MEETYOU_GATEWAY_ACCESS_TOKEN", None)
                else:
                    os.environ["MEETYOU_GATEWAY_ACCESS_TOKEN"] = old_gateway

            self.assertEqual(config.core_base_url, "http://192.168.1.50:8000")
            self.assertEqual(config.agent_id, "desktop-main-agent")
            self.assertEqual(config.workspace_ids, ["personal", "study"])
            self.assertEqual(config.agent_access_token, "agent-secret")
            self.assertEqual(config.gateway_access_token, "agent-secret")
            self.assertEqual(config.owner_client_id, "desktop-app")
            self.assertEqual(config.websocket_url, "ws://192.168.1.50:8000/agent/ws")
            self.assertTrue(config.local_bridge_enabled)
            self.assertEqual(config.local_bridge_host, "127.0.0.1")
            self.assertEqual(config.local_bridge_port, 38951)
            self.assertEqual(config.local_bridge_base_url, "http://127.0.0.1:38951")

    def test_load_desktop_agent_config_prefers_gateway_token_for_ui_bridge(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "desktop_agent.json"
            config_path.write_text(
                json.dumps(
                    {
                        "core_base_url": "http://127.0.0.1:8000",
                        "agent_access_token": "agent-from-file",
                        "gateway_access_token": "gateway-from-file",
                    }
                ),
                encoding="utf-8",
            )
            old_agent = os.environ.get("MEETYOU_AGENT_ACCESS_TOKEN")
            old_gateway = os.environ.get("MEETYOU_GATEWAY_ACCESS_TOKEN")
            os.environ.pop("MEETYOU_AGENT_ACCESS_TOKEN", None)
            os.environ.pop("MEETYOU_GATEWAY_ACCESS_TOKEN", None)
            previous_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                config = load_desktop_agent_config(str(config_path))
            finally:
                os.chdir(previous_cwd)
                if old_agent is None:
                    os.environ.pop("MEETYOU_AGENT_ACCESS_TOKEN", None)
                else:
                    os.environ["MEETYOU_AGENT_ACCESS_TOKEN"] = old_agent
                if old_gateway is None:
                    os.environ.pop("MEETYOU_GATEWAY_ACCESS_TOKEN", None)
                else:
                    os.environ["MEETYOU_GATEWAY_ACCESS_TOKEN"] = old_gateway

        self.assertEqual(config.agent_access_token, "agent-from-file")
        self.assertEqual(config.gateway_access_token, "gateway-from-file")

    def test_load_desktop_agent_config_reads_gateway_token_from_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "desktop_agent.json"
            env_path = Path(tmp_dir) / ".env"
            config_path.write_text(
                json.dumps(
                    {
                        "core_base_url": "http://127.0.0.1:8000",
                        "agent_access_token": "agent-from-file",
                    }
                ),
                encoding="utf-8",
            )
            env_path.write_text("MEETYOU_GATEWAY_ACCESS_TOKEN=gateway-from-dotenv\n", encoding="utf-8")

            previous_cwd = Path.cwd()
            previous_agent = os.environ.get("MEETYOU_AGENT_ACCESS_TOKEN")
            previous_gateway = os.environ.get("MEETYOU_GATEWAY_ACCESS_TOKEN")
            os.chdir(tmp_dir)
            os.environ.pop("MEETYOU_AGENT_ACCESS_TOKEN", None)
            os.environ.pop("MEETYOU_GATEWAY_ACCESS_TOKEN", None)
            try:
                config = load_desktop_agent_config(str(config_path))
            finally:
                os.chdir(previous_cwd)
                if previous_agent is None:
                    os.environ.pop("MEETYOU_AGENT_ACCESS_TOKEN", None)
                else:
                    os.environ["MEETYOU_AGENT_ACCESS_TOKEN"] = previous_agent
                if previous_gateway is None:
                    os.environ.pop("MEETYOU_GATEWAY_ACCESS_TOKEN", None)
                else:
                    os.environ["MEETYOU_GATEWAY_ACCESS_TOKEN"] = previous_gateway

        self.assertEqual(config.agent_access_token, "gateway-from-dotenv")
        self.assertEqual(config.gateway_access_token, "gateway-from-dotenv")

    def test_protocol_builders_include_expected_agent_payloads(self):
        config = load_desktop_agent_config()
        capabilities = build_static_capabilities(config)
        hello = build_hello(config)
        snapshot = build_capabilities_snapshot(config, revision=2)
        heartbeat = build_heartbeat(config, metrics={"cpu_percent": 10.0})

        self.assertEqual(len(capabilities), 5)
        self.assertEqual(capabilities[0]["capability_id"], f"agent.{config.agent_id}.utility.echo")
        self.assertEqual(hello["type"], "agent.hello")
        self.assertEqual(hello["payload"]["owner_client_id"], config.owner_client_id)
        self.assertEqual(snapshot["payload"]["revision"], 2)
        self.assertEqual(snapshot["payload"]["capabilities"][0]["workspace_ids"], config.workspace_ids)
        self.assertEqual(heartbeat["type"], "agent.heartbeat")
        self.assertEqual(heartbeat["payload"]["metrics"]["cpu_percent"], 10.0)

    def test_runtime_handles_call_request_with_echo_handler(self):
        config = load_desktop_agent_config()
        runtime = DesktopAgentRuntime(config)

        class _FakeWs:
            def __init__(self):
                self.sent = []

            async def send_json(self, payload):
                self.sent.append(payload)

        ws = _FakeWs()
        asyncio.run(
            runtime._handle_call_request(
                ws,
                {
                    "schema": "meetyou.agent.v1",
                    "type": "capability.call.request",
                    "message_id": "dispatch-1",
                    "payload": {
                        "call_id": "call-1",
                        "capability_id": f"agent.{config.agent_id}.utility.echo",
                        "arguments": {"text": "hello-agent"},
                    },
                },
                object(),
            )
        )
        self.assertEqual([item["type"] for item in ws.sent], [
            "capability.call.accepted",
            "capability.call.progress",
            "capability.call.result",
        ])
        self.assertEqual(ws.sent[-1]["payload"]["result"]["echo"], "hello-agent")

    def test_runtime_decrypts_encrypted_call_arguments(self):
        config = load_desktop_agent_config()
        runtime = DesktopAgentRuntime(config)

        class _FakeWs:
            def __init__(self):
                self.sent = []

            async def send_json(self, payload):
                self.sent.append(payload)

        ws = _FakeWs()
        old_secret = os.environ.get("MEETYOU_CREDENTIAL_SECRET")
        os.environ["MEETYOU_CREDENTIAL_SECRET"] = "desktop-agent-test-secret"
        try:
            asyncio.run(
                runtime._handle_call_request(
                    ws,
                    {
                        "schema": "meetyou.agent.v1",
                        "type": "capability.call.request",
                        "message_id": "dispatch-encrypted",
                        "payload": {
                            "call_id": "call-encrypted",
                            "capability_id": f"agent.{config.agent_id}.utility.echo",
                            "arguments": {"token": "[REDACTED]"},
                            "encrypted_arguments": encrypt_json_payload(
                                {"text": "hello-encrypted", "token": "secret-token"},
                                purpose="agent.capability.arguments.v1",
                            ),
                        },
                    },
                    object(),
                )
            )
        finally:
            if old_secret is None:
                os.environ.pop("MEETYOU_CREDENTIAL_SECRET", None)
            else:
                os.environ["MEETYOU_CREDENTIAL_SECRET"] = old_secret

        self.assertEqual(ws.sent[-1]["payload"]["result"]["echo"], "hello-encrypted")

    def test_runtime_accepts_agent_message_from_core(self):
        config = load_desktop_agent_config()
        runtime = DesktopAgentRuntime(config)

        class _FakeWs:
            def __init__(self):
                self.sent = []

            async def send_json(self, payload):
                self.sent.append(payload)

        ws = _FakeWs()
        ready_received = asyncio.run(
            runtime._handle_server_message(
                {
                    "schema": "meetyou.agent.v1",
                    "type": "agent.message",
                    "message_id": "core-message-1",
                    "agent_id": config.agent_id,
                    "payload": {
                        "session_id": "system:agent:desktop-main-agent",
                        "event_type": "message",
                        "role": "assistant",
                        "content": "欢迎接入，我这边已准备好后续协作。",
                        "stream_id": "",
                        "metadata": {"trigger": "agent_connected"},
                    },
                },
                False,
                ws,
                object(),
            )
        )

        self.assertFalse(ready_received)
        self.assertEqual(ws.sent, [])

    def test_runtime_handles_file_read_write_and_shell_exec(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                sample = root / "sample.txt"
                sample.write_text("hello file read", encoding="utf-8")
                config = DesktopAgentConfig(
                    core_base_url="http://127.0.0.1:8000",
                    agent_id="desktop-main-agent",
                    display_name="Desktop Main Agent",
                    workspace_ids=["personal"],
                    read_roots=["."],
                    trusted_write_roots=["."],
                    cmd_policy_path="missing.json",
                    command_timeout_seconds=30,
                )
                runtime = DesktopAgentRuntime(config)

                class _FakeWs:
                    def __init__(self):
                        self.sent = []

                    async def send_json(self, payload):
                        self.sent.append(payload)

                # file.read
                read_ws = _FakeWs()
                asyncio.run(
                    runtime._handle_call_request(
                        read_ws,
                        {
                            "schema": "meetyou.agent.v1",
                            "type": "capability.call.request",
                            "message_id": "dispatch-read",
                            "payload": {
                                "call_id": "call-read",
                                "capability_id": "agent.desktop-main-agent.file.read",
                                "arguments": {"path": "sample.txt"},
                            },
                        },
                        object(),
                    )
                )
                self.assertEqual(read_ws.sent[-1]["type"], "capability.call.result")
                self.assertEqual(read_ws.sent[-1]["payload"]["result"]["content"], "hello file read")

                # file.write
                write_ws = _FakeWs()
                asyncio.run(
                    runtime._handle_call_request(
                        write_ws,
                        {
                            "schema": "meetyou.agent.v1",
                            "type": "capability.call.request",
                            "message_id": "dispatch-write",
                            "payload": {
                                "call_id": "call-write",
                                "capability_id": "agent.desktop-main-agent.file.write",
                                "arguments": {"path": "written.txt", "content": "hello file write"},
                            },
                        },
                        object(),
                    )
                )
                self.assertEqual(write_ws.sent[-1]["type"], "capability.call.result")
                self.assertEqual((root / "written.txt").read_text(encoding="utf-8"), "hello file write")

                # shell.exec
                shell_ws = _FakeWs()
                asyncio.run(
                    runtime._handle_call_request(
                        shell_ws,
                        {
                            "schema": "meetyou.agent.v1",
                            "type": "capability.call.request",
                            "message_id": "dispatch-shell",
                            "payload": {
                                "call_id": "call-shell",
                                "capability_id": "agent.desktop-main-agent.shell.exec",
                                "arguments": {"command": 'python -c "print(123)"'},
                            },
                        },
                        object(),
                    )
                )
                self.assertEqual(shell_ws.sent[-1]["type"], "capability.call.result")
                self.assertEqual(shell_ws.sent[-1]["payload"]["result"]["stdout"], "123")
            finally:
                os.chdir(old_cwd)

    def test_runtime_handles_workspace_analyze(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "src").mkdir()
            (root / "package.json").write_text('{"name":"demo"}', encoding="utf-8")
            (root / "src" / "main.tsx").write_text("export default 'ok'\n", encoding="utf-8")
            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                config = DesktopAgentConfig(
                    core_base_url="http://127.0.0.1:8000",
                    agent_id="desktop-main-agent",
                    display_name="Desktop Main Agent",
                    workspace_ids=["personal"],
                    read_roots=["."],
                )
                runtime = DesktopAgentRuntime(config)

                class _FakeWs:
                    def __init__(self):
                        self.sent = []

                    async def send_json(self, payload):
                        self.sent.append(payload)

                ws = _FakeWs()
                asyncio.run(
                    runtime._handle_call_request(
                        ws,
                        {
                            "schema": "meetyou.agent.v1",
                            "type": "capability.call.request",
                            "message_id": "dispatch-workspace",
                            "payload": {
                                "call_id": "call-workspace",
                                "capability_id": "agent.desktop-main-agent.workspace.analyze",
                                "arguments": {"path": ".", "depth": 3, "focus": "src"},
                            },
                        },
                        object(),
                    )
                )
                self.assertEqual(ws.sent[-1]["type"], "capability.call.result")
                summary = ws.sent[-1]["payload"]["result"]["summary"]
                self.assertIn("package.json", summary["manifest_files"])
                self.assertIn("src/main.tsx", [item.replace("\\", "/") for item in summary["entry_clues"]])
            finally:
                os.chdir(old_cwd)

    def test_runtime_uploads_attachment_outputs_before_sending_result(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                attachment_file = root / "report.txt"
                attachment_file.write_text("attachment body", encoding="utf-8")
                config = DesktopAgentConfig(
                    core_base_url="http://127.0.0.1:8000",
                    agent_id="desktop-main-agent",
                    display_name="Desktop Main Agent",
                    workspace_ids=["personal"],
                    read_roots=["."],
                )
                runtime = DesktopAgentRuntime(config)
                runtime._handlers["agent.desktop-main-agent.utility.with_attachment"] = self._build_attachment_handler(str(attachment_file))

                class _FakeWs:
                    def __init__(self):
                        self.sent = []

                    async def send_json(self, payload):
                        self.sent.append(payload)

                class _FakeResponse:
                    def __init__(self, status: int, payload: dict):
                        self.status = status
                        self._payload = payload

                    async def json(self, content_type=None):
                        del content_type
                        return self._payload

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, exc_type, exc, tb):
                        return False

                class _FakeSession:
                    def request(self, method, url, **kwargs):
                        if method == "POST" and url.endswith("/agent/attachments/upload-ticket"):
                            return _FakeResponse(200, {
                                "attachment_id": "att_uploaded",
                                "ticket_id": "att_ticket",
                                "upload_url": "http://127.0.0.1:8000/agent/attachments/upload/att_ticket",
                            })
                        if method == "PUT" and url.endswith("/agent/attachments/upload/att_ticket"):
                            return _FakeResponse(200, {
                                "attachment_id": "att_uploaded",
                                "ticket_id": "att_ticket",
                                "status": "uploaded",
                                "size_bytes": len(kwargs.get("data") or b""),
                                "sha256": "abc",
                            })
                        if method == "POST" and url.endswith("/agent/attachments/att_uploaded/complete"):
                            return _FakeResponse(200, {
                                "attachment_id": "att_uploaded",
                                "status": "ready",
                                "mime_type": "text/plain",
                                "file_name": "report.txt",
                                "size_bytes": 15,
                                "sha256": "abc",
                            })
                        raise AssertionError(f"Unexpected request: {method} {url}")

                ws = _FakeWs()
                asyncio.run(
                    runtime._handle_call_request(
                        ws,
                        {
                            "schema": "meetyou.agent.v1",
                            "type": "capability.call.request",
                            "message_id": "dispatch-attachment",
                            "payload": {
                                "operation_id": "op_attachment_1",
                                "call_id": "call-attachment",
                                "capability_id": "agent.desktop-main-agent.utility.with_attachment",
                                "arguments": {},
                            },
                        },
                        _FakeSession(),
                    )
                )
                result_payload = ws.sent[-1]["payload"]
                self.assertEqual(result_payload["result"]["summary"], "done")
                self.assertEqual(result_payload["attachment_outputs"][0]["attachment_id"], "att_uploaded")
                self.assertEqual(result_payload["attachment_outputs"][0]["file_name"], "report.txt")
            finally:
                os.chdir(old_cwd)

    def test_runtime_deletes_local_ephemeral_attachment_after_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                attachment_file = root / "capture.png"
                attachment_file.write_bytes(b"png-bytes")
                config = DesktopAgentConfig(
                    core_base_url="http://127.0.0.1:8000",
                    agent_id="desktop-main-agent",
                    display_name="Desktop Main Agent",
                    workspace_ids=["personal"],
                    read_roots=["."],
                )
                runtime = DesktopAgentRuntime(config)

                async def _ephemeral_handler(arguments):
                    del arguments
                    return {
                        "summary": "done",
                        "attachment_outputs": [
                            {
                                "local_path": str(attachment_file),
                                "kind": "screenshot",
                                "mime_type": "image/png",
                                "file_name": "capture.png",
                                "lifecycle_policy": "ephemeral",
                            }
                        ],
                    }

                runtime._handlers["agent.desktop-main-agent.utility.with_ephemeral_attachment"] = _ephemeral_handler

                class _FakeWs:
                    def __init__(self):
                        self.sent = []

                    async def send_json(self, payload):
                        self.sent.append(payload)

                class _FakeResponse:
                    def __init__(self, status: int, payload: dict):
                        self.status = status
                        self._payload = payload

                    async def json(self, content_type=None):
                        del content_type
                        return self._payload

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, exc_type, exc, tb):
                        return False

                class _FakeSession:
                    def request(self, method, url, **kwargs):
                        if method == "POST" and url.endswith("/agent/attachments/upload-ticket"):
                            return _FakeResponse(200, {
                                "attachment_id": "att_uploaded",
                                "ticket_id": "att_ticket",
                                "upload_url": "http://127.0.0.1:8000/agent/attachments/upload/att_ticket",
                            })
                        if method == "PUT" and url.endswith("/agent/attachments/upload/att_ticket"):
                            return _FakeResponse(200, {
                                "attachment_id": "att_uploaded",
                                "ticket_id": "att_ticket",
                                "status": "uploaded",
                                "size_bytes": len(kwargs.get("data") or b""),
                                "sha256": "abc",
                            })
                        if method == "POST" and url.endswith("/agent/attachments/att_uploaded/complete"):
                            return _FakeResponse(200, {
                                "attachment_id": "att_uploaded",
                                "status": "ready",
                                "mime_type": "image/png",
                                "file_name": "capture.png",
                                "size_bytes": len(b"png-bytes"),
                                "sha256": "abc",
                                "lifecycle_policy": "ephemeral",
                                "expires_at": "2026-04-13T00:00:00Z",
                            })
                        raise AssertionError(f"Unexpected request: {method} {url}")

                ws = _FakeWs()
                asyncio.run(
                    runtime._handle_call_request(
                        ws,
                        {
                            "schema": "meetyou.agent.v1",
                            "type": "capability.call.request",
                            "message_id": "dispatch-ephemeral-attachment",
                            "payload": {
                                "operation_id": "op_attachment_ephemeral",
                                "call_id": "call-ephemeral-attachment",
                                "capability_id": "agent.desktop-main-agent.utility.with_ephemeral_attachment",
                                "arguments": {},
                            },
                        },
                        _FakeSession(),
                    )
                )
                result_payload = ws.sent[-1]["payload"]
                self.assertFalse(attachment_file.exists())
                self.assertTrue(result_payload["attachment_outputs"][0]["local_file_deleted"])
                self.assertEqual(result_payload["attachment_outputs"][0]["lifecycle_policy"], "ephemeral")
            finally:
                os.chdir(old_cwd)

    def test_hello_ack_applies_heartbeat_interval_without_waiting_old_interval(self):
        async def _run():
            config = DesktopAgentConfig(
                core_base_url="http://127.0.0.1:8000",
                agent_id="desktop-main-agent",
                display_name="Desktop Main Agent",
                workspace_ids=["personal"],
                heartbeat_interval_seconds=30,
            )
            runtime = DesktopAgentRuntime(config)

            class _FakeWs:
                def __init__(self):
                    self.sent = []
                    self.sent_event = asyncio.Event()

                async def send_json(self, payload):
                    self.sent.append(payload)
                    self.sent_event.set()

            ws = _FakeWs()
            heartbeat_task = asyncio.create_task(runtime._heartbeat_loop(ws))
            try:
                await asyncio.sleep(0.05)
                ready_received = await runtime._handle_server_message(
                    {
                        "schema": "meetyou.agent.v1",
                        "type": "agent.hello.ack",
                        "payload": {"heartbeat_interval_seconds": 1},
                    },
                    False,
                    ws,
                    object(),
                )
                self.assertFalse(ready_received)
                self.assertEqual(runtime._heartbeat_interval_seconds, 1)
                await asyncio.wait_for(ws.sent_event.wait(), timeout=3.5)
                self.assertEqual(ws.sent[-1]["type"], "agent.heartbeat")
            finally:
                heartbeat_task.cancel()
                with __import__("contextlib").suppress(asyncio.CancelledError):
                    await heartbeat_task

        asyncio.run(_run())

    @staticmethod
    def _build_attachment_handler(local_path: str):
        async def handler(arguments):
            del arguments
            return {
                "summary": "done",
                "attachment_outputs": [
                    {
                        "local_path": local_path,
                        "kind": "file",
                        "mime_type": "text/plain",
                        "file_name": "report.txt",
                    }
                ],
            }

        return handler


class DesktopAgentHeartbeatNegotiationTests(unittest.IsolatedAsyncioTestCase):
    async def test_hello_ack_updates_heartbeat_interval_and_wakes_loop(self):
        config = load_desktop_agent_config()
        runtime = DesktopAgentRuntime(config)
        self.assertEqual(runtime._heartbeat_interval_seconds, config.heartbeat_interval_seconds)
        self.assertFalse(runtime._heartbeat_interval_updated.is_set())

        ready_received = await runtime._handle_server_message(
            {
                "schema": "meetyou.agent.v1",
                "type": "agent.hello.ack",
                "payload": {
                    "heartbeat_interval_seconds": 5,
                    "protocol": {
                        "selected_schema": "meetyou.agent.v1",
                        "selected_version": 1,
                        "enabled_features": ["connection_prompt", "heartbeat_interval_negotiation"],
                        "disabled_features": ["experimental.delta"],
                        "compatibility_mode": "downgraded",
                    },
                },
            },
            False,
            object(),
            object(),
        )

        self.assertFalse(ready_received)
        self.assertEqual(runtime._heartbeat_interval_seconds, 5)
        self.assertTrue(runtime._heartbeat_interval_updated.is_set())
        self.assertEqual(runtime._negotiated_protocol["compatibility_mode"], "downgraded")
        self.assertEqual(runtime._negotiated_protocol["disabled_features"], ["experimental.delta"])
