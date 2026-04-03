import asyncio
import os
import sys
import time
import unittest
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.heart import Heart
from core.io_protocol import EventTarget, SourceKind, make_source
from core.session_manager import SessionManager


class _FakeMemory:
    def __init__(self):
        self._store = {"records": []}

    def set_housekeeping_adapter(self, adapter):
        self.adapter = adapter

    async def run_housekeeping(self, *args, **kwargs):
        return None


class _FakeTaskManager:
    def __init__(self, payload=None):
        self.payload = payload or {
            "scheduled_task_count": 0,
            "due_task_count": 0,
            "overdue_task_count": 0,
            "pending_delivery_count": 0,
            "nearest_due_task": None,
            "nearest_due_in_minutes": None,
            "urgent_due_tasks": [],
            "urgent_due_task_count": 0,
            "repeated_failure_tasks": [],
            "recent_failures": [],
            "recent_runs": [],
        }

    async def backfill_scheduled_tasks(self):
        return 0

    def build_background_status(self):
        return dict(self.payload)


class _FakeToolsManager:
    tools_schema_dict = {"background_tools": []}

    def get_heartbeat_tools(self):
        return []


class _FakeEventBus:
    def __init__(self):
        self.inbound_queue = asyncio.Queue()
        self.shutdown_event = asyncio.Event()


class _FakeConfig:
    def get(self, key: str):
        defaults = {
            "heartbeat_interval": 180,
            "housekeeping_interval": 60,
            "scheduler_interval": 15,
            "heartbeat_api_url": "",
            "heartbeat_api_key": "",
            "heart_model": "",
        }
        return defaults.get(key)

    def get_prompt(self, name: str):
        return f"prompt:{name}"


class HeartbeatGuardrailTests(unittest.IsolatedAsyncioTestCase):
    def _make_heart(self, payload=None):
        return Heart(
            adapter=object(),
            config=_FakeConfig(),
            tools_manager=_FakeToolsManager(),
            memory=_FakeMemory(),
            task_manager=_FakeTaskManager(payload),
            event_bus=_FakeEventBus(),
            exception_router=None,
        )

    async def test_background_status_marks_idle_poke_eligibility(self):
        heart = self._make_heart()
        manager = SessionManager()
        session_id = manager.get_or_create_session(make_source(SourceKind.WEB.value, "tab-a"), "web:1")
        binding = manager.get_binding(session_id)
        binding.metadata["last_active_at"] = time.time() - 3700
        binding.default_target = EventTarget(kind="web", id="tab-a")
        heart.set_session_manager(manager)

        payload = await heart.get_background_status()

        self.assertNotEqual(payload["last_user_activity_at"], "")
        self.assertTrue(payload["idle_poke_eligible"])
        self.assertEqual(payload["last_idle_poke_at"], "")

    async def test_idle_poke_is_silenced_when_not_eligible(self):
        heart = self._make_heart()
        normalized = heart._normalize_heartbeat_result(
            {
                "decision": "notify",
                "signal_kind": "idle_poke",
                "message": "Are you still there?",
            },
            {
                "idle_poke_eligible": False,
                "urgent_due_task_count": 0,
                "last_user_activity_at": "2026-04-03T00:00:00Z",
                "repeated_failure_tasks": [],
                "scheduler_stalled": False,
                "housekeeping_stalled": False,
                "pending_consolidation_stale": False,
                "last_housekeeping_error": "",
            },
        )

        self.assertEqual(normalized["decision"], "ok")
        self.assertEqual(normalized["signal_kind"], "none")
        self.assertEqual(normalized["message"], "")

    async def test_urgent_deadline_is_silenced_without_urgent_due_tasks(self):
        heart = self._make_heart()
        normalized = heart._normalize_heartbeat_result(
            {
                "decision": "notify",
                "signal_kind": "urgent_deadline",
                "message": "A task is about to be due.",
            },
            {
                "idle_poke_eligible": False,
                "urgent_due_task_count": 0,
                "last_user_activity_at": "2026-04-03T00:00:00Z",
                "repeated_failure_tasks": [],
                "scheduler_stalled": False,
                "housekeeping_stalled": False,
                "pending_consolidation_stale": False,
                "last_housekeeping_error": "",
            },
        )

        self.assertEqual(normalized["decision"], "ok")
        self.assertEqual(normalized["signal_kind"], "none")

    async def test_identical_canonical_message_is_silenced_in_cooldown(self):
        heart = self._make_heart()
        heart._last_heartbeat_signal_kind = "system_issue"
        heart._last_heartbeat_signal_message = (
            'Task "task-1" has failed repeatedly. Keep the follow-up brief and practical.'
        )
        heart._last_heartbeat_signal_at = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )

        normalized = heart._normalize_heartbeat_result(
            {
                "decision": "notify",
                "signal_kind": "system_issue",
                "message": "task failed again",
            },
            {
                "idle_poke_eligible": False,
                "urgent_due_task_count": 0,
                "last_user_activity_at": "2026-04-03T00:10:00Z",
                "repeated_failure_tasks": [{"task_key": "task-1"}],
                "scheduler_stalled": False,
                "housekeeping_stalled": False,
                "pending_consolidation_stale": False,
                "last_housekeeping_error": "",
            },
        )

        self.assertEqual(normalized["decision"], "ok")
        self.assertEqual(normalized["signal_kind"], "none")
        self.assertEqual(normalized["message"], "")

    async def test_hallucinated_system_issue_message_is_replaced_with_structured_note(self):
        heart = self._make_heart()
        normalized = heart._normalize_heartbeat_result(
            {
                "decision": "notify",
                "signal_kind": "system_issue",
                "message": "Galaxy Chromebook needs attention.",
            },
            {
                "idle_poke_eligible": False,
                "urgent_due_task_count": 0,
                "last_user_activity_at": "2026-04-03T00:10:00Z",
                "repeated_failure_tasks": [
                    {
                        "task_key": "task-1",
                        "summary": "daily digest sync",
                    }
                ],
                "scheduler_stalled": False,
                "housekeeping_stalled": False,
                "pending_consolidation_stale": False,
                "last_housekeeping_error": "",
            },
        )

        self.assertEqual(normalized["decision"], "notify")
        self.assertEqual(normalized["signal_kind"], "system_issue")
        self.assertIn("daily digest sync", normalized["message"])
        self.assertNotIn("Galaxy Chromebook", normalized["message"])

    async def test_pending_consolidation_only_does_not_trigger_system_issue(self):
        heart = self._make_heart()
        normalized = heart._normalize_heartbeat_result(
            {
                "decision": "notify",
                "signal_kind": "system_issue",
                "message": "background backlog is stale",
            },
            {
                "idle_poke_eligible": False,
                "urgent_due_task_count": 0,
                "last_user_activity_at": "2026-04-03T00:10:00Z",
                "repeated_failure_tasks": [],
                "scheduler_stalled": False,
                "housekeeping_stalled": False,
                "pending_consolidation_stale": True,
                "last_housekeeping_error": "",
            },
        )

        self.assertEqual(normalized["decision"], "ok")
        self.assertEqual(normalized["signal_kind"], "none")
        self.assertEqual(normalized["message"], "")


if __name__ == "__main__":
    unittest.main()
