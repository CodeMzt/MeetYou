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
            self.assertEqual(context.workspaces["desktop-main"].default_execution_target, "endpoint")
            self.assertTrue(context.workspaces["desktop-main"].prompt_overlay)
            self.assertEqual(context.workspaces["home-lab"].default_execution_target, "workspace_any_endpoint")
            inspector = inspect(context.engine)
            tables = set(inspector.get_table_names())
            self.assertIn("config_entries", tables)
            self.assertIn("memory_records", tables)
            self.assertNotIn("procedures", tables)
            self.assertIn("tasks", tables)
            self.assertIn("actors", tables)
            self.assertIn("endpoints", tables)
            self.assertIn("endpoint_capabilities", tables)
            self.assertIn("runs", tables)
            self.assertIn("run_events", tables)
            self.assertIn("scheduled_jobs", tables)
            self.assertIn("scheduled_job_runs", tables)
            self.assertIn("endpoint_outbox", tables)
            self.assertNotIn("agents", tables)
            self.assertNotIn("workspace_agent_memberships", tables)
            self.assertIsNotNone(context.services.actor.get_by_actor_id("system.scheduler"))
            self.assertIsNotNone(context.services.actor.get_by_actor_id("system.heartbeat"))
            user_actor = context.services.actor.get_by_actor_id("user:self")
            self.assertIsNotNone(user_actor)
            self.assertEqual(user_actor.owner_user_id, "self")
            self.assertIsNotNone(context.services.endpoint.get_by_endpoint_id("core.local"))
            self.assertIsNotNone(context.services.endpoint.get_by_endpoint_id("core.scheduler"))
            heartbeat = context.services.scheduler.get_job("system.heartbeat")
            self.assertIsNotNone(heartbeat)
            self.assertFalse(heartbeat.deletable)
        finally:
            context.engine.dispose()

    def test_service_layer_can_create_thread_session_operation_chain(self):
        context = bootstrap_core_domain(database_url=TEST_DATABASE_URL, run_migrations=True)
        try:
            endpoint = context.services.endpoint.ensure_endpoint(
                endpoint_id="desktop.electron-main.executor",
                endpoint_type="desktop_executor",
                provider_type="desktop",
                transport_type="websocket",
                workspace_scope=["personal"],
            )
            thread = context.services.thread.create_thread(
                principal_id=context.principal.id,
                workspace_id=context.workspaces["personal"].id,
                title="Bootstrap thread",
            )
            session = context.services.session.create_session(
                thread_id=thread.id,
                origin_endpoint_id=endpoint.id,
                workspace_id=context.workspaces["personal"].id,
            )
            operation = context.services.operation.create_operation(
                thread_id=thread.id,
                workspace_id=context.workspaces["personal"].id,
                operation_type="capture_screenshot",
                execution_target="endpoint",
                execution_target_type="endpoint",
                execution_target_id=endpoint.endpoint_id,
                target_endpoint_id=endpoint.id,
                title="Capture screenshot",
            )
            approval = context.services.approval.create_approval(
                operation_id=operation.id,
                approval_type="high_risk_action",
                risk_level="write",
            )
            actor = context.services.actor.get_by_actor_id("system.scheduler")
            endpoint = context.services.endpoint.get_by_endpoint_id("core.local")
            run = context.services.run.create_run(
                workspace_id=context.workspaces["personal"].id,
                thread_id=thread.id,
                trigger_type="manual",
                origin_actor_id=actor.id,
                origin_endpoint_id=endpoint.id,
                status="running",
            )
            event = context.services.run_event.emit_progress_notice(
                run_id=run.id,
                thread_id=thread.id,
                text="checking",
            )

            self.assertIsNotNone(context.services.thread.get_by_thread_id(thread.thread_id))
            self.assertIsNotNone(context.services.session.get_by_session_id(session.session_id))
            self.assertIsNotNone(context.services.operation.get_by_operation_id(operation.operation_id))
            self.assertIsNotNone(context.services.approval.get_by_approval_id(approval.approval_id))
            self.assertEqual(event.type, "assistant.progress_notice")
            self.assertFalse(event.durable)
            self.assertEqual(context.services.scheduler.get_job("system.heartbeat").job_id, "system.heartbeat")
        finally:
            context.engine.dispose()

if __name__ == "__main__":
    unittest.main()
