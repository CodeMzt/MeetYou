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
            "awaiting_completion_count": 0,
            "run_succeeded_pending_completion_count": 0,
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


class _HeartbeatProcessorConfig(_FakeConfig):
    def get(self, key: str):
        defaults = {
            "heartbeat_interval": 1,
            "housekeeping_interval": 60,
            "scheduler_interval": 15,
            "heartbeat_api_url": "https://example.com/v1/responses",
            "heartbeat_api_key": "test-key",
            "heart_model": "test-heart",
        }
        return defaults.get(key)


class _FakeHeartbeatRunner:
    def __init__(self, payloads, shutdown_event):
        self._payloads = list(payloads)
        self._shutdown_event = shutdown_event

    async def run(self, **kwargs):
        payload = self._payloads.pop(0)
        self._shutdown_event.set()
        return {"content": payload}


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
        self.assertIn("system", payload)
        self.assertIn("temporal", payload)
        self.assertIn("scheduler_stalled", payload["system"])
        self.assertIn("temporal_attention_candidates", payload["temporal"])
        self.assertIn("jobs", payload)
        self.assertIn("scheduler", payload["jobs"])
        self.assertIn("background_status_sources", payload)
        self.assertIn("heart.job_runtime", payload["background_status_sources"])

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

    async def test_legacy_urgent_deadline_maps_to_temporal_attention_but_is_silenced_without_candidates(self):
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
                "pending_delivery_count": 0,
                "awaiting_completion_count": 0,
                "run_succeeded_pending_completion_count": 0,
                "overdue_task_count": 0,
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

    async def test_temporal_attention_uses_pending_delivery_state(self):
        heart = self._make_heart()
        normalized = heart._normalize_heartbeat_result(
            {
                "decision": "notify",
                "signal_kind": "temporal_attention",
                "message": "这个提醒还没送达",
            },
            {
                "idle_poke_eligible": False,
                "pending_delivery_count": 1,
                "awaiting_completion_count": 0,
                "run_succeeded_pending_completion_count": 0,
                "overdue_task_count": 0,
                "last_user_activity_at": "2026-04-03T00:10:00Z",
                "repeated_failure_tasks": [],
                "scheduler_stalled": False,
                "housekeeping_stalled": False,
                "pending_consolidation_stale": False,
                "last_housekeeping_error": "",
                "delivery": {
                    "pending_redelivery_tasks": [
                        {
                            "task_key": "task-1",
                            "summary": "daily digest sync",
                        }
                    ]
                },
            },
        )

        self.assertEqual(normalized["decision"], "notify")
        self.assertEqual(normalized["signal_kind"], "temporal_attention")
        self.assertIn("daily digest sync", normalized["message"])
        self.assertIn("waiting to be delivered", normalized["message"])

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

    async def test_due_only_temporal_signal_is_ignored_without_temporal_anomaly(self):
        heart = self._make_heart()
        background_status = {
            "idle_poke_eligible": False,
            "urgent_due_task_count": 1,
            "pending_delivery_count": 0,
            "awaiting_completion_count": 0,
            "run_succeeded_pending_completion_count": 0,
            "overdue_task_count": 0,
            "last_user_activity_at": "2026-04-03T00:10:00Z",
            "nearest_due_task": {
                "task_key": "task-1",
                "summary": "daily digest sync",
                "due_at": "2026-04-03T00:30:00Z",
                "minutes_until_due": 29,
                "overdue": False,
            },
            "repeated_failure_tasks": [],
            "scheduler_stalled": False,
            "housekeeping_stalled": False,
            "pending_consolidation_stale": False,
            "last_housekeeping_error": "",
        }

        normalized = heart._normalize_heartbeat_result(
            {
                "decision": "notify",
                "signal_kind": "temporal_attention",
                "message": "这个任务快到期了",
            },
            background_status,
        )

        self.assertEqual(normalized["decision"], "ok")
        self.assertEqual(normalized["signal_kind"], "none")
        self.assertEqual(normalized["message"], "")

    async def test_temporal_attention_uses_awaiting_completion_state(self):
        heart = self._make_heart()
        normalized = heart._normalize_heartbeat_result(
            {
                "decision": "notify",
                "signal_kind": "temporal_attention",
                "message": "任务仍待完成确认",
            },
            {
                "idle_poke_eligible": False,
                "urgent_due_task_count": 0,
                "pending_delivery_count": 0,
                "awaiting_completion_count": 1,
                "run_succeeded_pending_completion_count": 1,
                "overdue_task_count": 0,
                "last_user_activity_at": "2026-04-03T00:10:00Z",
                "repeated_failure_tasks": [],
                "scheduler_stalled": False,
                "housekeeping_stalled": False,
                "pending_consolidation_stale": False,
                "last_housekeeping_error": "",
                "execution": {
                    "awaiting_completion_tasks": [
                        {
                            "task_key": "task-1",
                            "summary": "daily digest sync",
                            "auto_run": True,
                            "awaiting_completion": True,
                            "completion_state": "awaiting_completion",
                        }
                    ]
                },
            },
        )

        self.assertEqual(normalized["decision"], "notify")
        self.assertEqual(normalized["signal_kind"], "temporal_attention")
        self.assertIn("daily digest sync", normalized["message"])
        self.assertIn("completion confirmation", normalized["message"])

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

    async def test_pending_consolidation_stale_triggers_system_issue(self):
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

        self.assertEqual(normalized["decision"], "notify")
        self.assertEqual(normalized["signal_kind"], "system_issue")
        self.assertIn("Pending memory consolidation", normalized["message"])

    async def test_ok_cycle_keeps_last_signal_cooldown_state(self):
        task_manager = _FakeTaskManager(
            {
                "scheduled_task_count": 0,
                "due_task_count": 0,
                "overdue_task_count": 0,
                "pending_delivery_count": 0,
                "nearest_due_task": None,
                "nearest_due_in_minutes": None,
                "urgent_due_tasks": [],
                "urgent_due_task_count": 0,
                "repeated_failure_tasks": [{"task_key": "task-1"}],
                "recent_failures": [],
                "recent_runs": [],
            }
        )
        event_bus = _FakeEventBus()
        heart = Heart(
            adapter=object(),
            config=_HeartbeatProcessorConfig(),
            tools_manager=_FakeToolsManager(),
            memory=_FakeMemory(),
            task_manager=task_manager,
            event_bus=event_bus,
            exception_router=None,
        )
        heart._http_session = object()
        heart._last_heartbeat_signal_kind = "system_issue"
        heart._last_heartbeat_signal_message = (
            'Task "task-1" has failed repeatedly. Keep the follow-up brief and practical.'
        )
        heart._last_heartbeat_signal_fingerprint = "system_issue:repeated:task-1"
        heart._last_heartbeat_signal_at = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        heart._agent_runner = _FakeHeartbeatRunner(
            [
                '{"decision":"ok","signal_kind":"none","message":"","reasons":[],"confidence":"low"}',
            ],
            event_bus.shutdown_event,
        )
        manager = SessionManager()
        session_id = manager.get_or_create_session(make_source(SourceKind.WEB.value, "tab-a"), "web:1")
        binding = manager.get_binding(session_id)
        binding.metadata["last_active_at"] = time.time() - 120
        binding.default_target = EventTarget(kind="web", id="tab-a")
        heart.set_session_manager(manager)
        await heart.refresh_config()

        await heart.heartbeat_processor()

        self.assertEqual(heart._last_heartbeat_signal_kind, "system_issue")
        self.assertEqual(heart._last_heartbeat_signal_fingerprint, "system_issue:repeated:task-1")


if __name__ == "__main__":
    unittest.main()
