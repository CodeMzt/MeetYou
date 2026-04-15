from __future__ import annotations

import asyncio
import os
import unittest

from psycopg import connect
from sqlalchemy import select

from core.db.bootstrap import bootstrap_core_domain
from core.db.models.operation import Operation, OperationCall
from core.services.agent_dispatch_service import AgentDispatchError


TEST_DATABASE_NAME = "meetyou_agent_dispatch_test"
ADMIN_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
TEST_DATABASE_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{TEST_DATABASE_NAME}"


class AgentDispatchServiceTests(unittest.IsolatedAsyncioTestCase):
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

    async def asyncSetUp(self):
        self.domain = bootstrap_core_domain(database_url=TEST_DATABASE_URL, run_migrations=True)
        self.desktop_workspace = self.domain.services.workspace.get_by_workspace_id("desktop-main")
        self.client = self.domain.services.client.ensure_client(
            client_id="electron-main",
            principal_id=self.domain.principal.id,
            client_type="electron",
            display_name="Electron Main",
        )
        self.thread = self.domain.services.thread.create_thread(
            principal_id=self.domain.principal.id,
            workspace_id=self.desktop_workspace.id,
            title="Dispatch Thread",
        )
        self.session = self.domain.services.session.create_session(
            thread_id=self.thread.id,
            client_id=self.client.id,
            workspace_id=self.desktop_workspace.id,
        )
        self.agent = self.domain.services.agent.register_agent(
            principal_id=self.domain.principal.id,
            agent_id="desktop-main-agent",
            agent_type="desktop",
            display_name="Desktop Main Agent",
            transport_profile="desktop_wss",
            workspace_rows=[self.desktop_workspace],
            owner_client_id=self.client.id,
        )
        self.domain.services.capability.replace_agent_capabilities(
            agent=self.agent,
            capabilities=[
                {
                    "capability_id": "agent.desktop-main-agent.file.read",
                    "kind": "tool",
                    "title": "Read Local File",
                    "risk_level": "read",
                    "requires_confirmation": False,
                    "workspace_ids": ["desktop-main"],
                }
            ],
            workspace_rows=[self.desktop_workspace],
            revision=1,
        )

    async def asyncTearDown(self):
        self.domain.engine.dispose()

    async def test_dispatch_agent_capability_waits_for_agent_result(self):
        async def fake_transport(*, agent_id: str, payload: dict) -> bool:
            self.assertEqual(agent_id, "desktop-main-agent")
            call_id = payload["payload"]["call_id"]

            async def resolve_later():
                await asyncio.sleep(0.01)
                await self.domain.agent_dispatch.notify_call_result(
                    call_id=call_id,
                    result={"summary": "demo.txt", "content": "hello", "size_bytes": 5},
                )
                self.domain.services.operation_call.mark_succeeded(
                    call_id=call_id,
                    result={"summary": "demo.txt", "content": "hello", "size_bytes": 5},
                )

            asyncio.create_task(resolve_later())
            return True

        self.domain.agent_dispatch.set_transport(fake_transport)
        result = await self.domain.agent_dispatch.dispatch_agent_capability(
            capability_suffix="file.read",
            arguments={"path": "demo.txt"},
            session_id=self.session.session_id,
            title="Read demo.txt for wait-result test",
            operation_type="tool.read_local_documents",
        )

        self.assertEqual(result["content"], "hello")
        with self.domain.session_factory() as session:
            operation = session.execute(
                select(Operation).where(Operation.title == "Read demo.txt for wait-result test")
            ).scalar_one()
            call = session.execute(
                select(OperationCall).where(OperationCall.operation_id == operation.id)
            ).scalar_one()
            self.assertEqual(operation.status, "succeeded")
            self.assertEqual(call.status, "succeeded")

    async def test_dispatch_prefers_client_owned_local_backend(self):
        other_client = self.domain.services.client.ensure_client(
            client_id="feishu-client",
            principal_id=self.domain.principal.id,
            client_type="feishu",
            display_name="Feishu Client",
        )
        self.domain.services.agent.register_agent(
            principal_id=self.domain.principal.id,
            agent_id="shared-desktop-agent",
            agent_type="desktop",
            display_name="Shared Desktop Agent",
            transport_profile="desktop_wss",
            workspace_rows=[self.desktop_workspace],
            owner_client_id=other_client.id,
        )
        selection = self.domain.agent_dispatch._select_target_agent(  # noqa: SLF001
            capability_suffix="file.read",
            session_id=self.session.session_id,
        )
        self.assertEqual(selection.agent.agent_id, "desktop-main-agent")

    async def test_replace_agent_capabilities_truncates_oversized_titles_for_persistence(self):
        long_title = "Read the complete contents of a file from the file system as text. " * 8
        self.domain.services.capability.replace_agent_capabilities(
            agent=self.agent,
            capabilities=[
                {
                    "capability_id": "agent.desktop-main-agent.file.read_text_file",
                    "kind": "tool",
                    "title": long_title,
                    "risk_level": "read",
                    "requires_confirmation": False,
                    "workspace_ids": ["desktop-main"],
                }
            ],
            workspace_rows=[self.desktop_workspace],
            revision=2,
        )

        capability = self.domain.services.capability.get_by_capability_id(
            "agent.desktop-main-agent.file.read_text_file"
        )
        self.assertIsNotNone(capability)
        self.assertLessEqual(len(capability.title), 255)
        self.assertEqual((capability.meta or {}).get("full_title"), long_title)

    async def test_dispatch_encrypts_sensitive_arguments_for_agent_transport(self):
        transport_payload: dict[str, object] = {}

        async def fake_transport(*, agent_id: str, payload: dict) -> bool:
            self.assertEqual(agent_id, "desktop-main-agent")
            transport_payload.update(payload)
            call_id = payload["payload"]["call_id"]

            async def resolve_later():
                await asyncio.sleep(0.01)
                await self.domain.agent_dispatch.notify_call_result(
                    call_id=call_id,
                    result={"summary": "ok"},
                )
                self.domain.services.operation_call.mark_succeeded(
                    call_id=call_id,
                    result={"summary": "ok"},
                )

            asyncio.create_task(resolve_later())
            return True

        self.domain.agent_dispatch.set_transport(fake_transport)
        old_secret = os.environ.get("MEETYOU_CREDENTIAL_SECRET")
        os.environ["MEETYOU_CREDENTIAL_SECRET"] = "dispatch-test-secret"
        try:
            await self.domain.agent_dispatch.dispatch_agent_capability(
                capability_suffix="file.read",
                arguments={"path": "demo.txt", "access_token": "token-abc"},
                session_id=self.session.session_id,
                title="Read demo.txt for encrypted-args test",
                operation_type="tool.read_local_documents",
            )
        finally:
            if old_secret is None:
                os.environ.pop("MEETYOU_CREDENTIAL_SECRET", None)
            else:
                os.environ["MEETYOU_CREDENTIAL_SECRET"] = old_secret

        payload = transport_payload["payload"]
        self.assertEqual(payload["arguments"]["access_token"], "[REDACTED]")
        self.assertTrue(payload["encrypted_arguments"])

        with self.domain.session_factory() as session:
            operation = session.execute(
                select(Operation).where(Operation.title == "Read demo.txt for encrypted-args test")
            ).scalar_one()
            call = session.execute(
                select(OperationCall).where(OperationCall.operation_id == operation.id)
            ).scalar_one()
            self.assertEqual(operation.meta["arguments"]["access_token"], "[REDACTED]")
            self.assertTrue(operation.meta["arguments_encrypted"])
            self.assertEqual(call.arguments["access_token"], "[REDACTED]")

    async def test_dispatch_agent_capability_does_not_fallback_to_other_workspace_agent(self):
        home_lab_workspace = self.domain.services.workspace.get_by_workspace_id("home-lab")
        other_thread = self.domain.services.thread.create_thread(
            principal_id=self.domain.principal.id,
            workspace_id=home_lab_workspace.id,
            title="Home Lab Thread",
        )
        other_session = self.domain.services.session.create_session(
            thread_id=other_thread.id,
            client_id=self.client.id,
            workspace_id=home_lab_workspace.id,
        )

        with self.assertRaises(AgentDispatchError) as error_context:
            await self.domain.agent_dispatch.dispatch_agent_capability(
                capability_suffix="file.read",
                arguments={"path": "demo.txt"},
                session_id=other_session.session_id,
                title="Read demo.txt for home-lab rejection test",
                operation_type="tool.read_local_documents",
            )
        self.assertEqual(error_context.exception.tool_error_code, "agent_capability_unavailable")
        self.assertEqual(error_context.exception.tool_error_details["workspace_id"], "home-lab")
        self.assertEqual(error_context.exception.tool_error_details["capability_suffix"], "file.read")

        with self.domain.session_factory() as session:
            operations = session.execute(
                select(Operation).where(Operation.title == "Read demo.txt for home-lab rejection test")
            ).scalars().all()
            calls = session.execute(
                select(OperationCall).where(
                    OperationCall.operation_id.in_([operation.id for operation in operations])
                )
            ).scalars().all()
            self.assertEqual(len(operations), 0)
            self.assertEqual(len(calls), 0)
