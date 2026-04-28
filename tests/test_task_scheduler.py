import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.task_manager import TaskManager


class _FakeMemory:
    def __init__(self):
        self._embedding_model = "fake-embedding"
        self._store = {"records": [], "edges": [], "metadata": {}, "working_summaries": {}}
        self.saved = 0

    def _resolve_user_id(self, source):
        if isinstance(source, dict):
            return source.get("id", "global")
        return getattr(source, "id", "global") or "global"

    def _record_scope(self, user_id: str, session_id: str, record_type: str):
        return {"user_id": user_id, "session_id": session_id if record_type == "episode" else ""}

    async def _get_embedding(self, text: str):
        return [float(len(text or "")), 1.0]

    def _link_semantic_edges(self, record):
        return None

    async def save_memory_graph(self):
        self.saved += 1


class TaskSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_manage_tasks_supports_detail_delete_and_restore(self):
        manager = TaskManager(_FakeMemory())
        created = json.loads(
            await manager.manage_tasks(
                action="create",
                summary="Fix payment callback retries",
                source={"id": "desktop-user"},
            )
        )
        task_key = created["tasks"][0]["task_key"]

        detailed = json.loads(
            await manager.manage_tasks(
                action="detail",
                task_key=task_key,
                source={"id": "desktop-user"},
            )
        )
        self.assertEqual(detailed["status"], "success")
        self.assertEqual(detailed["objects"][0]["object_id"], task_key)

        with patch("tools.task_manager.request_user_confirmation", AsyncMock(return_value=True)):
            deleted = json.loads(
                await manager.manage_tasks(
                    action="delete",
                    task_key=task_key,
                    session_id="web:session:1",
                    source={"id": "desktop-user"},
                )
            )
        self.assertEqual(deleted["status"], "success")
        self.assertEqual(deleted["objects"][0]["status"], "deleted")

        with patch("tools.task_manager.request_user_confirmation", AsyncMock(return_value=True)):
            restored = json.loads(
                await manager.manage_tasks(
                    action="restore",
                    task_key=task_key,
                    session_id="web:session:1",
                    source={"id": "desktop-user"},
                )
            )
        self.assertEqual(restored["status"], "success")
        self.assertEqual(restored["objects"][0]["status"], "active")

    async def test_manage_tasks_returns_ambiguous_candidates_for_non_unique_query(self):
        manager = TaskManager(_FakeMemory())
        await manager.manage_tasks(action="create", summary="整理日报", source={"id": "desktop-user"})
        await manager.manage_tasks(action="create", summary="整理日报并归档", source={"id": "desktop-user"})

        payload = json.loads(
            await manager.manage_tasks(
                action="detail",
                query="日报",
                source={"id": "desktop-user"},
            )
        )
        self.assertEqual(payload["status"], "ambiguous")
        self.assertEqual(len(payload["candidates"]), 2)

    async def test_manage_tasks_rejects_schedule_fields_for_user_todo(self):
        manager = TaskManager(_FakeMemory())

        failed = await manager.manage_tasks(
            action="create",
            summary="Run a daily digest",
            schedule_kind="recurring",
            recurrence={"freq": "daily", "hour": 9},
            source={"id": "desktop-user"},
        )

        self.assertFalse(failed.ok)
        self.assertEqual(failed.error.code, "task_domain_invalid")
        self.assertIn("manage_scheduled_jobs", failed.error.message)

    async def test_task_manager_exposes_user_todo_tool_only(self):
        manager = TaskManager(_FakeMemory())

        self.assertTrue(callable(getattr(manager, "manage_tasks", None)))


if __name__ == "__main__":
    unittest.main()
