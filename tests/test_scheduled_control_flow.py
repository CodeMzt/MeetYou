import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import App
from core.io_protocol import EventTarget, EventType, InboundEvent, SourceKind, TargetKind, make_source


class _FakeConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key: str, default=None):
        return self._values.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self._values.get(key, default)
        if isinstance(value, bool):
            return value
        if value in (None, ""):
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}


class _FakeTaskManager:
    def __init__(self, record):
        self._record = copy.deepcopy(record)
        self.completed_due = None
        self.completed_run = None

    def get_task_by_key(self, task_key: str):
        if task_key != self._record.get("task_key"):
            return None
        return copy.deepcopy(self._record)

    async def complete_due_notification(self, task_key: str, *, summary: str, delivered: bool, now=None):
        del now
        self.completed_due = {
            "task_key": task_key,
            "summary": summary,
            "delivered": delivered,
        }
        return copy.deepcopy(self._record)

    async def complete_task_run(
        self,
        task_key: str,
        *,
        succeeded: bool,
        summary: str,
        next_retry_seconds=900,
        delivered: bool = True,
        now=None,
    ):
        del next_retry_seconds, now
        self.completed_run = {
            "task_key": task_key,
            "succeeded": succeeded,
            "summary": summary,
            "delivered": delivered,
        }
        return copy.deepcopy(self._record)


class _FakeBackgroundAgent:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.result)


class _FakeBrain:
    def __init__(self):
        self._http_session = object()


class _FakeToolsManager:
    def get_scheduled_job_tools(self):
        return [
            {"type": "function", "function": {"name": "manage_tasks"}},
            {"type": "function", "function": {"name": "compile_report"}},
        ]


class ScheduledControlFlowTests(unittest.IsolatedAsyncioTestCase):
    def _make_app(self, task_record: dict, background_result: dict):
        app = App.__new__(App)
        app.config = _FakeConfig(
            {
                "api_url": "https://api.example.test/v1/responses",
                "api_key": "test-key",
                "model": "gpt-5.4",
                "thinking_enabled": False,
            }
        )
        app.task_manager = _FakeTaskManager(task_record)
        app.background_agent = _FakeBackgroundAgent(background_result)
        app.brain = _FakeBrain()
        app.tools_manager = _FakeToolsManager()
        app.session_manager = None
        app.gateway = None
        app._runtime_source = make_source(SourceKind.SYSTEM.value, "runtime")
        return app

    async def test_scheduled_reminder_control_marks_notification_pending_when_not_delivered(self):
        task_record = {
            "task_key": "daily-review",
            "content": "Review the daily digest",
            "next_run_at": "2026-04-02T01:00:00Z",
            "due_at": "2026-04-02T01:00:00Z",
            "notify_policy": "on_due",
        }
        app = self._make_app(task_record, {"status": "ok", "content": "unused"})

        async def _emit_task_update(task_record, message):
            del task_record, message
            return False

        app._emit_task_update = _emit_task_update

        handled = await App._handle_control_event(
            app,
            InboundEvent(
                session_id="system:task:daily-review",
                type=EventType.CONTROL.value,
                role="system",
                content={"task_key": "daily-review"},
                source=make_source(SourceKind.SYSTEM.value, "scheduler"),
                target=EventTarget(kind=TargetKind.INTERNAL.value),
                metadata={"control_kind": "scheduled_reminder"},
            ),
        )

        self.assertTrue(handled)
        self.assertIsNotNone(app.task_manager.completed_due)
        self.assertFalse(app.task_manager.completed_due["delivered"])
        self.assertIn("Scheduled reminder:", app.task_manager.completed_due["summary"])

    async def test_scheduled_task_control_uses_allowlisted_tools_and_completes_task(self):
        task_record = {
            "task_key": "daily-news",
            "content": "Every day at 9 summarize AI news",
            "schedule_kind": "recurring",
            "next_run_at": "2026-04-02T01:00:00Z",
            "auto_run": True,
            "notify_policy": "on_completion",
            "delivery_target": {
                "kind": "current_session",
                "id": "",
                "session_id": "web:session-1",
                "source_kind": "web",
                "source_id": "browser-1",
            },
            "origin_session_id": "web:session-1",
            "scope": {"user_id": "user-1"},
        }
        app = self._make_app(task_record, {"status": "ok", "content": "Wrote the daily summary report."})

        delivered_messages = []

        async def _emit_task_update(task_record, message):
            delivered_messages.append({"task_key": task_record.get("task_key"), "message": message})
            return True

        app._emit_task_update = _emit_task_update

        handled = await App._handle_control_event(
            app,
            InboundEvent(
                session_id="system:task:daily-news",
                type=EventType.CONTROL.value,
                role="system",
                content={"task_key": "daily-news"},
                source=make_source(SourceKind.SYSTEM.value, "scheduler"),
                target=EventTarget(kind=TargetKind.INTERNAL.value),
                metadata={"control_kind": "scheduled_task"},
            ),
        )

        self.assertTrue(handled)
        self.assertEqual(len(app.background_agent.calls), 1)
        call = app.background_agent.calls[0]
        self.assertEqual(call["session_id"], "web:session-1")
        self.assertEqual(call["route_context"]["tool_bundle"], ["manage_tasks", "compile_report"])
        self.assertEqual(
            [tool["function"]["name"] for tool in call["tools"]],
            ["manage_tasks", "compile_report"],
        )
        self.assertNotIn("manage_schedule", call["route_context"]["tool_bundle"])
        self.assertIsNotNone(app.task_manager.completed_run)
        self.assertTrue(app.task_manager.completed_run["succeeded"])
        self.assertTrue(app.task_manager.completed_run["delivered"])
        self.assertIn("Scheduled task completed:", app.task_manager.completed_run["summary"])
        self.assertEqual(len(delivered_messages), 1)
        self.assertIn("Wrote the daily summary report.", delivered_messages[0]["message"])


if __name__ == "__main__":
    unittest.main()
