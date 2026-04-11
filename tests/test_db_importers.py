from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from psycopg import connect

from core.config import ConfigManager
from core.db.bootstrap import bootstrap_core_domain
from core.db.importers import import_config_state, import_memory_state, import_source_catalog_state, import_task_state
from core.db.models.config_entry import ConfigEntry
from core.db.models.memory_record import MemoryRecordModel, MemoryWorkspaceTag
from core.db.models.state_blob import RuntimeStateBlob
from core.db.models.task import TaskState
from core.source_catalog import SOURCE_CATALOG_STATE_KEY, SourceCatalogManager


TEST_DATABASE_NAME = "meetyou_import_test"
ADMIN_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
TEST_DATABASE_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{TEST_DATABASE_NAME}"


class DatabaseImporterTests(unittest.TestCase):
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
        self._old_cwd = os.getcwd()
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self._temp_dir.name)
        os.chdir(self.temp_root)
        (self.temp_root / "user").mkdir()
        (self.temp_root / "user" / "config.json").write_text(
            json.dumps({"api_provider": "openai", "model": "gpt-5.4"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.temp_root / "user" / "mcp_servers.json").write_text(json.dumps({"mcpServers": {}}, ensure_ascii=False), encoding="utf-8")
        (self.temp_root / ".env").write_text(
            "MEETYOU_API_KEY=test-secret\nMEETYOU_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/meetyou_import_test\n",
            encoding="utf-8",
        )
        (self.temp_root / "user" / "memory_graph.json").write_text(
            json.dumps(
                {
                    "metadata": {"schema_version": "2", "revision": 1},
                    "records": [
                        {
                            "id": "mem_desktop",
                            "type": "profile",
                            "scope": {"user_id": "desktop-app", "session_id": ""},
                            "content": "desktop memory",
                            "canonical_text": "desktop memory",
                            "status": "active",
                        },
                        {
                            "id": "mem_global",
                            "type": "fact",
                            "scope": {"user_id": "global", "session_id": ""},
                            "content": "global memory",
                            "canonical_text": "global memory",
                            "status": "active",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.temp_root / "user" / "memory_tasks.json").write_text(
            json.dumps(
                {
                    "metadata": {"schema_version": "2", "revision": 1},
                    "tasks": [
                        {
                            "id": "task_desktop",
                            "type": "task",
                            "scope": {"user_id": "desktop-app", "session_id": ""},
                            "content": "desktop task",
                            "status": "active",
                        },
                        {
                            "id": "task_global",
                            "type": "task",
                            "scope": {"user_id": "global", "session_id": ""},
                            "content": "global task",
                            "status": "active",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.temp_root / "user" / "source_catalog.json").write_text(
            json.dumps(
                {
                    "version": "1",
                    "default_source_profiles": {
                        "academic_research": {
                            "preferred_source_ids": ["source_pg"],
                            "official_only": True,
                            "primary_domains": [],
                        }
                    },
                    "context_limits": [],
                    "sources": [
                        {
                            "id": "source_pg",
                            "enabled": True,
                            "domain": "pg.example.com",
                            "label": "Postgres",
                            "connector_type": "rss_atom_feed",
                            "profiles": ["academic_research"],
                            "priority": 50,
                            "primary_source": True,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._temp_dir.cleanup()

    def test_importers_load_current_state_into_database(self):
        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )
        context = bootstrap_core_domain(config, database_url=TEST_DATABASE_URL, run_migrations=True)
        try:
            config_count = import_config_state(config, context.services)
            memory_count = import_memory_state(
                str(self.temp_root / "user" / "memory_graph.json"),
                principal_id=context.principal.id,
                workspaces=context.workspaces,
                services=context.services,
            )
            task_count = import_task_state(
                str(self.temp_root / "user" / "memory_tasks.json"),
                principal_id=context.principal.id,
                workspaces=context.workspaces,
                services=context.services,
            )
            source_catalog_count = import_source_catalog_state(
                str(self.temp_root / "user" / "source_catalog.json"),
                principal_id=context.principal.id,
                services=context.services,
            )

            with context.session_factory() as session:
                self.assertGreaterEqual(config_count, 2)
                self.assertEqual(session.query(ConfigEntry).count(), config_count)
                self.assertEqual(memory_count, 2)
                self.assertEqual(session.query(MemoryRecordModel).count(), 2)
                self.assertEqual(task_count, 2)
                self.assertEqual(session.query(TaskState).count(), 2)
                self.assertEqual(source_catalog_count, 1)
                source_catalog_blob = session.query(RuntimeStateBlob).filter_by(state_key=SOURCE_CATALOG_STATE_KEY).one()
                self.assertEqual(source_catalog_blob.payload_json["sources"][0]["id"], "source_pg")
                desktop_memory = session.query(MemoryRecordModel).filter_by(memory_id="mem_desktop").one()
                self.assertIsNotNone(desktop_memory.origin_workspace_id)
                self.assertEqual(
                    session.query(MemoryWorkspaceTag).filter_by(memory_row_id=desktop_memory.id).count(),
                    1,
                )
            manager = SourceCatalogManager(
                _StaticConfig({"source_catalog_path": str(self.temp_root / "user" / "source_catalog.json")})
            )
            manager.set_store_backend(
                _StateBlobBackendAdapter(
                    context.services,
                    principal_id=context.principal.id,
                    state_key=SOURCE_CATALOG_STATE_KEY,
                )
            )
            self.assertEqual(manager.get_catalog_status()["storage"], "database")
            self.assertEqual(manager.get_source_by_id("source_pg")["label"], "Postgres")
        finally:
            context.engine.dispose()


class _StaticConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key: str, default=None):
        return self._values.get(key, default)


class _StateBlobBackendAdapter:
    def __init__(self, services, *, principal_id, state_key: str):
        self._services = services
        self._principal_id = principal_id
        self._state_key = state_key

    def load(self):
        return self._services.state_blob.load_state(
            principal_id=self._principal_id,
            state_key=self._state_key,
            default_factory=dict,
        )


if __name__ == "__main__":
    unittest.main()
