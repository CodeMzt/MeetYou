from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.state_backends import RuntimeStateBlobBackend
from tools.document_tools import DocumentTools
from tools.memory import Memory
from tools.office_tools import OfficeTools
from tools.study_tools import StudyTools
from tools.task_manager import TaskManager


class _InMemoryStateBlobService:
    def __init__(self):
        self.state = {}

    def load_state(self, *, principal_id, state_key: str, default_factory):
        return self.state.get((str(principal_id), state_key), default_factory())

    def save_state(self, *, principal_id, state_key: str, payload: dict, meta: dict | None = None):
        self.state[(str(principal_id), state_key)] = dict(payload or {})
        return None


class _FakeMemory:
    def __init__(self):
        self._memory_file_path = ""
        self._embedding_model = "fake-embedding"

    def _resolve_user_id(self, source):
        if isinstance(source, dict):
            return source.get("id", "global")
        return getattr(source, "id", "global") or "global"

    def _record_scope(self, user_id: str, session_id: str, record_type: str):
        return {"user_id": user_id, "session_id": session_id if record_type == "episode" else ""}

    async def save_memory_graph(self):
        return None


class _FakeModeManager:
    def get_document_parser_config(self):
        return {"max_file_bytes": 2_000_000, "max_total_chars": 24_000, "max_chunks_per_document": 12, "enable_ocr": False}

    def get_trusted_write_roots(self):
        return [str(Path.cwd().resolve())]

    def is_trusted_write_path(self, path_value: str):
        return str(Path(path_value).resolve()).startswith(str(Path.cwd().resolve()))

    def get_office_integrations(self):
        return {"local": {"enabled": True, "draft_only": False}}


class RuntimeStateBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_persists_to_blob_backend(self):
        service = _InMemoryStateBlobService()
        backend = RuntimeStateBlobBackend(service, principal_id="self", state_key="memory_graph", default_factory=dict)

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "memory.json"

            class _Config:
                def get(self, key, default=None):
                    values = {
                        "memory_file_path": str(config_path),
                        "embedding_model": "fake-embedding",
                        "embedding_api_key": "",
                        "embedding_api_url": "",
                    }
                    return values.get(key, default)

            memory = Memory()
            await memory.init_memory(_Config())
            memory.set_store_backend(backend, migrate_current=True)
            async def _fake_embedding(text: str):
                return [0.1, 0.2, 0.3]
            memory._get_embedding = _fake_embedding
            await memory.save_memory("把服务端记忆迁移到 state blob", source={"id": "desktop-user"})

            stored = service.state[("self", "memory_graph")]
            self.assertEqual(len(stored["records"]), 1)
            self.assertEqual(stored["records"][0]["content"], "把服务端记忆迁移到 state blob")
            await memory.close_memory()

    async def test_task_manager_persists_to_blob_backend(self):
        service = _InMemoryStateBlobService()
        backend = RuntimeStateBlobBackend(service, principal_id="self", state_key="task_store", default_factory=dict)
        manager = TaskManager(_FakeMemory())
        manager.set_store_backend(backend, migrate_current=True)

        payload = json.loads(
            await manager.manage_tasks(
                action="create",
                summary="收口旧任务状态",
                source={"id": "desktop-user"},
            )
        )

        self.assertEqual(payload["status"], "success")
        stored = service.state[("self", "task_store")]
        self.assertEqual(len(stored["tasks"]), 1)

    async def test_office_and_study_tools_persist_to_blob_backend(self):
        service = _InMemoryStateBlobService()
        office_backend = RuntimeStateBlobBackend(service, principal_id="self", state_key="office_state", default_factory=dict)
        study_backend = RuntimeStateBlobBackend(service, principal_id="self", state_key="study_progress", default_factory=dict)

        with tempfile.TemporaryDirectory() as tmp_dir:
            old_cwd = Path.cwd()
            root = Path(tmp_dir)
            try:
                import os
                os.chdir(root)
                doc_tools = DocumentTools(_FakeModeManager())
                office = OfficeTools(_FakeModeManager(), doc_tools)
                office.set_state_backend(office_backend)
                study = StudyTools(doc_tools)
                study.set_state_backend(study_backend)

                office_payload = json.loads(
                    await office.manage_schedule(action="draft", when="明天 9:00", title="开会", source_system="local")
                )
                study_payload = json.loads(
                    await study.track_mastery(action="update", topic="LLM 架构", score=0.8, notes="需要复习")
                )

                self.assertEqual(office_payload["status"], "draft")
                self.assertEqual(study_payload["status"], "updated")
                self.assertEqual(len(service.state[("self", "office_state")]["schedules"]), 1)
                self.assertEqual(len(service.state[("self", "study_progress")]["topics"]), 1)
            finally:
                os.chdir(old_cwd)
