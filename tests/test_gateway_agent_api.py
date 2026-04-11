from __future__ import annotations

import time
import unittest

from fastapi.testclient import TestClient
from psycopg import connect
from sqlalchemy import select

from core.db.bootstrap import bootstrap_core_domain
from core.db.models.agent import Agent, AgentCapabilitySnapshot
from core.db.models.capability import Capability, CapabilityWorkspaceBinding
from core.db.models.operation import Operation, OperationCall
from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway


TEST_DATABASE_NAME = "meetyou_gateway_agent_test"
ADMIN_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
TEST_DATABASE_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{TEST_DATABASE_NAME}"


class GatewayAgentApiTests(unittest.TestCase):
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
                "updated_at": "2026-04-08T00:00:00Z",
            },
            core_domain=self.core_domain,
            access_token=self.access_token,
        )
        self.client = TestClient(self.gateway.app)

    def tearDown(self):
        self.client.close()
        self.core_domain.engine.dispose()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    def test_agent_websocket_registers_agent_and_capabilities(self):
        hello = {
            "schema": "meetyou.agent.v1",
            "type": "agent.hello",
            "message_id": "msg-hello-1",
            "sent_at": "2026-04-08T00:00:00Z",
            "agent_id": "desktop-main-agent",
            "payload": {
                "agent_type": "desktop",
                "display_name": "Desktop Main Agent",
                "transport_profile": "desktop_wss",
                "owner_client_id": "desktop-app",
                "owner_client_type": "electron",
                "owner_client_display_name": "Desktop App",
                "workspace_ids": ["personal", "desktop-main", "study"],
                "supports_offline_cache": True,
                "host": {"hostname": "DESKTOP-01", "os": "windows", "arch": "x86_64"},
            },
        }
        snapshot = {
            "schema": "meetyou.agent.v1",
            "type": "agent.capabilities.snapshot",
            "message_id": "msg-caps-1",
            "sent_at": "2026-04-08T00:00:01Z",
            "agent_id": "desktop-main-agent",
            "payload": {
                "revision": 3,
                "capabilities": [
                    {
                        "capability_id": "agent.desktop-main-agent.screen.capture",
                        "kind": "tool",
                        "title": "Capture Desktop Screenshot",
                        "risk_level": "read",
                        "requires_confirmation": False,
                        "workspace_ids": ["personal", "desktop-main"],
                    },
                    {
                        "capability_id": "agent.desktop-main-agent.shell.exec",
                        "kind": "tool",
                        "title": "Execute Local Command",
                        "risk_level": "system",
                        "requires_confirmation": True,
                        "workspace_ids": ["desktop-main", "study"],
                    },
                ],
            },
        }

        with self.client.websocket_connect("/agent/ws", headers=self._auth_headers()) as websocket:
            websocket.send_json(hello)
            hello_ack = websocket.receive_json()
            self.assertEqual(hello_ack["type"], "agent.hello.ack")
            websocket.send_json(snapshot)
            ready = websocket.receive_json()
            self.assertEqual(ready["type"], "agent.ready")

            operator_resp = self.client.get("/operator/agents", headers=self._auth_headers())
            self.assertEqual(operator_resp.status_code, 200)
            payload = operator_resp.json()
            self.assertEqual(payload[0]["agent_id"], "desktop-main-agent")
            self.assertEqual(payload[0]["owner_client_id"], "desktop-app")
            self.assertEqual(set(payload[0]["workspace_ids"]), {"personal", "desktop-main", "study"})

        with self.core_domain.session_factory() as session:
            agent = session.execute(select(Agent).where(Agent.agent_id == "desktop-main-agent")).scalar_one()
            self.assertEqual(agent.status, "offline")
            self.assertEqual(agent.host_os, "windows")
            self.assertIsNotNone(agent.owner_client_id)
            snapshots = session.execute(select(AgentCapabilitySnapshot)).scalars().all()
            self.assertGreaterEqual(len(snapshots), 1)
            capabilities = session.execute(select(Capability).where(Capability.provider_ref == "desktop-main-agent")).scalars().all()
            capability_ids = {item.capability_id for item in capabilities}
            self.assertIn("agent.desktop-main-agent.screen.capture", capability_ids)
            self.assertIn("agent.desktop-main-agent.shell.exec", capability_ids)
            bindings = session.execute(select(CapabilityWorkspaceBinding)).scalars().all()
            self.assertGreaterEqual(len(bindings), 4)

    def test_agent_websocket_rejects_identity_switch_on_same_socket(self):
        first_hello = {
            "schema": "meetyou.agent.v1",
            "type": "agent.hello",
            "message_id": "msg-hello-1",
            "sent_at": "2026-04-08T00:00:00Z",
            "agent_id": "desktop-main-agent",
            "payload": {
                "agent_type": "desktop",
                "display_name": "Desktop Main Agent",
                "transport_profile": "desktop_wss",
                "owner_client_id": "desktop-app",
                "owner_client_type": "electron",
                "owner_client_display_name": "Desktop App",
                "workspace_ids": ["personal", "desktop-main"],
                "supports_offline_cache": True,
                "host": {"hostname": "DESKTOP-01", "os": "windows", "arch": "x86_64"},
            },
        }
        second_hello = {
            **first_hello,
            "message_id": "msg-hello-2",
            "agent_id": "desktop-rogue-agent",
            "payload": {
                **first_hello["payload"],
                "display_name": "Desktop Rogue Agent",
            },
        }

        with self.client.websocket_connect("/agent/ws", headers=self._auth_headers()) as websocket:
            websocket.send_json(first_hello)
            ack = websocket.receive_json()
            self.assertEqual(ack["type"], "agent.hello.ack")

            websocket.send_json(second_hello)
            error = websocket.receive_json()
            self.assertEqual(error["kind"], "error")
            self.assertEqual(error["error"]["code"], "agent_identity_mismatch")

        operator_resp = self.client.get("/operator/agents", headers=self._auth_headers())
        self.assertEqual(operator_resp.status_code, 200)
        agent_ids = {item["agent_id"] for item in operator_resp.json()}
        self.assertIn("desktop-main-agent", agent_ids)
        self.assertNotIn("desktop-rogue-agent", agent_ids)

    def test_agent_websocket_receives_dispatched_call_and_reports_result(self):
        hello = {
            "schema": "meetyou.agent.v1",
            "type": "agent.hello",
            "message_id": "msg-hello-1",
            "sent_at": "2026-04-08T00:00:00Z",
            "agent_id": "desktop-main-agent",
            "payload": {
                "agent_type": "desktop",
                "display_name": "Desktop Main Agent",
                "transport_profile": "desktop_wss",
                "owner_client_id": "desktop-app",
                "owner_client_type": "electron",
                "owner_client_display_name": "Desktop App",
                "workspace_ids": ["personal", "desktop-main", "study"],
                "supports_offline_cache": True,
                "host": {"hostname": "DESKTOP-01", "os": "windows", "arch": "x86_64"},
            },
        }
        snapshot = {
            "schema": "meetyou.agent.v1",
            "type": "agent.capabilities.snapshot",
            "message_id": "msg-caps-1",
            "sent_at": "2026-04-08T00:00:01Z",
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

        desktop_workspace = self.core_domain.services.workspace.get_by_workspace_id("desktop-main")
        thread = self.core_domain.services.thread.create_thread(
            principal_id=self.core_domain.principal.id,
            workspace_id=desktop_workspace.id,
            title="Agent call thread",
        )

        with self.client.websocket_connect("/agent/ws", headers=self._auth_headers()) as websocket:
            websocket.send_json(hello)
            websocket.receive_json()
            websocket.send_json(snapshot)
            websocket.receive_json()

            operation_resp = self.client.post(
                "/client/operations",
                json={
                    "thread_id": thread.thread_id,
                    "workspace_id": "desktop-main",
                    "client_id": "desktop-app",
                    "title": "Echo test",
                    "operation_type": "capability_call",
                    "execution_target": "specific_agent",
                    "target_agent_id": "desktop-main-agent",
                    "capability_id": "agent.desktop-main-agent.utility.echo",
                    "arguments": {"text": "hello-agent"},
                },
                headers=self._auth_headers(),
            )
            self.assertEqual(operation_resp.status_code, 200)
            operation_payload = operation_resp.json()
            self.assertEqual(operation_payload["status"], "dispatching")

            call_request = websocket.receive_json()
            self.assertEqual(call_request["type"], "capability.call.request")
            call_id = call_request["payload"]["call_id"]
            operation_id = call_request["payload"]["operation_id"]
            self.assertEqual(call_request["payload"]["arguments"]["text"], "hello-agent")

            websocket.send_json(
                {
                    "schema": "meetyou.agent.v1",
                    "type": "capability.call.accepted",
                    "message_id": "msg-call-accepted-1",
                    "sent_at": "2026-04-08T00:00:02Z",
                    "agent_id": "desktop-main-agent",
                    "correlation_id": call_request["message_id"],
                    "payload": {"call_id": call_id, "accepted": True, "started_at": "2026-04-08T00:00:02Z"},
                }
            )
            websocket.send_json(
                {
                    "schema": "meetyou.agent.v1",
                    "type": "capability.call.result",
                    "message_id": "msg-call-result-1",
                    "sent_at": "2026-04-08T00:00:03Z",
                    "agent_id": "desktop-main-agent",
                    "correlation_id": call_request["message_id"],
                    "payload": {
                        "call_id": call_id,
                        "status": "succeeded",
                        "result": {"summary": "hello-agent", "echo": "hello-agent"},
                        "attachment_outputs": [],
                        "finished_at": "2026-04-08T00:00:03Z",
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
            operation = session.execute(select(Operation).where(Operation.operation_id == operation_id)).scalar_one()
            call = session.execute(select(OperationCall).where(OperationCall.call_id == call_id)).scalar_one()
            self.assertEqual(operation.status, "succeeded")
            self.assertEqual(call.status, "succeeded")
            self.assertEqual(call.result["echo"], "hello-agent")

    def test_agent_call_result_normalizes_attachment_outputs(self):
        hello = {
            "schema": "meetyou.agent.v1",
            "type": "agent.hello",
            "message_id": "msg-hello-1",
            "sent_at": "2026-04-08T00:00:00Z",
            "agent_id": "desktop-main-agent",
            "payload": {
                "agent_type": "desktop",
                "display_name": "Desktop Main Agent",
                "transport_profile": "desktop_wss",
                "owner_client_id": "desktop-app",
                "owner_client_type": "electron",
                "owner_client_display_name": "Desktop App",
                "workspace_ids": ["desktop-main"],
                "supports_offline_cache": True,
                "host": {"hostname": "DESKTOP-01", "os": "windows", "arch": "x86_64"},
            },
        }
        snapshot = {
            "schema": "meetyou.agent.v1",
            "type": "agent.capabilities.snapshot",
            "message_id": "msg-caps-1",
            "sent_at": "2026-04-08T00:00:01Z",
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
                        "workspace_ids": ["desktop-main"],
                    }
                ],
            },
        }

        desktop_workspace = self.core_domain.services.workspace.get_by_workspace_id("desktop-main")
        thread = self.core_domain.services.thread.create_thread(
            principal_id=self.core_domain.principal.id,
            workspace_id=desktop_workspace.id,
            title="Attachment normalization thread",
        )

        with self.client.websocket_connect("/agent/ws", headers=self._auth_headers()) as websocket:
            websocket.send_json(hello)
            websocket.receive_json()
            websocket.send_json(snapshot)
            websocket.receive_json()

            operation_resp = self.client.post(
                "/client/operations",
                json={
                    "thread_id": thread.thread_id,
                    "workspace_id": "desktop-main",
                    "client_id": "desktop-app",
                    "title": "Attachment normalization",
                    "operation_type": "capability_call",
                    "execution_target": "specific_agent",
                    "target_agent_id": "desktop-main-agent",
                    "capability_id": "agent.desktop-main-agent.utility.echo",
                    "arguments": {"text": "hello-agent"},
                },
                headers=self._auth_headers(),
            )
            self.assertEqual(operation_resp.status_code, 200)

            call_request = websocket.receive_json()
            call_id = call_request["payload"]["call_id"]
            operation_id = call_request["payload"]["operation_id"]

            ticket_resp = self.client.post(
                "/agent/attachments/upload-ticket",
                json={
                    "agent_id": "desktop-main-agent",
                    "owner_type": "operation",
                    "owner_id": operation_id,
                    "kind": "file",
                    "mime_type": "text/plain",
                    "file_name": "report.txt",
                },
                headers=self._auth_headers(),
            )
            self.assertEqual(ticket_resp.status_code, 200)
            ticket_payload = ticket_resp.json()

            upload_resp = self.client.put(
                f"/agent/attachments/upload/{ticket_payload['ticket_id']}",
                content=b"attachment body",
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
                    "message_id": "msg-call-accepted-2",
                    "sent_at": "2026-04-08T00:00:02Z",
                    "agent_id": "desktop-main-agent",
                    "correlation_id": call_request["message_id"],
                    "payload": {"call_id": call_id, "accepted": True, "started_at": "2026-04-08T00:00:02Z"},
                }
            )
            websocket.send_json(
                {
                    "schema": "meetyou.agent.v1",
                    "type": "capability.call.result",
                    "message_id": "msg-call-result-2",
                    "sent_at": "2026-04-08T00:00:03Z",
                    "agent_id": "desktop-main-agent",
                    "correlation_id": call_request["message_id"],
                    "payload": {
                        "call_id": call_id,
                        "status": "succeeded",
                        "result": {"summary": "done"},
                        "attachment_outputs": [{"attachment_id": ticket_payload["attachment_id"]}],
                        "finished_at": "2026-04-08T00:00:03Z",
                    },
                }
            )

            for _ in range(10):
                with self.core_domain.session_factory() as session:
                    call_row = session.execute(select(OperationCall).where(OperationCall.call_id == call_id)).scalar_one()
                    if call_row.status == "succeeded":
                        break
                time.sleep(0.05)

        with self.core_domain.session_factory() as session:
            call_row = session.execute(select(OperationCall).where(OperationCall.call_id == call_id)).scalar_one()
            attachment_outputs = call_row.result["attachment_outputs"]
            self.assertEqual(attachment_outputs[0]["attachment_id"], ticket_payload["attachment_id"])
            self.assertEqual(attachment_outputs[0]["file_name"], "report.txt")
            self.assertEqual(attachment_outputs[0]["mime_type"], "text/plain")
            self.assertEqual(attachment_outputs[0]["size_bytes"], len(b"attachment body"))
            self.assertEqual(attachment_outputs[0]["status"], "ready")

    def test_agent_attachment_http_flow(self):
        desktop_workspace = self.core_domain.services.workspace.get_by_workspace_id("desktop-main")
        client = self.core_domain.services.client.ensure_client(
            client_id="desktop-app",
            principal_id=self.core_domain.principal.id,
            client_type="electron",
            display_name="Desktop App",
        )
        agent = self.core_domain.services.agent.register_agent(
            principal_id=self.core_domain.principal.id,
            agent_id="desktop-main-agent",
            agent_type="desktop",
            display_name="Desktop Main Agent",
            transport_profile="desktop_wss",
            workspace_rows=[desktop_workspace],
            owner_client_id=client.id,
        )

        ticket_resp = self.client.post(
            "/agent/attachments/upload-ticket",
            json={
                "agent_id": "desktop-main-agent",
                "owner_type": "operation",
                "owner_id": "op_123",
                "kind": "file",
                "mime_type": "text/plain",
                "file_name": "agent-note.txt",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(ticket_resp.status_code, 200)
        ticket_payload = ticket_resp.json()
        self.assertTrue(ticket_payload["attachment_id"])
        self.assertTrue(ticket_payload["ticket_id"])

        upload_resp = self.client.put(
            f"/agent/attachments/upload/{ticket_payload['ticket_id']}",
            content=b"hello from agent",
            headers=self._auth_headers(),
        )
        self.assertEqual(upload_resp.status_code, 200)
        upload_payload = upload_resp.json()
        self.assertEqual(upload_payload["status"], "uploaded")

        complete_resp = self.client.post(
            f"/agent/attachments/{ticket_payload['attachment_id']}/complete",
            json={"ticket_id": ticket_payload["ticket_id"]},
            headers=self._auth_headers(),
        )
        self.assertEqual(complete_resp.status_code, 200)
        self.assertEqual(complete_resp.json()["status"], "ready")

        attachment = self.core_domain.services.attachment.get_by_attachment_id(ticket_payload["attachment_id"])
        self.assertIsNotNone(attachment)
        self.assertEqual(attachment.status, "ready")
