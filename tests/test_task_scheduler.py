import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.task_manager import TaskManager


class _FakeMemory:
    def __init__(self, memory_file_path: str = ""):
        self._embedding_model = "fake-embedding"
        self._memory_file_path = memory_file_path
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
        if self._memory_file_path:
            with open(self._memory_file_path, "w", encoding="utf-8") as handle:
                json.dump(self._store, handle, ensure_ascii=False, indent=2)


class TaskSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_recurring_task_parses_schedule_and_auto_run(self):
        manager = TaskManager(_FakeMemory())

        payload = json.loads(
            await manager.manage_scheduled_tasks(
                action="create",
                summary="每天早上9点自动整理技术动态并提醒我阅读",
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )

        task = payload["tasks"][0]
        self.assertEqual(task["task_domain"], "assistant_schedule")
        self.assertEqual(task["schedule_kind"], "recurring")
        self.assertTrue(task["auto_run"])
        self.assertEqual(task["notify_policy"], "on_completion")
        self.assertEqual(task["recurrence"]["freq"], "daily")
        self.assertTrue(task["next_run_at"])

    async def test_weekly_recurrence_object_requires_explicit_trigger_hour(self):
        manager = TaskManager(_FakeMemory())

        created = json.loads(
            await manager.manage_scheduled_tasks(
                action="create",
                summary="每周例行检查",
                schedule_kind="recurring",
                recurrence={"freq": "weekly", "weekday": "monday", "hour": 9, "minute": 30},
                timezone="UTC",
                source={"id": "desktop-user"},
            )
        )

        task = created["tasks"][0]
        self.assertEqual(task["schedule_kind"], "recurring")
        self.assertEqual(task["recurrence"], {"freq": "weekly", "weekday": 0, "hour": 9, "minute": 30})

        failed = await manager.manage_scheduled_tasks(
            action="create",
            summary="每周但没写时间",
            schedule_kind="recurring",
            recurrence={"freq": "weekly", "weekday": "monday"},
            timezone="UTC",
            source={"id": "desktop-user"},
        )
        self.assertIn("weekly recurrence hour is required", failed)

    async def test_manage_tasks_rejects_schedule_fields_for_user_todo(self):
        manager = TaskManager(_FakeMemory())
        failed = await manager.manage_tasks(
            action="create",
            summary="明天早上九点提醒我",
            schedule_kind="once",
            due_at="2026-04-05T01:00:00Z",
            source={"id": "desktop-user"},
        )
        self.assertIn("manage_tasks only manages user TODO items", failed)

    async def test_user_todo_with_time_language_is_not_claimed_by_scheduler(self):
        manager = TaskManager(_FakeMemory())
        created = json.loads(
            await manager.manage_tasks(
                action="create",
                summary="明天早上九点前完成周报",
                source={"id": "desktop-user"},
            )
        )
        task = created["tasks"][0]
        self.assertEqual(task["task_domain"], "user_todo")
        self.assertEqual(task["schedule_kind"], "none")
        self.assertEqual(await manager.claim_due_tasks(), [])

    async def test_once_task_run_success_requires_explicit_complete_to_finish(self):
        manager = TaskManager(_FakeMemory())
        due_at = (datetime.now(timezone.utc) - timedelta(minutes=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        created = json.loads(
            await manager.manage_scheduled_tasks(
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
        self.assertEqual(task["task_status"], "open")
        self.assertEqual(task["completion_state"], "awaiting_completion")
        self.assertEqual(task["orchestration"]["execution_status"], "succeeded")
        self.assertEqual(task["orchestration"]["completion_status"], "awaiting_completion")
        self.assertEqual(task["next_run_at"], due_at)
        self.assertEqual(await manager.claim_due_tasks(), [])

        completed = json.loads(
            await manager.manage_scheduled_tasks(
                action="complete",
                task_key=task_key,
                completion_summary="日报已生成并归档",
                source={"id": "desktop-user"},
            )
        )["tasks"][0]
        self.assertEqual(completed["task_status"], "done")
        self.assertIsNone(completed["next_run_at"])
        self.assertEqual(completed["last_completion_summary"], "日报已生成并归档")

    async def test_failed_auto_run_can_retry_after_failure_backoff(self):
        manager = TaskManager(_FakeMemory())
        now = datetime(2026, 4, 2, 10, 0, tzinfo=timezone.utc)
        due_at = (now - timedelta(minutes=5)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        created = json.loads(
            await manager.manage_scheduled_tasks(
                action="create",
                summary="生成一次性周报",
                schedule_kind="once",
                due_at=due_at,
                auto_run=True,
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )
        task_key = created["tasks"][0]["task_key"]

        first_claim = await manager.claim_due_tasks(now=now)
        self.assertEqual(len(first_claim), 1)

        await manager.complete_task_run(
            task_key,
            succeeded=False,
            summary="周报生成失败，需要稍后重试",
            delivered=True,
            next_retry_seconds=60,
            now=now + timedelta(seconds=1),
        )

        task = manager.get_task_by_key(task_key)
        self.assertEqual(task["last_run_status"], "failed")
        self.assertEqual(task["completion_state"], "awaiting_retry")
        self.assertEqual(task["orchestration"]["execution_status"], "failed")
        self.assertEqual(await manager.claim_due_tasks(now=now + timedelta(seconds=30)), [])

        retry_claim = await manager.claim_due_tasks(now=now + timedelta(seconds=62))
        self.assertEqual(len(retry_claim), 1)
        self.assertEqual(retry_claim[0]["task_key"], task_key)

    async def test_once_task_is_not_reclaimed_after_lease_expires_before_completion(self):
        manager = TaskManager(_FakeMemory())
        claim_time = datetime(2026, 4, 2, 10, 0, tzinfo=timezone.utc)
        due_at = (claim_time - timedelta(minutes=5)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        created = json.loads(
            await manager.manage_scheduled_tasks(
                action="create",
                summary="一次性复盘提醒",
                schedule_kind="once",
                due_at=due_at,
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )
        task_key = created["tasks"][0]["task_key"]

        claimed = await manager.claim_due_tasks(now=claim_time)
        self.assertEqual(len(claimed), 1)
        self.assertTrue(claimed[0]["active_claim_token"])

        task = manager.get_task_by_key(task_key)
        self.assertEqual(task["last_triggered_at"], "2026-04-02T10:00:00Z")
        self.assertEqual(await manager.claim_due_tasks(now=claim_time + timedelta(minutes=3)), [])

    async def test_recurring_reminder_marks_cycle_awaiting_completion_and_pending_delivery_can_be_collected(self):
        manager = TaskManager(_FakeMemory())
        created = json.loads(
            await manager.manage_scheduled_tasks(
                action="create",
                summary="提醒我查看技术动态",
                schedule_kind="recurring",
                recurrence={"freq": "daily", "hour": 9, "minute": 0},
                timezone="UTC",
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )
        task_key = created["tasks"][0]["task_key"]
        record = manager._find_task_by_key_any_user(task_key)
        record["schedule_anchor_at"] = "2026-04-01T08:00:00Z"
        claim_time = datetime(2026, 4, 2, 9, 30, tzinfo=timezone.utc)

        claimed = await manager.claim_due_tasks(now=claim_time)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["next_run_at"], "2026-04-02T09:00:00Z")

        await manager.complete_due_notification(
            task_key,
            summary="该查看技术动态了",
            delivered=False,
            now=claim_time,
        )
        task = manager.get_task_by_key(task_key)
        state = manager._schedule_state(record, now=claim_time + timedelta(minutes=1))
        self.assertEqual(task["last_run_status"], "pending_delivery")
        self.assertEqual(task["next_run_at"], "2026-04-02T09:00:00Z")
        self.assertTrue(state["awaiting_completion"])
        self.assertEqual(task["orchestration"]["delivery_status"], "pending_redelivery")

        pending = await manager.collect_pending_delivery_messages(source={"id": "desktop-user"})
        self.assertEqual(len(pending), 1)
        self.assertIn("该查看技术动态了", pending[0]["message"])
        self.assertEqual(pending[0]["kind"], "task_due")
        self.assertTrue(pending[0]["event_id"])
        self.assertEqual(pending[0]["source_event_id"], pending[0]["event_id"])
        self.assertTrue(pending[0]["cycle_key"])
        self.assertEqual(await manager.collect_pending_delivery_messages(source={"id": "desktop-user"}), [])

    async def test_overdue_recurring_task_is_caught_up_and_current_cycle_is_not_duplicated(self):
        manager = TaskManager(_FakeMemory())
        created = json.loads(
            await manager.manage_scheduled_tasks(
                action="create",
                summary="每日站会提醒",
                schedule_kind="recurring",
                recurrence={"freq": "daily", "hour": 9, "minute": 0},
                timezone="UTC",
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )
        task_key = created["tasks"][0]["task_key"]
        record = manager._find_task_by_key_any_user(task_key)
        record["schedule_anchor_at"] = "2026-04-01T08:00:00Z"

        claim_time = datetime(2026, 4, 2, 10, 0, tzinfo=timezone.utc)
        first_claim = await manager.claim_due_tasks(now=claim_time)
        self.assertEqual(len(first_claim), 1)
        self.assertEqual(first_claim[0]["next_run_at"], "2026-04-02T09:00:00Z")

        self.assertEqual(await manager.claim_due_tasks(now=claim_time + timedelta(minutes=1)), [])

        await manager.complete_due_notification(
            task_key,
            summary="今天的站会到了",
            delivered=True,
            now=claim_time + timedelta(minutes=2),
        )
        self.assertEqual(await manager.claim_due_tasks(now=claim_time + timedelta(minutes=3)), [])

        state = manager._schedule_state(record, now=claim_time + timedelta(minutes=3))
        self.assertEqual(state["completion_state"], "awaiting_completion")

        next_cycle_claim = await manager.claim_due_tasks(now=datetime(2026, 4, 3, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(len(next_cycle_claim), 1)
        self.assertEqual(next_cycle_claim[0]["next_run_at"], "2026-04-03T09:00:00Z")

    async def test_recurring_task_is_not_reclaimed_after_lease_expires_within_same_cycle(self):
        manager = TaskManager(_FakeMemory())
        created = json.loads(
            await manager.manage_scheduled_tasks(
                action="create",
                summary="每日上午九点发送运营提醒",
                schedule_kind="recurring",
                recurrence={"freq": "daily", "hour": 9, "minute": 0},
                timezone="UTC",
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )
        task_key = created["tasks"][0]["task_key"]
        record = manager._find_task_by_key_any_user(task_key)
        record["schedule_anchor_at"] = "2026-04-01T08:00:00Z"
        claim_time = datetime(2026, 4, 2, 10, 0, tzinfo=timezone.utc)

        first_claim = await manager.claim_due_tasks(now=claim_time)
        self.assertEqual(len(first_claim), 1)
        self.assertTrue(first_claim[0]["active_claim_token"])
        self.assertEqual(await manager.claim_due_tasks(now=claim_time + timedelta(minutes=3)), [])

    async def test_complete_action_for_recurring_task_advances_to_next_cycle(self):
        manager = TaskManager(_FakeMemory())
        created = json.loads(
            await manager.manage_scheduled_tasks(
                action="create",
                summary="每周例会复盘",
                schedule_kind="recurring",
                recurrence={"freq": "weekly", "weekday": "friday", "hour": 9, "minute": 0},
                timezone="UTC",
                source={"id": "desktop-user"},
            )
        )
        task_key = created["tasks"][0]["task_key"]
        record = manager._find_task_by_key_any_user(task_key)
        record["schedule_anchor_at"] = "2026-04-03T08:00:00Z"

        completed = json.loads(
            await manager.manage_scheduled_tasks(
                action="complete",
                task_key=task_key,
                source={"id": "desktop-user"},
            )
        )

        task = completed["tasks"][0]
        self.assertEqual(task["task_status"], "open")
        self.assertTrue(task["last_completed_at"])
        self.assertTrue(task["next_run_at"] > task["last_completed_at"])
        self.assertEqual(task["completion_state"], "completed_for_cycle")

    async def test_restart_can_recover_missed_recurring_cycle(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            memory_path = Path(tmp_dir) / "memory_graph.json"
            memory_path.write_text(
                json.dumps(
                    {
                        "metadata": {"updated_at": "2026-04-02T10:00:00Z"},
                        "records": [],
                        "edges": [],
                        "working_summaries": {"global": "", "by_session": {}},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            memory = _FakeMemory(str(memory_path))
            manager = TaskManager(memory)
            created = json.loads(
                await manager.manage_scheduled_tasks(
                    action="create",
                    summary="每日巡检",
                    schedule_kind="recurring",
                    recurrence={"freq": "daily", "hour": 9, "minute": 0},
                    timezone="UTC",
                    source={"id": "desktop-user"},
                )
            )
            task_key = created["tasks"][0]["task_key"]
            record = manager._find_task_by_key_any_user(task_key)
            record["schedule_anchor_at"] = "2026-04-01T08:00:00Z"
            await manager._persist()

            restarted = TaskManager(_FakeMemory(str(memory_path)))
            claimed = await restarted.claim_due_tasks(now=datetime(2026, 4, 2, 10, 0, tzinfo=timezone.utc))

            self.assertEqual(len(claimed), 1)
            self.assertEqual(claimed[0]["task_key"], task_key)
            self.assertEqual(claimed[0]["next_run_at"], "2026-04-02T09:00:00Z")


    async def test_background_status_exposes_nearest_urgent_due_and_repeated_failures(self):
        manager = TaskManager(_FakeMemory())
        urgent_due = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        later_due = (datetime.now(timezone.utc) + timedelta(hours=12)).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        urgent_task = json.loads(
            await manager.manage_scheduled_tasks(
                action="create",
                summary="urgent follow-up",
                schedule_kind="once",
                due_at=urgent_due,
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )["tasks"][0]
        later_task = json.loads(
            await manager.manage_scheduled_tasks(
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

        self.assertIn("schedule", status)
        self.assertIn("execution", status)
        self.assertIn("delivery", status)
        self.assertEqual(status["schedule"]["nearest_due_task"]["task_key"], urgent_task["task_key"])
        self.assertEqual(status["execution"]["repeated_failure_tasks"][0]["task_key"], urgent_task["task_key"])
        self.assertEqual(status["nearest_due_task"]["task_key"], urgent_task["task_key"])
        self.assertEqual(status["urgent_due_task_count"], 1)
        self.assertEqual(status["urgent_due_tasks"][0]["task_key"], urgent_task["task_key"])
        self.assertEqual(status["repeated_failure_tasks"][0]["task_key"], urgent_task["task_key"])
        self.assertGreaterEqual(status["nearest_due_in_minutes"], 0)
        self.assertNotEqual(status["nearest_due_task"]["task_key"], later_task["task_key"])

    async def test_background_status_counts_run_succeeded_but_not_completed(self):
        manager = TaskManager(_FakeMemory())
        now = datetime.now(timezone.utc).replace(microsecond=0)
        due_at = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        created = json.loads(
            await manager.manage_scheduled_tasks(
                action="create",
                summary="生成一次性看板",
                schedule_kind="once",
                due_at=due_at,
                auto_run=True,
                source={"id": "desktop-user"},
            )
        )
        task_key = created["tasks"][0]["task_key"]

        await manager.claim_due_tasks(now=now)
        await manager.complete_task_run(
            task_key,
            succeeded=True,
            summary="看板已更新，但仍等待明确完成确认",
            delivered=True,
            now=now + timedelta(seconds=1),
        )

        task = manager.get_task_by_key(task_key)
        self.assertEqual(task["completion_state"], "awaiting_completion")
        status = manager.build_background_status()
        self.assertEqual(status["execution"]["awaiting_completion_count"], 1)
        self.assertEqual(status["execution"]["run_succeeded_pending_completion_count"], 1)
        self.assertEqual(status["awaiting_completion_count"], 1)
        self.assertEqual(status["run_succeeded_pending_completion_count"], 1)

    async def test_background_status_excludes_auto_run_and_awaiting_completion_from_urgent_due(self):
        manager = TaskManager(_FakeMemory())
        now = datetime.now(timezone.utc).replace(microsecond=0)
        auto_run_due_at = (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        reminder_due_at = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        auto_run_task = json.loads(
            await manager.manage_scheduled_tasks(
                action="create",
                summary="定时生成日报",
                schedule_kind="once",
                due_at=auto_run_due_at,
                auto_run=True,
                source={"id": "desktop-user"},
            )
        )["tasks"][0]
        reminder_task = json.loads(
            await manager.manage_scheduled_tasks(
                action="create",
                summary="提醒我同步日报",
                schedule_kind="once",
                due_at=reminder_due_at,
                source={"id": "desktop-user"},
                session_id="web:session:1",
            )
        )["tasks"][0]

        await manager.claim_due_tasks(now=now)
        await manager.complete_due_notification(
            reminder_task["task_key"],
            summary="该同步日报了",
            delivered=True,
            now=now + timedelta(seconds=1),
        )

        status = manager.build_background_status()

        self.assertEqual(status["urgent_due_task_count"], 0)
        self.assertIsNone(status["nearest_due_task"])
        self.assertEqual(status["awaiting_completion_count"], 1)
        self.assertEqual(manager.get_task_by_key(auto_run_task["task_key"])["auto_run"], True)

    async def test_sync_legacy_memory_tasks_reads_disk_legacy_records_and_rebinds_task_store(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            memory_path = Path(tmp_dir) / "memory_graph.json"
            task_path = Path(tmp_dir) / "memory_tasks.json"
            legacy_task = {
                "id": "task_legacy_follow_up",
                "type": "task",
                "scope": {"user_id": "desktop-user", "session_id": ""},
                "content": "legacy follow-up",
                "canonical_text": "legacy follow-up",
                "embedding": [16.0, 1.0],
                "embedding_model": "fake-embedding",
                "strength": 0.72,
                "importance": 0.7,
                "confidence": 1.0,
                "created_at": "2026-04-04T03:16:31Z",
                "last_accessed_at": "2026-04-04T03:16:31Z",
                "last_updated_at": "2026-04-04T03:16:31Z",
                "access_count": 0,
                "status": "active",
                "tags": [],
                "entity_keys": [],
                "source_record_ids": [],
                "task_key": "legacy-follow-up",
                "project": "",
                "task_status": "open",
                "deadline": None,
            }
            fact_record = {
                "id": "fact_payment_callback",
                "type": "fact",
                "scope": {"user_id": "desktop-user", "session_id": ""},
                "content": "payment callback still needs retry handling",
                "canonical_text": "payment callback still needs retry handling",
                "embedding": [1.0, 2.0],
                "embedding_model": "fake-embedding",
                "strength": 0.8,
                "importance": 0.7,
                "confidence": 0.9,
                "created_at": "2026-04-04T03:16:31Z",
                "last_accessed_at": "2026-04-04T03:16:31Z",
                "last_updated_at": "2026-04-04T03:16:31Z",
                "access_count": 0,
                "status": "active",
                "tags": [],
                "entity_keys": [],
                "source_record_ids": [],
            }
            memory_path.write_text(
                json.dumps(
                    {
                        "metadata": {"updated_at": "2026-04-04T03:16:31Z"},
                        "records": [legacy_task, fact_record],
                        "edges": [{"from_id": legacy_task["id"], "to_id": fact_record["id"], "derived_from": True}],
                        "working_summaries": {"global": "", "by_session": {}},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            memory = _FakeMemory()
            manager = TaskManager(memory)
            memory._memory_file_path = str(memory_path)
            memory._store = {
                "records": [fact_record.copy()],
                "edges": [],
                "metadata": {"updated_at": "2026-04-04T03:16:31Z"},
                "working_summaries": {"global": "", "by_session": {}},
            }

            migrated = await manager.sync_legacy_memory_tasks()

            self.assertEqual(migrated, 1)
            self.assertEqual(manager.get_task_by_key("legacy-follow-up")["content"], "legacy follow-up")
            self.assertTrue(task_path.exists())
            self.assertEqual(json.loads(task_path.read_text(encoding="utf-8"))["tasks"][0]["task_key"], "legacy-follow-up")

            cleaned_graph = json.loads(memory_path.read_text(encoding="utf-8"))
            self.assertEqual([record["type"] for record in cleaned_graph["records"]], ["fact"])
            self.assertEqual(cleaned_graph["edges"], [])
            self.assertEqual(memory.saved, 1)

    async def test_sync_legacy_memory_tasks_cleans_duplicate_disk_records_without_reimporting(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            memory_path = Path(tmp_dir) / "memory_graph.json"
            task_path = Path(tmp_dir) / "memory_tasks.json"
            task_record = {
                "id": "task_legacy_follow_up",
                "type": "task",
                "scope": {"user_id": "desktop-user", "session_id": ""},
                "content": "legacy follow-up",
                "canonical_text": "legacy follow-up",
                "embedding": [16.0, 1.0],
                "embedding_model": "fake-embedding",
                "strength": 0.72,
                "importance": 0.7,
                "confidence": 1.0,
                "created_at": "2026-04-04T03:16:31Z",
                "last_accessed_at": "2026-04-04T03:16:31Z",
                "last_updated_at": "2026-04-04T03:16:31Z",
                "access_count": 0,
                "status": "active",
                "tags": [],
                "entity_keys": [],
                "source_record_ids": [],
                "task_key": "legacy-follow-up",
                "project": "",
                "task_status": "open",
                "deadline": None,
            }
            memory_path.write_text(
                json.dumps(
                    {
                        "metadata": {"updated_at": "2026-04-04T03:16:31Z"},
                        "records": [task_record],
                        "edges": [],
                        "working_summaries": {"global": "", "by_session": {}},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            task_path.write_text(
                json.dumps(
                    {
                        "metadata": {"updated_at": "2026-04-04T03:16:31Z"},
                        "tasks": [task_record],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            memory = _FakeMemory(str(memory_path))
            memory._store = {
                "records": [],
                "edges": [],
                "metadata": {"updated_at": "2026-04-04T03:16:31Z"},
                "working_summaries": {"global": "", "by_session": {}},
            }
            manager = TaskManager(memory)

            migrated = await manager.sync_legacy_memory_tasks()

            self.assertEqual(migrated, 0)
            self.assertEqual(len(json.loads(task_path.read_text(encoding="utf-8"))["tasks"]), 1)
            self.assertEqual(json.loads(memory_path.read_text(encoding="utf-8"))["records"], [])
            self.assertEqual(memory.saved, 1)


if __name__ == "__main__":
    unittest.main()
