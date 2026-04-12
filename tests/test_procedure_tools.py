from __future__ import annotations

import asyncio
import unittest

from psycopg import connect

from core.db.bootstrap import bootstrap_core_domain
from core.event_bus import EventBus
from core.io_protocol import make_source
from tools import system_tools
from tools.procedure_tools import ProcedureTools


TEST_DATABASE_NAME = "meetyou_procedure_tools_test"
ADMIN_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
TEST_DATABASE_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{TEST_DATABASE_NAME}"


class ProcedureToolsTests(unittest.IsolatedAsyncioTestCase):
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
        self.core_domain = bootstrap_core_domain(database_url=TEST_DATABASE_URL, run_migrations=True)
        self.event_bus = EventBus()
        system_tools.init_system_tools(None, self.event_bus, allow_local_fallback=False)
        self.tools = ProcedureTools()
        self.tools.set_core_domain(self.core_domain)
        self.client = self.core_domain.services.client.ensure_client(
            client_id="electron-main",
            principal_id=self.core_domain.principal.id,
            client_type="electron",
            display_name="Electron Main",
        )
        self.thread = self.core_domain.services.thread.create_thread(
            principal_id=self.core_domain.principal.id,
            workspace_id=self.core_domain.workspaces["personal"].id,
            title="Procedure tool thread",
        )
        self.session = self.core_domain.services.session.create_session(
            thread_id=self.thread.id,
            client_id=self.client.id,
            workspace_id=self.core_domain.workspaces["personal"].id,
        )

    async def asyncTearDown(self):
        self.core_domain.engine.dispose()

    async def test_propose_pin_waits_for_confirmation_and_applies(self):
        task = asyncio.create_task(
            self.tools.manage_procedures(
                action="propose_pin",
                procedure_id="code_review",
                session_id=self.session.session_id,
                source=make_source("web", "test"),
            )
        )
        await asyncio.sleep(0)
        self.assertTrue(self.event_bus.pending_request_id)
        self.assertTrue(
            self.event_bus.submit_confirmation_response(
                True,
                request_id=self.event_bus.pending_request_id,
                session_id=self.session.session_id,
            )
        )
        payload = await task
        self.assertEqual(payload["status"], "applied")
        refreshed_thread = self.core_domain.services.thread.get_by_thread_id(self.thread.thread_id)
        self.assertEqual(refreshed_thread.pinned_procedure_id, "code_review")

    async def test_propose_create_creates_procedure_after_confirmation(self):
        task = asyncio.create_task(
            self.tools.manage_procedures(
                action="propose_create",
                title="Release Notes Digest",
                description="Summarize release notes and extract action items.",
                applicable_modes=["documents", "general"],
                recommended_capabilities=["summarize_text"],
                infer_keywords=["release notes", "changelog"],
                session_id=self.session.session_id,
                source=make_source("web", "test"),
            )
        )
        await asyncio.sleep(0)
        self.assertTrue(self.event_bus.pending_request_id)
        self.event_bus.submit_confirmation_response(
            True,
            request_id=self.event_bus.pending_request_id,
            session_id=self.session.session_id,
        )
        payload = await task
        self.assertEqual(payload["status"], "applied")
        procedure = self.core_domain.services.procedure.get_by_procedure_id("release_notes_digest")
        self.assertIsNotNone(procedure)


if __name__ == "__main__":
    unittest.main()
