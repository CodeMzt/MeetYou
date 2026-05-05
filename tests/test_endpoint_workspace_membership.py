from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
import unittest

from alembic import command
from alembic.config import Config
import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.bootstrap import build_core_services


ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "alembic.ini"
MIGRATION_TEST_DATABASE_NAME = "meetyou_endpoint_membership_migration_test"
ADMIN_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres?connect_timeout=5"
MIGRATION_TEST_DATABASE_URL = (
    f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{MIGRATION_TEST_DATABASE_NAME}?connect_timeout=5"
)


class EndpointWorkspaceMembershipTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.services = build_core_services(self.session_factory)
        self.principal = self.services.principal.ensure_principal(principal_key="self", display_name="Self")
        self.personal = self.services.workspace.ensure_workspace(
            workspace_id="personal",
            principal_id=self.principal.id,
            title="Personal",
        )
        self.study = self.services.workspace.ensure_workspace(
            workspace_id="study",
            principal_id=self.principal.id,
            title="Study",
        )

    def tearDown(self):
        self.engine.dispose()

    def test_provider_seed_does_not_override_core_managed_primary_workspace(self):
        endpoint = self.services.endpoint.ensure_endpoint(
            endpoint_id="desktop.main.executor",
            endpoint_type="desktop_executor",
            provider_type="desktop",
            transport_type="websocket",
            workspace_scope=["personal"],
        )
        seeded_scope = self.services.endpoint_workspace_membership.seed_endpoint_memberships(
            endpoint_row_id=endpoint.id,
            workspace_ids=["personal"],
        )

        self.assertEqual(seeded_scope, ["personal"])

        result = self.services.endpoint_workspace_membership.set_primary_workspace(
            endpoint_id="desktop.main.executor",
            workspace_id="study",
        )
        self.assertEqual(result["primary_workspace_id"], "study")
        self.assertEqual(result["workspace_ids"], ["study", "personal"])

        reseeded_scope = self.services.endpoint_workspace_membership.seed_endpoint_memberships(
            endpoint_row_id=endpoint.id,
            workspace_ids=["personal"],
        )
        refreshed = self.services.endpoint.get_by_endpoint_id("desktop.main.executor")

        self.assertEqual(reseeded_scope, ["study", "personal"])
        self.assertEqual(refreshed.workspace_scope, ["study", "personal"])
        self.assertEqual((refreshed.meta or {}).get("primary_workspace_id"), "study")

    def test_remove_membership_syncs_cache_and_rejects_last_workspace(self):
        endpoint = self.services.endpoint.ensure_endpoint(
            endpoint_id="desktop.main.executor",
            endpoint_type="desktop_executor",
            provider_type="desktop",
            transport_type="websocket",
            workspace_scope=["personal"],
        )
        self.services.endpoint_workspace_membership.seed_endpoint_memberships(
            endpoint_row_id=endpoint.id,
            workspace_ids=["personal", "study"],
        )

        result = self.services.endpoint_workspace_membership.remove_workspace(
            endpoint_id="desktop.main.executor",
            workspace_id="personal",
        )
        refreshed = self.services.endpoint.get_by_endpoint_id("desktop.main.executor")

        self.assertEqual(result["workspace_ids"], ["study"])
        self.assertEqual(refreshed.workspace_scope, ["study"])
        with self.assertRaises(ValueError):
            self.services.endpoint_workspace_membership.remove_workspace(
                endpoint_id="desktop.main.executor",
                workspace_id="study",
            )

    def test_core_endpoints_are_readonly_for_workspace_membership_mutations(self):
        self.services.endpoint.ensure_endpoint(
            endpoint_id="core.local",
            endpoint_type="core_local",
            provider_type="core",
            transport_type="inproc",
        )

        with self.assertRaises(ValueError):
            self.services.endpoint_workspace_membership.set_primary_workspace(
                endpoint_id="core.local",
                workspace_id="personal",
            )

    def test_acceptance_probe_cleanup_archives_endpoint_and_disables_capabilities(self):
        endpoint = self.services.endpoint.ensure_endpoint(
            endpoint_id="desktop.v4check-deadbeef.executor",
            endpoint_type="desktop_executor",
            provider_type="desktop",
            transport_type="websocket",
            workspace_scope=["personal"],
            status="online",
            metadata={
                "provider": {
                    "provider_id": "v4check-deadbeef",
                    "display_name": "V4 Acceptance Endpoint",
                    "transport_profile": "acceptance_ws",
                }
            },
        )
        self.services.endpoint_workspace_membership.seed_endpoint_memberships(
            endpoint_row_id=endpoint.id,
            workspace_ids=["personal"],
        )
        self.services.endpoint_capability.upsert_capability(
            endpoint_row_id=endpoint.id,
            tool_key="utility.echo",
            capability_id="endpoint.desktop.v4check-deadbeef.executor.utility.echo",
        )

        retired = self.services.endpoint.retire_acceptance_probe_endpoints()
        refreshed = self.services.endpoint.get_by_endpoint_id("desktop.v4check-deadbeef.executor")
        capabilities = self.services.endpoint_capability.list_for_endpoint(endpoint_row_id=endpoint.id)

        self.assertEqual(retired, 1)
        self.assertEqual(refreshed.status, "archived")
        self.assertTrue((refreshed.meta or {}).get("operator_hidden"))
        self.assertFalse(any(capability.enabled for capability in capabilities))


class EndpointWorkspaceMembershipMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls._drop_database(MIGRATION_TEST_DATABASE_NAME)
            cls._create_database(MIGRATION_TEST_DATABASE_NAME)
        except psycopg.OperationalError as exc:
            raise unittest.SkipTest(f"PostgreSQL is not available: {exc}") from exc

    @classmethod
    def tearDownClass(cls):
        try:
            cls._drop_database(MIGRATION_TEST_DATABASE_NAME)
        except psycopg.OperationalError:
            pass

    @staticmethod
    def _admin_connect():
        return psycopg.connect(ADMIN_DATABASE_URL, autocommit=True)

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
    def _run_migration(revision: str) -> None:
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", MIGRATION_TEST_DATABASE_URL)
        command.upgrade(config, revision)

    def test_existing_scope_json_backfills_membership_metadata_on_psycopg(self):
        self._run_migration("20260430_000014")
        principal_id = uuid.uuid4()
        personal_id = uuid.uuid4()
        study_id = uuid.uuid4()
        endpoint_id = uuid.uuid4()
        address_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        engine = create_engine(MIGRATION_TEST_DATABASE_URL, future=True)

        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO principals (id, principal_key, display_name, status, metadata, created_at, updated_at)
                        VALUES (:id, 'self', 'Self', 'active', CAST(:metadata AS JSON), :created_at, :updated_at)
                        """
                    ),
                    {"id": principal_id, "metadata": json.dumps({}), "created_at": now, "updated_at": now},
                )
                for workspace_uuid, workspace_id, title in (
                    (personal_id, "personal", "Personal"),
                    (study_id, "study", "Study"),
                ):
                    conn.execute(
                        text(
                            """
                            INSERT INTO workspaces (
                                id, workspace_id, principal_id, title, description, status, base_mode,
                                prompt_overlay, default_execution_target, metadata, created_at, updated_at
                            )
                            VALUES (
                                :id, :workspace_id, :principal_id, :title, '', 'active', 'general',
                                '', 'core.local', CAST(:metadata AS JSON), :created_at, :updated_at
                            )
                            """
                        ),
                        {
                            "id": workspace_uuid,
                            "workspace_id": workspace_id,
                            "principal_id": principal_id,
                            "title": title,
                            "metadata": json.dumps({}),
                            "created_at": now,
                            "updated_at": now,
                        },
                    )
                conn.execute(
                    text(
                        """
                        INSERT INTO endpoints (
                            id, endpoint_id, endpoint_type, provider_type, transport_type, workspace_scope,
                            status, labels, priority, metadata, created_at, updated_at
                        )
                        VALUES (
                            :id, 'desktop.main.executor', 'desktop_executor', 'desktop', 'websocket',
                            CAST(:workspace_scope AS JSON), 'online', CAST(:labels AS JSON), 100,
                            CAST(:metadata AS JSON), :created_at, :updated_at
                        )
                        """
                    ),
                    {
                        "id": endpoint_id,
                        "workspace_scope": json.dumps(["personal", "study"]),
                        "labels": json.dumps([]),
                        "metadata": json.dumps({}),
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO endpoint_addresses (
                            id, address_id, endpoint_id, provider_type, address_type, external_ref, display_name,
                            workspace_scope, status, capabilities, metadata, created_at, updated_at
                        )
                        VALUES (
                            :id, 'addr.desktop.self', :endpoint_id, 'desktop', 'direct', 'self', 'Self',
                            CAST(:workspace_scope AS JSON), 'online', CAST(:capabilities AS JSON),
                            CAST(:metadata AS JSON), :created_at, :updated_at
                        )
                        """
                    ),
                    {
                        "id": address_id,
                        "endpoint_id": endpoint_id,
                        "workspace_scope": json.dumps(["study"]),
                        "capabilities": json.dumps([]),
                        "metadata": json.dumps({}),
                        "created_at": now,
                        "updated_at": now,
                    },
                )
        finally:
            engine.dispose()

        self._run_migration("head")
        engine = create_engine(MIGRATION_TEST_DATABASE_URL, future=True)
        try:
            with engine.connect() as conn:
                endpoint_rows = conn.execute(
                    text(
                        """
                        SELECT w.workspace_id, m.is_primary, m.metadata
                        FROM endpoint_workspace_memberships m
                        JOIN workspaces w ON w.id = m.workspace_id
                        WHERE m.endpoint_id = :endpoint_id
                        ORDER BY m.is_primary DESC, w.workspace_id
                        """
                    ),
                    {"endpoint_id": endpoint_id},
                ).mappings().all()
                address_rows = conn.execute(
                    text(
                        """
                        SELECT w.workspace_id, m.is_primary, m.metadata
                        FROM endpoint_address_workspace_memberships m
                        JOIN workspaces w ON w.id = m.workspace_id
                        WHERE m.address_id = :address_id
                        ORDER BY m.is_primary DESC, w.workspace_id
                        """
                    ),
                    {"address_id": address_id},
                ).mappings().all()

            self.assertEqual(
                [(row["workspace_id"], row["is_primary"]) for row in endpoint_rows],
                [("personal", True), ("study", False)],
            )
            self.assertEqual(endpoint_rows[0]["metadata"]["migrated_from_workspace_scope"], ["personal", "study"])
            self.assertEqual(
                [(row["workspace_id"], row["is_primary"]) for row in address_rows],
                [("study", True)],
            )
            self.assertEqual(address_rows[0]["metadata"]["migrated_from_workspace_scope"], ["study"])
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
