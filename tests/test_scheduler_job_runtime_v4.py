from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from core.app import App


def _row(**kwargs):
    return SimpleNamespace(**kwargs)


class _RunService:
    def __init__(self):
        self.created = []
        self.status_updates = []

    def create_run(self, **kwargs):
        row = _row(id=f"run-row-{len(self.created) + 1}", run_id=f"run_{len(self.created) + 1}", **kwargs)
        self.created.append(row)
        return row

    def update_status(self, **kwargs):
        self.status_updates.append(dict(kwargs))
        return _row(**kwargs)


class _RunEventService:
    def __init__(self):
        self.events = []

    def append_event(self, **kwargs):
        row = _row(
            id=f"event-row-{len(self.events) + 1}",
            event_id=f"evt_{len(self.events) + 1}",
            seq=len(self.events) + 1,
            created_at=datetime.now(timezone.utc),
            **kwargs,
        )
        self.events.append(row)
        return row


class _JobRunService:
    def __init__(self):
        self.created = []
        self.status_updates = []

    def create_job_run(self, **kwargs):
        row = _row(id=f"jobrun-row-{len(self.created) + 1}", job_run_id=f"jobrun_{len(self.created) + 1}", **kwargs)
        self.created.append(row)
        return row

    def update_status(self, **kwargs):
        self.status_updates.append(dict(kwargs))
        return _row(**kwargs)


class _MessageService:
    def __init__(self):
        self.created = []

    def create_message(self, **kwargs):
        row = _row(
            id=f"message-row-{len(self.created) + 1}",
            message_id=f"msg_{len(self.created) + 1}",
            channel=kwargs.get("channel", "message"),
            created_at=datetime.now(timezone.utc),
            **kwargs,
        )
        self.created.append(row)
        return row


class _DeliveryService:
    def __init__(self):
        self.calls = []

    async def deliver(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"sent": False, "status": "queued"}


class _Brain:
    def __init__(self):
        self.calls = []

    async def run_background_turn(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"status": "ok", "content": "Scheduled job result", "tool_names": ["get_current_system_time"], "result": {"ok": True}}


class _Gateway:
    def __init__(self):
        self.events = []

    async def publish_endpoint_run_event(self, **kwargs):
        self.events.append(dict(kwargs))
        return 1


class SchedulerJobRuntimeV4Tests(unittest.IsolatedAsyncioTestCase):
    def _make_app(self):
        job = _row(
            id="job-row-1",
            job_id="acceptance.job",
            kind="workflow",
            name="Acceptance Job",
            workspace_id=None,
            action_ref="core.workflow.assistant_turn",
            run_template={"prompt": "Write an acceptance result.", "tool_bundle": ["get_current_system_time"]},
            execution_policy={},
            delivery_policy={"targets": [{"endpoint_id": "core.inbox"}]},
            meta={},
            deletable=True,
        )
        workspace = _row(id="workspace-row-1", workspace_id="personal")
        thread = _row(id="thread-row-1", thread_id="thr_1", workspace_id=workspace.id)
        session = _row(id="session-row-1", session_id="sess_1", thread_id=thread.id, workspace_id=workspace.id)
        scheduler_endpoint = _row(id="endpoint-row-scheduler", endpoint_id="core.scheduler")
        inbox_endpoint = _row(id="endpoint-row-inbox", endpoint_id="core.inbox")

        services = SimpleNamespace(
            actor=SimpleNamespace(
                get_by_actor_id=lambda actor_id: _row(id=f"actor-{actor_id}", actor_id=actor_id),
                ensure_actor=lambda **kwargs: _row(id=f"actor-{kwargs['actor_id']}", **kwargs),
            ),
            endpoint=SimpleNamespace(
                get_by_endpoint_id=lambda endpoint_id: {"core.scheduler": scheduler_endpoint, "core.inbox": inbox_endpoint}.get(endpoint_id),
            ),
            workspace=SimpleNamespace(
                get_by_id=lambda row_id: workspace if row_id == workspace.id else None,
                get_by_workspace_id=lambda workspace_id: workspace if workspace_id == "personal" else None,
            ),
            thread=SimpleNamespace(
                create_thread=lambda **kwargs: thread,
                get_by_thread_id=lambda thread_id: thread if thread_id == thread.thread_id else None,
                get_by_id=lambda row_id: thread if row_id == thread.id else None,
            ),
            session=SimpleNamespace(
                create_session=lambda **kwargs: session,
                get_by_session_id=lambda session_id: session if session_id == session.session_id else None,
            ),
            scheduler=SimpleNamespace(
                update_job=lambda **kwargs: job,
                get_job=lambda job_id: job if job_id == job.job_id else None,
            ),
            run=_RunService(),
            run_event=_RunEventService(),
            scheduled_job_run=_JobRunService(),
            message=_MessageService(),
            delivery=_DeliveryService(),
        )

        app = App.__new__(App)
        app.core_domain = SimpleNamespace(principal=_row(id="principal-row-1"), services=services)
        app.core_services = services
        app.tools_manager = SimpleNamespace(
            get_scheduled_job_tools=lambda: [
                {"type": "function", "function": {"name": "get_current_system_time"}},
                {"type": "function", "function": {"name": "compile_report"}},
            ]
        )
        app.brain = _Brain()
        app.config = SimpleNamespace(
            get=lambda key, default=None: default or "",
            get_bool=lambda key, default=False: default,
        )
        app.gateway = _Gateway()
        return app, job, services

    async def test_scheduler_job_runs_background_turn_persists_message_and_fans_out_events(self):
        app, job, services = self._make_app()

        result = await App._run_assistant_scheduled_job(app, job, workspace_id="personal", manual=True)

        self.assertTrue(result["triggered"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(services.run.created), 1)
        self.assertEqual(len(services.scheduled_job_run.created), 1)
        self.assertEqual([event.type for event in services.run_event.events], ["run.started", "message.completed", "run.completed"])
        self.assertEqual(len(services.message.created), 1)
        self.assertEqual(services.message.created[0].content, "Scheduled job result")
        self.assertEqual(len(services.delivery.calls), 1)
        self.assertEqual(services.delivery.calls[0]["message_type"], "message")
        self.assertEqual(len(app.gateway.events), 3)
        self.assertEqual(app.brain.calls[0]["route_context"]["tool_bundle"], ["get_current_system_time"])


if __name__ == "__main__":
    unittest.main()
