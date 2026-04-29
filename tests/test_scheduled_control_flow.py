import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import App
from core.io_protocol import EventTarget, EventType, InboundEvent, SourceKind, TargetKind, make_source


class _FakeTaskManager:
    def __init__(self):
        self.checked_claims = []
        self.completed_due = None
        self.completed_run = None

    def has_current_claim(self, task_key: str, claim_token: str, *, now=None):
        del now
        self.checked_claims.append((task_key, claim_token))
        return False

    async def complete_due_notification(self, *args, **kwargs):
        self.completed_due = {"args": args, "kwargs": kwargs}

    async def complete_task_run(self, *args, **kwargs):
        self.completed_run = {"args": args, "kwargs": kwargs}


class _FakeBrain:
    def __init__(self):
        self.calls = []

    async def run_background_turn(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "ok", "content": "should not run"}


class _FakeOperationService:
    def __init__(self):
        self.rows = []

    def create_operation(self, **kwargs):
        self.rows.append(dict(kwargs))
        return kwargs


class ScheduledControlFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_scheduled_control_event_is_consumed_without_taskmanager_execution(self):
        app = App.__new__(App)
        app.task_manager = _FakeTaskManager()
        app.brain = _FakeBrain()
        app.core_services = type("CoreServices", (), {"operation": _FakeOperationService()})()

        handled = await App._handle_control_event(
            app,
            InboundEvent(
                session_id="system:task:daily-review",
                type=EventType.CONTROL.value,
                role="system",
                content={"task_key": "daily-review", "claim_token": "claim-1"},
                source=make_source(SourceKind.SYSTEM.value, "scheduler"),
                target=EventTarget(kind=TargetKind.INTERNAL.value),
                metadata={"control_kind": "scheduled_task"},
            ),
        )

        self.assertTrue(handled)
        self.assertEqual(app.task_manager.checked_claims, [])
        self.assertIsNone(app.task_manager.completed_due)
        self.assertIsNone(app.task_manager.completed_run)
        self.assertEqual(app.brain.calls, [])
        self.assertEqual(app.core_services.operation.rows, [])

    async def test_legacy_scheduled_reminder_event_is_consumed_without_taskmanager_execution(self):
        app = App.__new__(App)
        app.task_manager = _FakeTaskManager()
        app.brain = _FakeBrain()
        app.core_services = type("CoreServices", (), {"operation": _FakeOperationService()})()

        handled = await App._handle_control_event(
            app,
            InboundEvent(
                session_id="system:task:daily-review",
                type=EventType.CONTROL.value,
                role="system",
                content={"task_key": "daily-review", "claim_token": "claim-1"},
                source=make_source(SourceKind.SYSTEM.value, "scheduler"),
                target=EventTarget(kind=TargetKind.INTERNAL.value),
                metadata={"control_kind": "scheduled_reminder"},
            ),
        )

        self.assertTrue(handled)
        self.assertEqual(app.task_manager.checked_claims, [])
        self.assertIsNone(app.task_manager.completed_due)
        self.assertIsNone(app.task_manager.completed_run)
        self.assertEqual(app.brain.calls, [])
        self.assertEqual(app.core_services.operation.rows, [])


if __name__ == "__main__":
    unittest.main()
