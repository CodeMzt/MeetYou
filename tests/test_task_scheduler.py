import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

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
    async def test_recurring_task_parses_schedule_and_auto_run(self):
        manager = TaskManager(_FakeMemory())

        payload = json.loads(
            await manager.manage_tasks(
                action="create",
                summary="每天早上9点自动整理技术动态并提醒我阅读",
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )

        task = payload["tasks"][0]
        self.assertEqual(task["schedule_kind"], "recurring")
        self.assertTrue(task["auto_run"])
        self.assertEqual(task["notify_policy"], "on_completion")
        self.assertTrue(task["next_run_at"])

    async def test_once_task_is_claimed_once_and_marked_done_after_success(self):
        manager = TaskManager(_FakeMemory())
        due_at = (datetime.now(timezone.utc) - timedelta(minutes=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        created = json.loads(
            await manager.manage_tasks(
                action="create",
                summary="生成一次性日报",
                schedule_kind="once",
                due_at=due_at,
                auto_run=True,
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )
        task_key = created["tasks"][0]["task_key"]

        claimed = await manager.claim_due_tasks()
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["task_key"], task_key)

        await manager.complete_task_run(task_key, succeeded=True, summary="日报已生成", delivered=True)
        task = manager.get_task_by_key(task_key)
        self.assertIsNotNone(task)
        self.assertEqual(task["task_status"], "done")
        self.assertIsNone(task["next_run_at"])
        self.assertEqual(await manager.claim_due_tasks(), [])

    async def test_recurring_reminder_advances_and_pending_delivery_can_be_collected(self):
        manager = TaskManager(_FakeMemory())
        created = json.loads(
            await manager.manage_tasks(
                action="create",
                summary="每天早上9点提醒我查看技术动态",
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )
        task_key = created["tasks"][0]["task_key"]
        record = manager._find_task_by_key_any_user(task_key)
        record["next_run_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        claimed = await manager.claim_due_tasks()
        self.assertEqual(len(claimed), 1)

        await manager.complete_due_notification(
            task_key,
            summary="该查看技术动态了",
            delivered=False,
        )
        task = manager.get_task_by_key(task_key)
        self.assertEqual(task["last_run_status"], "pending_delivery")
        self.assertTrue(task["next_run_at"])

        pending = await manager.collect_pending_delivery_messages(source={"id": "desktop-user"})
        self.assertEqual(len(pending), 1)
        self.assertIn("该查看技术动态了", pending[0]["message"])
        self.assertEqual(await manager.collect_pending_delivery_messages(source={"id": "desktop-user"}), [])


    async def test_background_status_exposes_nearest_urgent_due_and_repeated_failures(self):
        manager = TaskManager(_FakeMemory())
        urgent_due = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        later_due = (datetime.now(timezone.utc) + timedelta(hours=12)).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        urgent_task = json.loads(
            await manager.manage_tasks(
                action="create",
                summary="urgent follow-up",
                schedule_kind="once",
                due_at=urgent_due,
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )["tasks"][0]
        later_task = json.loads(
            await manager.manage_tasks(
                action="create",
                summary="later follow-up",
                schedule_kind="once",
                due_at=later_due,
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )["tasks"][0]

        record = manager._find_task_by_key_any_user(urgent_task["task_key"])
        record["run_history"] = [
            {"status": "failed"},
            {"status": "failed"},
        ]
        record["last_run_status"] = "failed"
        record["last_run_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        record["last_run_summary"] = "failed twice"

        status = manager.build_background_status()

        self.assertEqual(status["nearest_due_task"]["task_key"], urgent_task["task_key"])
        self.assertEqual(status["urgent_due_task_count"], 1)
        self.assertEqual(status["urgent_due_tasks"][0]["task_key"], urgent_task["task_key"])
        self.assertEqual(status["repeated_failure_tasks"][0]["task_key"], urgent_task["task_key"])
        self.assertGreaterEqual(status["nearest_due_in_minutes"], 0)
        self.assertNotEqual(status["nearest_due_task"]["task_key"], later_task["task_key"])


if __name__ == "__main__":
    unittest.main()
