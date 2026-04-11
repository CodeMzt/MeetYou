import copy
import json
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
        self.checked_claims = []
        self.remembered_operations = []

    def get_task_by_key(self, task_key: str):
        if task_key != self._record.get("task_key"):
            return None
        return copy.deepcopy(self._record)

    def has_current_claim(self, task_key: str, claim_token: str, *, now=None):
        del now
        self.checked_claims.append((task_key, claim_token))
        expected = str(self._record.get("active_claim_token") or "").strip()
        if not claim_token:
            return True
        return task_key == self._record.get("task_key") and expected == claim_token

    async def complete_due_notification(
        self,
        task_key: str,
        *,
        summary: str,
        delivered: bool,
        runtime_source="",
        delivery_channel="task_update",
        delivery_details=None,
        now=None,
    ):
        del delivery_details, now
        self.completed_due = {
            "task_key": task_key,
            "summary": summary,
            "delivered": delivered,
            "runtime_source": runtime_source,
            "delivery_channel": delivery_channel,
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
        completed: bool = False,
        failure_category="",
        failure_retryable=None,
        failure_code="",
        failure_details=None,
        runtime_source="",
        delivery_channel="task_update",
        delivery_details=None,
        now=None,
    ):
        del next_retry_seconds, failure_details, delivery_details, now
        self.completed_run = {
            "task_key": task_key,
            "succeeded": succeeded,
            "summary": summary,
            "delivered": delivered,
            "completed": completed,
            "failure_category": failure_category,
            "failure_retryable": failure_retryable,
            "failure_code": failure_code,
            "runtime_source": runtime_source,
            "delivery_channel": delivery_channel,
        }
        return copy.deepcopy(self._record)

    async def remember_task_operation(self, task_key: str, *, operation_id: str, status: str, now=None):
        del now
        self.remembered_operations.append({"task_key": task_key, "operation_id": operation_id, "status": status})
        self._record["last_operation_id"] = operation_id
        self._record["last_operation_status"] = status
        return copy.deepcopy(self._record)


class _FakeOperationRow:
    def __init__(self, operation_id: str, operation_type: str, execution_target: str, title: str, metadata: dict):
        self.id = operation_id
        self.operation_id = operation_id
        self.operation_type = operation_type
        self.execution_target = execution_target
        self.title = title
        self.status = "running"
        self.meta = dict(metadata)


class _FakeOperationService:
    def __init__(self):
        self.rows = []

    def create_operation(self, **kwargs):
        row = _FakeOperationRow(
            operation_id=f"op-test-{len(self.rows) + 1}",
            operation_type=kwargs.get("operation_type", ""),
            execution_target=kwargs.get("execution_target", ""),
            title=kwargs.get("title", ""),
            metadata=kwargs.get("metadata") or {},
        )
        self.rows.append(row)
        return row

    def update_status(self, *, operation_id, status: str, result_summary: str | None = None, metadata: dict | None = None):
        for row in self.rows:
            if row.id == operation_id or row.operation_id == operation_id:
                row.status = status
                if metadata:
                    merged = dict(row.meta)
                    merged.update(dict(metadata))
                    row.meta = merged
                if result_summary is not None:
                    row.result_summary = result_summary
                return row
        return None

    def get_by_operation_id(self, operation_id: str):
        for row in self.rows:
            if row.operation_id == operation_id:
                return row
        return None


class _FakeSessionService:
    def __init__(self):
        self.row = type("SessionRow", (), {"id": "session-row-1", "client_id": "client-row-1", "thread_id": "thread-row-1", "workspace_id": "workspace-row-1"})()

    def get_by_session_id(self, session_id: str):
        return self.row if session_id == "web:session-1" else None


class _FakeThreadService:
    def __init__(self):
        self.row = type("ThreadRow", (), {"id": "thread-row-1", "thread_id": "thread-1"})()

    def get_by_id(self, row_id):
        return self.row if row_id == "thread-row-1" else None


class _FakeWorkspaceService:
    def __init__(self):
        self.row = type("WorkspaceRow", (), {"id": "workspace-row-1", "workspace_id": "desktop-main"})()

    def get_by_id(self, row_id):
        return self.row if row_id == "workspace-row-1" else None


class _FakeGateway:
    def __init__(self):
        self.events = []

    async def publish_client_thread_event(self, thread_id: str, *, event_type: str, payload: dict):
        self.events.append({"thread_id": thread_id, "event_type": event_type, "payload": dict(payload)})


class _FakeBrain:
    def __init__(self, result):
        self._http_session = object()
        self.result = result
        self.calls = []

    async def run_background_turn(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.result)


