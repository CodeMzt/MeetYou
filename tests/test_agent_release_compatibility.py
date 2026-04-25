from __future__ import annotations

import asyncio
import os
import time
import unittest

from fastapi.testclient import TestClient
from psycopg import connect
from sqlalchemy import select

from agent_sdk.protocol import (
    AGENT_ARGUMENTS_PURPOSE,
    DEFAULT_AGENT_PROTOCOL_FEATURES,
    LEGACY_AGENT_PROTOCOL_FEATURES,
    build_agent_protocol_offer,
)
from agent_sdk.security import decrypt_json_payload
from core.db.bootstrap import bootstrap_core_domain
from core.db.models.operation import OperationCall
from desktop_agent.config import DesktopAgentConfig
from desktop_agent.runtime import DesktopAgentRuntime
from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway


TEST_DATABASE_NAME = "meetyou_agent_release_compat_test"
ADMIN_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
TEST_DATABASE_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{TEST_DATABASE_NAME}"


class _GatewayAgentReleaseTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._drop_database(TEST_DATABASE_NAME)
        cls._create_database(TEST_DATABASE_NAME)

    @classmethod
    def tearDownClass(cls):
        cls._drop_database(TEST_DATABASE_NAME)

    @staticmethod
    def _admin_connect():
        return connect(ADMIN_DATABASE_URL, autocommit=True)

    @classmethod
    def _drop_database(cls, db_name: str) -> None:
        with cls._admin_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (db_name,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')

    @classmethod
    def _create_database(cls, db_name: str) -> None:
        with cls._admin_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE DATABASE "{db_name}"')

    def setUp(self):
        self.access_token = "agent-token"
        self.core_domain = bootstrap_core_domain(database_url=TEST_DATABASE_URL, run_migrations=True)
        self.gateway = FastAPIGateway(
            EventBus(),
            SessionManager(),
            health_getter=lambda: {
                "service": "meetyou-runtime",
                "status": "ready",
                "live": True,
                "ready": True,
                "degraded": False,
                "components": [],
                "errors": [],
                "updated_at": "2026-04-15T00:00:00Z",
            },
            core_domain=self.core_domain,
            agent_access_token=self.access_token,
            access_token=self.access_token,
        )
        self.client = TestClient(self.gateway.app)

    def tearDown(self):
        self.client.close()
        self.core_domain.engine.dispose()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    def _wait_for_operator_agent_status(self, expected_status: str, *, timeout_seconds: float = 2.0):
        deadline = time.time() + timeout_seconds
        last_payload = None
        while time.time() < deadline:
            operator_resp = self.client.get("/operator/agents", headers=self._auth_headers())
            self.assertEqual(operator_resp.status_code, 200)
            last_payload = operator_resp.json()
            if last_payload and last_payload[0].get("status") == expected_status:
                return last_payload
            time.sleep(0.05)
        self.assertIsNotNone(last_payload)
        self.assertTrue(last_payload)
        self.assertEqual(last_payload[0]["status"], expected_status)

    def _hello_payload(self, *, protocol: dict | None):
        payload = {
            "agent_type": "desktop",
            "display_name": "Desktop Main Agent",
            "transport_profile": "desktop_wss",
            "owner_client_id": "desktop-app",
            "owner_client_type": "electron",
            "owner_client_display_name": "Desktop App",
            "workspace_ids": ["personal", "desktop-main"],
            "supports_offline_cache": True,
            "host": {"hostname": "DESKTOP-01", "os": "windows", "arch": "x86_64"},
        }
        if protocol is not None:
            payload["protocol"] = protocol
        return {
            "schema": "meetyou.agent.v1",
            "type": "agent.hello",
            "message_id": "msg-hello-release",
            "sent_at": "2026-04-15T00:00:00Z",
            "agent_id": "desktop-main-agent",
            "payload": payload,
        }

    @staticmethod
    def _snapshot_payload():
        return {
            "schema": "meetyou.agent.v1",
            "type": "agent.capabilities.snapshot",
            "message_id": "msg-caps-release",
            "sent_at": "2026-04-15T00:00:01Z",
            "agent_id": "desktop-main-agent",
            "payload": {
                "revision": 3,
                "capabilities": [
                    {
                        "capability_id": "agent.desktop-main-agent.utility.echo",
                        "kind": "tool",
                        "title": "Echo Payload",
                        "risk_level": "read",
                        "requires_confirmation": False,
                        "workspace_ids": ["personal", "desktop-main"],
                    }
                ],
            },
        }

    @staticmethod
    def _heartbeat_payload(*, status: str, cpu_percent: float):
        return {
            "schema": "meetyou.agent.v1",
            "type": "agent.heartbeat",
            "message_id": f"msg-heartbeat-{status}",
            "sent_at": "2026-04-15T00:00:02Z",
            "agent_id": "desktop-main-agent",
            "payload": {
                "status": status,
                "metrics": {"cpu_percent": cpu_percent},
            },
        }

    def _create_operation_thread(self):
        workspace = self.core_domain.services.workspace.get_by_workspace_id("desktop-main")
        thread = self.core_domain.services.thread.create_thread(
            principal_id=self.core_domain.principal.id,
            workspace_id=workspace.id,
            title="Compatibility release thread",
        )
        return thread


class GatewayAgentReleaseCompatibilityTests(_GatewayAgentReleaseTestCase):
    def test_core_n_agent_n_release_flow_covers_handshake_heartbeat_encrypted_call_and_attachment_download(self):
        protocol = build_agent_protocol_offer(
            schema_name="meetyou.agent.v1",
            version=1,
            supported_schemas=["meetyou.agent.v1"],
            supported_versions=[1],
            features=DEFAULT_AGENT_PROTOCOL_FEATURES,
        )

        old_secret = os.environ.get("MEETYOU_CREDENTIAL_SECRET")
        os.environ["MEETYOU_CREDENTIAL_SECRET"] = "release-matrix-secret"
        try:
            with self.client.websocket_connect("/agent/ws", headers=self._auth_headers()) as websocket:
                websocket.send_json(self._hello_payload(protocol=protocol))
                hello_ack = websocket.receive_json()
                self.assertEqual(hello_ack["type"], "agent.hello.ack")
                self.assertTrue(hello_ack["payload"]["accepted"])
                self.assertEqual(hello_ack["payload"]["protocol"]["selected_version"], 1)
                self.assertEqual(hello_ack["payload"]["protocol"]["compatibility_mode"], "negotiated")
                self.assertEqual(
                    set(hello_ack["payload"]["protocol"]["enabled_features"]),
                    set(DEFAULT_AGENT_PROTOCOL_FEATURES),
                )
                self.assertEqual(hello_ack["payload"]["heartbeat_interval_seconds"], 20)

                websocket.send_json(self._snapshot_payload())
                ready = websocket.receive_json()
                self.assertEqual(ready["type"], "agent.ready")

                websocket.send_json(self._heartbeat_payload(status="ready", cpu_percent=18.5))
                self._wait_for_operator_agent_status("ready")

                thread = self._create_operation_thread()
                operation_resp = self.client.post(
                    "/client/operations",
                    json={
                        "thread_id": thread.thread_id,
                        "workspace_id": "desktop-main",
                        "client_id": "desktop-app",
                        "title": "Release encrypted call",
                        "operation_type": "capability_call",
                        "execution_target": "specific_agent",
                        "target_agent_id": "desktop-main-agent",
                        "capability_id": "agent.desktop-main-agent.utility.echo",
                        "arguments": {
                            "text": "hello-release",
                            "access_token": "token-release-123",
                        },
                    },
                    headers=self._auth_headers(),
                )
                self.assertEqual(operation_resp.status_code, 200)
                operation_payload = operation_resp.json()
                operation_id = operation_payload["operation_id"]

                call_request = websocket.receive_json()
                self.assertEqual(call_request["type"], "capability.call.request")
                self.assertEqual(call_request["payload"]["arguments"]["access_token"], "[REDACTED]")
                decrypted = decrypt_json_payload(
                    call_request["payload"]["encrypted_arguments"],
                    purpose=AGENT_ARGUMENTS_PURPOSE,
                )
                self.assertEqual(
                    decrypted,
                    {"text": "hello-release", "access_token": "token-release-123"},
                )

                ticket_resp = self.client.post(
                    "/agent/attachments/upload-ticket",
                    json={
                        "agent_id": "desktop-main-agent",
                        "owner_type": "operation",
                        "owner_id": operation_id,
                        "kind": "file",
                        "mime_type": "text/plain",
                        "file_name": "release-report.txt",
                    },
                    headers=self._auth_headers(),
                )
                self.assertEqual(ticket_resp.status_code, 200)
                ticket_payload = ticket_resp.json()

                upload_resp = self.client.put(
                    f"/agent/attachments/upload/{ticket_payload['ticket_id']}",
                    content=b"release attachment body",
                    headers=self._auth_headers(),
                )
                self.assertEqual(upload_resp.status_code, 200)

                complete_resp = self.client.post(
                    f"/agent/attachments/{ticket_payload['attachment_id']}/complete",
                    json={"ticket_id": ticket_payload["ticket_id"]},
                    headers=self._auth_headers(),
                )
                self.assertEqual(complete_resp.status_code, 200)

                websocket.send_json(
                    {
                        "schema": "meetyou.agent.v1",
                        "type": "capability.call.accepted",
                        "message_id": "msg-call-accepted-release",
                        "sent_at": "2026-04-15T00:00:03Z",
                        "agent_id": "desktop-main-agent",
                        "correlation_id": call_request["message_id"],
                        "payload": {
                            "call_id": call_request["payload"]["call_id"],
                            "accepted": True,
                            "started_at": "2026-04-15T00:00:03Z",
                        },
                    }
                )
                websocket.send_json(
                    {
                        "schema": "meetyou.agent.v1",
                        "type": "capability.call.result",
                        "message_id": "msg-call-result-release",
                        "sent_at": "2026-04-15T00:00:04Z",
                        "agent_id": "desktop-main-agent",
                        "correlation_id": call_request["message_id"],
                        "payload": {
                            "call_id": call_request["payload"]["call_id"],
                            "status": "succeeded",
                            "result": {"summary": "done", "echo": "hello-release"},
                            "attachment_outputs": [{"attachment_id": ticket_payload["attachment_id"]}],
                            "finished_at": "2026-04-15T00:00:04Z",
                        },
                    }
                )

                fetched_payload = None
                for _ in range(10):
                    fetched = self.client.get(f"/client/operations/{operation_id}", headers=self._auth_headers())
                    self.assertEqual(fetched.status_code, 200)
                    fetched_payload = fetched.json()
                    if fetched_payload["status"] == "succeeded":
                        break
                    time.sleep(0.05)
                self.assertEqual(fetched_payload["status"], "succeeded")

                with self.core_domain.session_factory() as session:
                    call_row = session.execute(
                        select(OperationCall).where(
                            OperationCall.call_id == call_request["payload"]["call_id"]
                        )
                    ).scalar_one()
                attachment_view = call_row.result["attachment_outputs"][0]
                self.assertEqual(attachment_view["file_name"], "release-report.txt")
                self.assertEqual(attachment_view["mime_type"], "text/plain")
                self.assertEqual(attachment_view["status"], "ready")

                download_ticket = self.core_domain.services.attachment.create_download_ticket(
                    attachment_id=ticket_payload["attachment_id"],
                    issuer_type="agent",
                    issuer_ref="desktop-main-agent",
                    fallback_download_url="http://127.0.0.1:8000/agent/attachments/content/demo?ticket_id=",
                )
                download_resp = self.client.get(
                    f"/agent/attachments/content/{ticket_payload['attachment_id']}?ticket_id={download_ticket['ticket_id']}",
                    headers=self._auth_headers(),
                )
                self.assertEqual(download_resp.status_code, 200)
                self.assertEqual(download_resp.content, b"release attachment body")
        finally:
            if old_secret is None:
                os.environ.pop("MEETYOU_CREDENTIAL_SECRET", None)
            else:
                os.environ["MEETYOU_CREDENTIAL_SECRET"] = old_secret

    def test_core_n_agent_n_minus_1_release_flow_accepts_legacy_handshake_and_attachment_call_path(self):
        with self.client.websocket_connect("/agent/ws", headers=self._auth_headers()) as websocket:
            websocket.send_json(self._hello_payload(protocol=None))
            hello_ack = websocket.receive_json()
            self.assertEqual(hello_ack["type"], "agent.hello.ack")
            self.assertTrue(hello_ack["payload"]["accepted"])
            self.assertEqual(hello_ack["payload"]["protocol"]["compatibility_mode"], "legacy_defaults")
            self.assertEqual(
                set(hello_ack["payload"]["protocol"]["enabled_features"]),
                set(LEGACY_AGENT_PROTOCOL_FEATURES),
            )

            websocket.send_json(self._snapshot_payload())
            ready = websocket.receive_json()
            self.assertEqual(ready["type"], "agent.ready")

            websocket.send_json(self._heartbeat_payload(status="busy", cpu_percent=42.0))
            self._wait_for_operator_agent_status("busy")

            thread = self._create_operation_thread()
            operation_resp = self.client.post(
                "/client/operations",
                json={
                    "thread_id": thread.thread_id,
                    "workspace_id": "desktop-main",
                    "client_id": "desktop-app",
                    "title": "Legacy agent release call",
                    "operation_type": "capability_call",
                    "execution_target": "specific_agent",
                    "target_agent_id": "desktop-main-agent",
                    "capability_id": "agent.desktop-main-agent.utility.echo",
                    "arguments": {"text": "legacy-agent"},
                },
                headers=self._auth_headers(),
            )
            self.assertEqual(operation_resp.status_code, 200)
            operation_payload = operation_resp.json()
            operation_id = operation_payload["operation_id"]

            call_request = websocket.receive_json()
            self.assertEqual(call_request["type"], "capability.call.request")
            self.assertEqual(call_request["payload"]["arguments"], {"text": "legacy-agent"})
            self.assertEqual(call_request["payload"].get("encrypted_arguments") or {}, {})

            ticket_resp = self.client.post(
                "/agent/attachments/upload-ticket",
                json={
                    "agent_id": "desktop-main-agent",
                    "owner_type": "operation",
                    "owner_id": operation_id,
                    "kind": "file",
                    "mime_type": "text/plain",
                    "file_name": "legacy-agent-note.txt",
                },
                headers=self._auth_headers(),
            )
            self.assertEqual(ticket_resp.status_code, 200)
            ticket_payload = ticket_resp.json()

            upload_resp = self.client.put(
                f"/agent/attachments/upload/{ticket_payload['ticket_id']}",
                content=b"legacy attachment body",
                headers=self._auth_headers(),
            )
            self.assertEqual(upload_resp.status_code, 200)

            complete_resp = self.client.post(
                f"/agent/attachments/{ticket_payload['attachment_id']}/complete",
                json={"ticket_id": ticket_payload["ticket_id"]},
                headers=self._auth_headers(),
            )
            self.assertEqual(complete_resp.status_code, 200)

            websocket.send_json(
                {
                    "schema": "meetyou.agent.v1",
                    "type": "capability.call.accepted",
                    "message_id": "msg-call-accepted-legacy",
                    "sent_at": "2026-04-15T00:00:03Z",
                    "agent_id": "desktop-main-agent",
                    "correlation_id": call_request["message_id"],
                    "payload": {
                        "call_id": call_request["payload"]["call_id"],
                        "accepted": True,
                        "started_at": "2026-04-15T00:00:03Z",
                    },
                }
            )
            websocket.send_json(
                {
                    "schema": "meetyou.agent.v1",
                    "type": "capability.call.result",
                    "message_id": "msg-call-result-legacy",
                    "sent_at": "2026-04-15T00:00:04Z",
                    "agent_id": "desktop-main-agent",
                    "correlation_id": call_request["message_id"],
                    "payload": {
                        "call_id": call_request["payload"]["call_id"],
                        "status": "succeeded",
                        "result": {"summary": "legacy-done", "echo": "legacy-agent"},
                        "attachment_outputs": [{"attachment_id": ticket_payload["attachment_id"]}],
                        "finished_at": "2026-04-15T00:00:04Z",
                    },
                }
            )

            fetched_payload = None
            for _ in range(10):
                fetched = self.client.get(f"/client/operations/{operation_id}", headers=self._auth_headers())
                self.assertEqual(fetched.status_code, 200)
                fetched_payload = fetched.json()
                if fetched_payload["status"] == "succeeded":
                    break
                time.sleep(0.05)
            self.assertEqual(fetched_payload["status"], "succeeded")
            with self.core_domain.session_factory() as session:
                call_row = session.execute(
                    select(OperationCall).where(
                        OperationCall.call_id == call_request["payload"]["call_id"]
                    )
                ).scalar_one()
            self.assertEqual(call_row.result["echo"], "legacy-agent")
            self.assertEqual(call_row.result["attachment_outputs"][0]["file_name"], "legacy-agent-note.txt")


class AgentRuntimeReleaseCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_core_n_minus_1_agent_n_release_flow_falls_back_to_legacy_ack_then_heartbeat_and_call(self):
        config = DesktopAgentConfig(
            core_base_url="http://127.0.0.1:8000",
            agent_id="desktop-main-agent",
            display_name="Desktop Main Agent",
            workspace_ids=["personal"],
            heartbeat_interval_seconds=3,
        )
        runtime = DesktopAgentRuntime(config)

        class _FakeWs:
            def __init__(self):
                self.sent = []
                self.heartbeat_sent = asyncio.Event()

            async def send_json(self, payload):
                self.sent.append(payload)
                if payload.get("type") == "agent.heartbeat":
                    self.heartbeat_sent.set()

        ws = _FakeWs()
        heartbeat_task = asyncio.create_task(runtime._heartbeat_loop(ws))
        try:
            ready_received = await runtime._handle_server_message(
                {
                    "schema": "meetyou.agent.v1",
                    "type": "agent.hello.ack",
                    "payload": {
                        "accepted": True,
                        "registered_agent_id": config.agent_id,
                    },
                },
                False,
                ws,
                object(),
            )
            self.assertFalse(ready_received)
            self.assertTrue(runtime._requires_capability_snapshot)
            self.assertEqual(runtime._heartbeat_interval_seconds, 3)
            self.assertEqual(runtime._negotiated_protocol["compatibility_mode"], "legacy_defaults")

            await asyncio.wait_for(ws.heartbeat_sent.wait(), timeout=3.5)
            self.assertEqual(ws.sent[-1]["type"], "agent.heartbeat")

            await runtime._handle_call_request(
                ws,
                {
                    "schema": "meetyou.agent.v1",
                    "type": "capability.call.request",
                    "message_id": "dispatch-legacy-core",
                    "payload": {
                        "call_id": "call-legacy-core",
                        "capability_id": f"agent.{config.agent_id}.utility.echo",
                        "arguments": {"text": "legacy-core"},
                    },
                },
                object(),
            )

            self.assertEqual(
                [item["type"] for item in ws.sent if item["type"] != "agent.heartbeat"][-3:],
                [
                    "capability.call.accepted",
                    "capability.call.progress",
                    "capability.call.result",
                ],
            )
            self.assertEqual(ws.sent[-1]["payload"]["result"]["echo"], "legacy-core")
        finally:
            heartbeat_task.cancel()
            with __import__("contextlib").suppress(asyncio.CancelledError):
                await heartbeat_task
