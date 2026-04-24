from __future__ import annotations

import uuid
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from psycopg import connect
from sqlalchemy import inspect, text

from core.db.engine import create_db_engine, create_session_factory
from core.db.repositories import (
    AgentRepository,
    ApprovalRepository,
    AttachmentRepository,
    ContextPoolRepository,
    ClientRepository,
    OperationRepository,
    PrincipalRepository,
    SessionRepository,
    ThreadRepository,
    WorkspaceRepository,
)


ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "alembic.ini"
TEST_DATABASE_NAME = "meetyou_phase1_test"
ADMIN_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
TEST_DATABASE_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{TEST_DATABASE_NAME}"


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
                "agents",
                "workspace_agent_memberships",
                "threads",
                "sessions",
                "operations",
                "approvals",
                "attachments",
                "client_workspace_memberships",
                "context_pool_items",
            }.issubset(tables)
        )

    def test_repositories_can_create_phase1_resource_chain(self):
        with self.session_factory() as session:
            principal_repo = PrincipalRepository(session)
            client_repo = ClientRepository(session)
            workspace_repo = WorkspaceRepository(session)
            agent_repo = AgentRepository(session)
            context_pool_repo = ContextPoolRepository(session)
            thread_repo = ThreadRepository(session)
            session_repo = SessionRepository(session)
            operation_repo = OperationRepository(session)
            approval_repo = ApprovalRepository(session)
            attachment_repo = AttachmentRepository(session)

            principal = principal_repo.create(principal_key="self", display_name="Self")
            client = client_repo.create(
                client_id="desktop-main",
                principal_id=principal.id,
                client_type="electron",
                display_name="Desktop Main",
            )
            workspace = workspace_repo.create(
                workspace_id="personal",
                principal_id=principal.id,
                title="Personal",
            )
            agent = agent_repo.create(
                agent_id="desktop-main-agent",
                principal_id=principal.id,
                agent_type="desktop",
                display_name="Desktop Agent",
                transport_profile="desktop_wss",
            )
            agent_repo.bind_workspace(workspace_id=workspace.id, agent_id=agent.id)
            client_repo.bind_workspace(workspace_id=workspace.id, client_id=client.id)
            thread = thread_repo.create(
                thread_id=f"thr_{uuid.uuid4().hex}",
                principal_id=principal.id,
                home_workspace_id=workspace.id,
                title="Phase 1 Test",
            )
            conversation = session_repo.create(
                session_id=f"sess_{uuid.uuid4().hex}",
                thread_id=thread.id,
                client_id=client.id,
                active_workspace_id=workspace.id,
            )
            context_item = context_pool_repo.create(
                context_id=f"ctx_{uuid.uuid4().hex}",
                principal_id=principal.id,
                thread_id=thread.id,
                session_id=conversation.id,
                source_client_id=client.id,
                home_workspace_id=workspace.id,
                active_workspace_id=workspace.id,
                content="Desktop client asked about payment callback retries.",
                canonical_text="desktop client asked about payment callback retries",
                role="user",
            )
            operation = operation_repo.create(
                operation_id=f"op_{uuid.uuid4().hex}",
                thread_id=thread.id,
                workspace_id=workspace.id,
                operation_type="capture_screenshot",
                execution_target="specific_agent",
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
            self.assertIsNotNone(client_repo.get_by_client_id("desktop-main"))
            self.assertIsNotNone(workspace_repo.get_by_workspace_id("personal"))
            self.assertIsNotNone(agent_repo.get_by_agent_id("desktop-main-agent"))
            self.assertTrue(client_repo.is_bound_to_workspace(client_id="desktop-main", workspace_id=workspace.id))
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


if __name__ == "__main__":
    unittest.main()
