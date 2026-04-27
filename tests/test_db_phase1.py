from __future__ import annotations

import uuid
import unittest
from datetime import timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from psycopg import connect
from sqlalchemy import inspect, text

from core.db.base import utcnow
from core.db.engine import create_db_engine, create_session_factory
from core.db.repositories import (
    ApprovalRepository,
    AttachmentRepository,
    ContextPoolRepository,
    EndpointCapabilityRepository,
    EndpointRepository,
    OperationRepository,
    PrincipalRepository,
    SessionRepository,
    ThreadRepository,
    WorkspaceRepository,
)


ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "alembic.ini"
TEST_DATABASE_NAME = "meetyou_phase1_test"
ADMIN_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres?connect_timeout=5"
TEST_DATABASE_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{TEST_DATABASE_NAME}?connect_timeout=5"


class DatabasePhase1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._drop_database(TEST_DATABASE_NAME)
        cls._create_database(TEST_DATABASE_NAME)
        cls._run_migration("upgrade")

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

    @staticmethod
    def _run_migration(direction: str) -> None:
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
        if direction == "upgrade":
            command.upgrade(config, "head")
        else:
            command.downgrade(config, "base")

    def setUp(self):
        self.engine = create_db_engine(TEST_DATABASE_URL)
        self.session_factory = create_session_factory(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_migration_creates_expected_phase1_tables(self):
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        self.assertTrue(
            {
                "principals",
                "clients",
                "workspaces",
                "threads",
                "sessions",
                "operations",
                "approvals",
                "attachments",
                "client_workspace_memberships",
                "context_pool_items",
                "actors",
                "endpoints",
                "endpoint_connections",
                "endpoint_capabilities",
                "runs",
                "run_events",
                "scheduled_jobs",
                "scheduled_job_runs",
                "endpoint_outbox",
                "delivery_attempts",
            }.issubset(tables)
        )
        self.assertNotIn("agents", tables)
        self.assertNotIn("workspace_agent_memberships", tables)
        self.assertNotIn("agent_capability_snapshots", tables)

    def test_repositories_can_create_phase1_resource_chain(self):
        with self.session_factory() as session:
            principal_repo = PrincipalRepository(session)
            endpoint_repo = EndpointRepository(session)
            endpoint_capability_repo = EndpointCapabilityRepository(session)
            workspace_repo = WorkspaceRepository(session)
            context_pool_repo = ContextPoolRepository(session)
            thread_repo = ThreadRepository(session)
            session_repo = SessionRepository(session)
            operation_repo = OperationRepository(session)
            approval_repo = ApprovalRepository(session)
            attachment_repo = AttachmentRepository(session)

            principal = principal_repo.create(principal_key="self", display_name="Self")
            endpoint = endpoint_repo.upsert(
                endpoint_id="desktop-main.executor",
                endpoint_type="tool_executor",
                provider_type="desktop",
                transport_type="websocket",
                status="online",
                workspace_scope=["personal"],
                labels=["local_tools"],
                metadata={"display_name": "Desktop Main"},
            )
            endpoint_capability = endpoint_capability_repo.upsert(
                endpoint_id=endpoint.id,
                tool_key="shell.exec",
                capability_id="endpoint.desktop-main.executor.shell.exec",
                risk_level="system",
            )
            workspace = workspace_repo.create(
                workspace_id="personal",
                principal_id=principal.id,
                title="Personal",
            )
            thread = thread_repo.create(
                thread_id=f"thr_{uuid.uuid4().hex}",
                principal_id=principal.id,
                home_workspace_id=workspace.id,
                title="Phase 1 Test",
            )
            conversation = session_repo.create(
                session_id=f"sess_{uuid.uuid4().hex}",
                thread_id=thread.id,
                origin_endpoint_id=endpoint.id,
                active_workspace_id=workspace.id,
            )
            context_item = context_pool_repo.create(
                context_id=f"ctx_{uuid.uuid4().hex}",
                principal_id=principal.id,
                thread_id=thread.id,
                session_id=conversation.id,
                origin_endpoint_id=endpoint.id,
                home_workspace_id=workspace.id,
                active_workspace_id=workspace.id,
                content="Desktop endpoint asked about payment callback retries.",
                canonical_text="desktop endpoint asked about payment callback retries",
                role="user",
            )
            operation = operation_repo.create(
                operation_id=f"op_{uuid.uuid4().hex}",
                thread_id=thread.id,
                workspace_id=workspace.id,
                operation_type="capture_screenshot",
                execution_target="specific_endpoint",
                execution_target_type="endpoint",
                execution_target_id=endpoint.endpoint_id,
                target_endpoint_id=endpoint.id,
                title="Capture screenshot",
            )
            approval = approval_repo.create(
                approval_id=f"approval_{uuid.uuid4().hex}",
                operation_id=operation.id,
                approval_type="high_risk_action",
                risk_level="write",
            )
            attachment = attachment_repo.create(
                attachment_id=f"att_{uuid.uuid4().hex}",
                owner_type="operation",
                owner_id=operation.operation_id,
                kind="image",
                mime_type="image/png",
                object_key="ops/test.png",
                size_bytes=128,
            )
            session.commit()

            self.assertIsNotNone(principal_repo.get_by_principal_key("self"))
            self.assertIsNotNone(endpoint_repo.get_by_endpoint_id("desktop-main.executor"))
            self.assertIsNotNone(endpoint_capability_repo.get_by_capability_id(endpoint_capability.capability_id))
            self.assertIsNotNone(workspace_repo.get_by_workspace_id("personal"))
            self.assertIsNotNone(thread_repo.get_by_thread_id(thread.thread_id))
            self.assertIsNotNone(session_repo.get_by_session_id(conversation.session_id))
            self.assertIsNotNone(context_pool_repo.get_by_context_id(context_item.context_id))
            self.assertIsNotNone(operation_repo.get_by_operation_id(operation.operation_id))
            self.assertIsNotNone(approval_repo.get_by_approval_id(approval.approval_id))
            self.assertIsNotNone(attachment_repo.get_by_attachment_id(attachment.attachment_id))

    def test_database_connection_is_available_for_phase1(self):
        with self.engine.connect() as conn:
            value = conn.execute(text("SELECT 1")).scalar_one()
        self.assertEqual(value, 1)

    def test_context_pool_prune_keeps_high_importance_and_bounds_active_window(self):
        with self.session_factory() as session:
            principal = PrincipalRepository(session).create(principal_key="context-prune", display_name="Context Prune")
            repo = ContextPoolRepository(session)
            now = utcnow()
            rows = []
            for idx in range(6):
                row = repo.create(
                    context_id=f"ctx_prune_{idx}",
                    principal_id=principal.id,
                    content=f"context item {idx}",
                    canonical_text=f"context item {idx}",
                    importance=0.95 if idx == 0 else 0.1,
                )
                row.created_at = now - timedelta(minutes=idx)
                rows.append(row)

            pruned = repo.prune_for_principal(principal_id=principal.id, max_items=3)
            active = repo.list_active_for_principal(principal_id=principal.id)
            active_ids = {row.context_id for row in active}

            self.assertEqual(pruned, 3)
            self.assertEqual(len(active), 3)
            self.assertIn("ctx_prune_0", active_ids)
            self.assertTrue(all(row.status == "pruned" for row in rows if row.context_id not in active_ids))


if __name__ == "__main__":
    unittest.main()
