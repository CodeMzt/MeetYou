from __future__ import annotations

import unittest
from pathlib import Path

from psycopg import connect
from sqlalchemy import inspect

from core.db.bootstrap import bootstrap_core_domain


ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_NAME = "meetyou_bootstrap_test"
ADMIN_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres?connect_timeout=5"
TEST_DATABASE_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{TEST_DATABASE_NAME}?connect_timeout=5"


class DatabaseBootstrapTests(unittest.TestCase):
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

    def test_bootstrap_initializes_default_principal_and_workspaces(self):
        context = bootstrap_core_domain(database_url=TEST_DATABASE_URL, run_migrations=True)
        try:
            self.assertEqual(context.principal.principal_key, "self")
            self.assertEqual(set(context.workspaces), {"personal", "desktop-main", "study", "home-lab"})
            self.assertEqual(context.workspaces["desktop-main"].default_execution_target, "specific_client")
            self.assertTrue(context.workspaces["desktop-main"].prompt_overlay)
            self.assertEqual(context.workspaces["home-lab"].default_execution_target, "workspace_any_client")
            inspector = inspect(context.engine)
            tables = set(inspector.get_table_names())
            self.assertIn("config_entries", tables)
            self.assertIn("memory_records", tables)
            self.assertIn("procedures", tables)
            self.assertIn("tasks", tables)
            self.assertNotIn("agents", tables)
            self.assertNotIn("workspace_agent_memberships", tables)
            procedure = context.services.procedure.get_by_procedure_id("code_review")
            self.assertIsNotNone(procedure)
        finally:
            context.engine.dispose()

    def test_service_layer_can_create_thread_session_operation_chain(self):
        context = bootstrap_core_domain(database_url=TEST_DATABASE_URL, run_migrations=True)
        try:
            client = context.services.client.ensure_client(
                client_id="electron-main",
                principal_id=context.principal.id,
                client_type="electron",
                display_name="Electron Main",
            )
            thread = context.services.thread.create_thread(
                principal_id=context.principal.id,
                workspace_id=context.workspaces["personal"].id,
                title="Bootstrap thread",
                pinned_procedure_id="code_review",
            )
            session = context.services.session.create_session(
                thread_id=thread.id,
                client_id=client.id,
                workspace_id=context.workspaces["personal"].id,
            )
            operation = context.services.operation.create_operation(
                thread_id=thread.id,
                workspace_id=context.workspaces["personal"].id,
                operation_type="capture_screenshot",
                execution_target="specific_client",
                title="Capture screenshot",
            )
            approval = context.services.approval.create_approval(
                operation_id=operation.id,
                approval_type="high_risk_action",
                risk_level="write",
            )

            self.assertIsNotNone(context.services.thread.get_by_thread_id(thread.thread_id))
            self.assertEqual(context.services.thread.get_by_thread_id(thread.thread_id).pinned_procedure_id, "code_review")
            self.assertIsNotNone(context.services.session.get_by_session_id(session.session_id))
            self.assertIsNotNone(context.services.operation.get_by_operation_id(operation.operation_id))
            self.assertIsNotNone(context.services.approval.get_by_approval_id(approval.approval_id))
        finally:
            context.engine.dispose()

    def test_procedure_service_can_infer_from_content(self):
        context = bootstrap_core_domain(database_url=TEST_DATABASE_URL, run_migrations=True)
        try:
            inferred = context.services.procedure.infer_for_turn(
                principal_id=context.principal.id,
                content="Please review this patch for regressions and risky changes.",
                preferred_mode="general",
                workspace_id="personal",
            )
            self.assertTrue(inferred["matched"])
            self.assertEqual(inferred["procedure_id"], "code_review")
            self.assertGreater(inferred["score"], 0)
        finally:
            context.engine.dispose()


if __name__ == "__main__":
    unittest.main()