class _FakeToolsManager:
    def get_scheduled_job_tools(self):
        return [
            {"type": "function", "function": {"name": "manage_scheduled_tasks"}},
            {"type": "function", "function": {"name": "get_current_system_time"}},
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
        app.brain = _FakeBrain(background_result)
        app.tools_manager = _FakeToolsManager()
        app.session_manager = None
        app.gateway = _FakeGateway()
        app.core_services = type(
            "CoreServices",
            (),
            {
                "operation": _FakeOperationService(),
                "session": _FakeSessionService(),
                "thread": _FakeThreadService(),
                "workspace": _FakeWorkspaceService(),
            },
        )()
        app._runtime_source = make_source(SourceKind.SYSTEM.value, "runtime")
        return app

    async def test_scheduled_reminder_control_marks_notification_pending_when_not_delivered(self):
        task_record = {
            "task_key": "daily-review",
            "content": "Review the daily digest",
            "next_run_at": "2026-04-02T01:00:00Z",
            "due_at": "2026-04-02T01:00:00Z",
            "notify_policy": "on_due",
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
        self.assertEqual(len(app.core_services.operation.rows), 1)
        self.assertEqual(app.core_services.operation.rows[0].operation_type, "scheduled_reminder_run")
        self.assertEqual(app.core_services.operation.rows[0].status, "succeeded")
        self.assertEqual(app.task_manager.remembered_operations[-1]["status"], "succeeded")

    async def test_scheduled_task_control_uses_allowlisted_tools_and_reports_brain_completion(self):
        task_record = {
            "task_key": "daily-news",
            "content": "Every day at 9 summarize AI news",
            "schedule_kind": "recurring",
            "next_run_at": "2026-04-02T01:00:00Z",
            "auto_run": True,
            "preferred_capability_ref": "manage_tasks",
            "preferred_agent_ids": ["desktop-main-agent"],
            "preferred_agent_types": ["desktop"],
            "agent_routing_policy": "strict_preferred",
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
        app = self._make_app(
            task_record,
            {
                "status": "ok",
                "content": "Wrote the daily summary report.",
                "completed_task_keys": ["daily-news"],
            },
        )

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
        self.assertEqual(len(app.brain.calls), 1)
        call = app.brain.calls[0]
        self.assertEqual(call["session_id"], "web:session-1")
        self.assertEqual(call["route_context"]["current_mode"], "scheduled_task")
        self.assertEqual(call["route_context"]["tool_bundle"], ["manage_scheduled_tasks", "get_current_system_time", "compile_report"])
        self.assertEqual(call["route_context"]["task_routing"]["preferred_capability_ref"], "manage_tasks")
        self.assertEqual(call["route_context"]["task_routing"]["preferred_agent_ids"], ["desktop-main-agent"])
        self.assertEqual(call["route_context"]["task_routing"]["agent_routing_policy"], "strict_preferred")
        self.assertEqual(
            [tool["function"]["name"] for tool in call["tools"]],
            ["manage_scheduled_tasks", "get_current_system_time", "compile_report"],
        )
        self.assertNotIn("manage_tasks", call["route_context"]["tool_bundle"])
        payload = json.loads(call["messages"][1]["content"])
        self.assertIn("time_context", payload)
        self.assertIn("orchestration", payload)
        self.assertIsNotNone(app.task_manager.completed_run)
        self.assertTrue(app.task_manager.completed_run["succeeded"])
        self.assertEqual(len(app.core_services.operation.rows), 1)
        self.assertEqual(app.core_services.operation.rows[0].operation_type, "scheduled_task_run")
        self.assertEqual(app.core_services.operation.rows[0].status, "succeeded")
        self.assertEqual(app.task_manager.remembered_operations[-1]["status"], "succeeded")
        self.assertTrue(app.task_manager.completed_run["delivered"])
        self.assertIn("Scheduled task completed:", app.task_manager.completed_run["summary"])
        self.assertEqual(len(delivered_messages), 1)
        self.assertIn("Wrote the daily summary report.", delivered_messages[0]["message"])

    async def test_scheduled_task_control_keeps_successful_run_waiting_for_completion(self):
        task_record = {
            "task_key": "daily-audit",
            "content": "Every day at 9 audit reports",
            "schedule_kind": "recurring",
            "next_run_at": "2026-04-02T01:00:00Z",
            "auto_run": True,
            "notify_policy": "on_completion",
            "delivery_target": {
                "kind": "current_session",
                "id": "",
                "session_id": "web:session-2",
                "source_kind": "web",
                "source_id": "browser-2",
            },
            "origin_session_id": "web:session-2",
            "scope": {"user_id": "user-2"},
        }
        app = self._make_app(task_record, {"status": "ok", "content": "Audit steps ran successfully."})

        delivered_messages = []

        async def _emit_task_update(task_record, message):
            delivered_messages.append({"task_key": task_record.get("task_key"), "message": message})
            return True

        app._emit_task_update = _emit_task_update

        handled = await App._handle_control_event(
            app,
            InboundEvent(
                session_id="system:task:daily-audit",
                type=EventType.CONTROL.value,
                role="system",
                content={"task_key": "daily-audit"},
                source=make_source(SourceKind.SYSTEM.value, "scheduler"),
                target=EventTarget(kind=TargetKind.INTERNAL.value),
                metadata={"control_kind": "scheduled_task"},
            ),
        )

        self.assertTrue(handled)
        self.assertIsNotNone(app.task_manager.completed_run)
        self.assertTrue(app.task_manager.completed_run["succeeded"])
        self.assertIn("awaiting completion confirmation", app.task_manager.completed_run["summary"])
        self.assertEqual(len(delivered_messages), 1)
        self.assertIn("awaiting completion confirmation", delivered_messages[0]["message"])

    async def test_scheduled_task_control_reports_failure_through_task_run_state(self):
        task_record = {
            "task_key": "daily-sync",
            "content": "Every day at 9 sync the digest",
            "schedule_kind": "recurring",
            "next_run_at": "2026-04-02T01:00:00Z",
            "auto_run": True,
            "notify_policy": "on_completion",
            "delivery_target": {
                "kind": "current_session",
                "id": "",
                "session_id": "web:session-3",
                "source_kind": "web",
                "source_id": "browser-3",
            },
            "origin_session_id": "web:session-3",
            "scope": {"user_id": "user-3"},
        }
        app = self._make_app(
            task_record,
            {
                "status": "error",
                "content": "Digest sync failed.",
                "error": {
                    "category": "manual_intervention",
                    "retryable": False,
                    "code": "digest_sync_denied",
                    "details": {"provider": "digest-api"},
                },
            },
        )

        delivered_messages = []

        async def _emit_task_update(task_record, message):
            delivered_messages.append({"task_key": task_record.get("task_key"), "message": message})
            return True

        app._emit_task_update = _emit_task_update

        handled = await App._handle_control_event(
            app,
            InboundEvent(
                session_id="system:task:daily-sync",
                type=EventType.CONTROL.value,
                role="system",
                content={"task_key": "daily-sync"},
                source=make_source(SourceKind.SYSTEM.value, "scheduler"),
                target=EventTarget(kind=TargetKind.INTERNAL.value),
                metadata={"control_kind": "scheduled_task"},
            ),
        )

        self.assertTrue(handled)
        self.assertIsNotNone(app.task_manager.completed_run)
        self.assertFalse(app.task_manager.completed_run["succeeded"])
        self.assertTrue(app.task_manager.completed_run["delivered"])
        self.assertIn("Scheduled task failed:", app.task_manager.completed_run["summary"])
        self.assertEqual(app.task_manager.completed_run["failure_category"], "manual_intervention")
        self.assertFalse(app.task_manager.completed_run["failure_retryable"])
        self.assertEqual(app.task_manager.completed_run["runtime_source"], "app.scheduled_task")
        self.assertEqual(len(delivered_messages), 1)
        self.assertIn("Digest sync failed.", delivered_messages[0]["message"])

    async def test_scheduled_task_control_reuses_scheduler_precreated_operation(self):
        task_record = {
            "task_key": "daily-precreated",
            "content": "Every day at 9 prepare report",
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
        app = self._make_app(task_record, {"status": "ok", "content": "Report prepared.", "completed_task_keys": ["daily-precreated"]})
        precreated = app.core_services.operation.create_operation(
            thread_id="thread-row-1",
            workspace_id="workspace-row-1",
            operation_type="scheduled_task_run",
            execution_target="core_only",
            title="Scheduled Task: Every day at 9 prepare report",
            metadata={"task_key": "daily-precreated", "workspace_id": "desktop-main"},
        )

        async def _emit_task_update(task_record, message):
            del task_record, message
            return True

        app._emit_task_update = _emit_task_update

        handled = await App._handle_control_event(
            app,
            InboundEvent(
                session_id="system:task:daily-precreated",
                type=EventType.CONTROL.value,
                role="system",
                content={"task_key": "daily-precreated", "operation_id": precreated.operation_id},
                source=make_source(SourceKind.SYSTEM.value, "scheduler"),
                target=EventTarget(kind=TargetKind.INTERNAL.value),
                metadata={"control_kind": "scheduled_task", "operation_id": precreated.operation_id},
            ),
        )

        self.assertTrue(handled)
        self.assertEqual(len(app.core_services.operation.rows), 1)
        self.assertEqual(app.core_services.operation.rows[0].status, "succeeded")

    async def test_scheduled_control_ignores_stale_claim_token(self):
        task_record = {
            "task_key": "daily-review",
            "content": "Review the daily digest",
            "next_run_at": "2026-04-02T01:00:00Z",
            "due_at": "2026-04-02T01:00:00Z",
            "notify_policy": "on_due",
            "active_claim_token": "fresh-claim",
        }
        app = self._make_app(task_record, {"status": "ok", "content": "unused"})

        async def _emit_task_update(task_record, message):
            del task_record, message
            return True

        app._emit_task_update = _emit_task_update

        handled = await App._handle_control_event(
            app,
            InboundEvent(
                session_id="system:task:daily-review",
                type=EventType.CONTROL.value,
                role="system",
                content={"task_key": "daily-review", "claim_token": "stale-claim"},
                source=make_source(SourceKind.SYSTEM.value, "scheduler"),
                target=EventTarget(kind=TargetKind.INTERNAL.value),
                metadata={"control_kind": "scheduled_reminder", "claim_token": "stale-claim"},
            ),
        )

        self.assertTrue(handled)
        self.assertIsNone(app.task_manager.completed_due)
        self.assertEqual(app.task_manager.checked_claims, [("daily-review", "stale-claim")])


if __name__ == "__main__":
    unittest.main()
