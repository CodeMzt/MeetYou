from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.services.scheduler_service import SchedulerService
from core.services.heartbeat_workflow import HeartbeatWorkflow


class _Service:
    def __init__(self):
        self.job = SimpleNamespace(id="job-row", job_id="system.heartbeat", enabled=True)
        self.events = []

    def get_job(self, job_id):
        return self.job

    def ensure_system_heartbeat(self):
        return self.job

    def get_by_actor_id(self, actor_id):
        return SimpleNamespace(id="actor-row", actor_id=actor_id)

    def get_by_endpoint_id(self, endpoint_id):
        return SimpleNamespace(id="endpoint-row", endpoint_id=endpoint_id)

    def get_by_workspace_id(self, workspace_id):
        return SimpleNamespace(id="workspace-row", workspace_id=workspace_id)

    def create_run(self, **kwargs):
        return SimpleNamespace(id="run-row", run_id="run_1", **kwargs)

    def create_job_run(self, **kwargs):
        return SimpleNamespace(job_run_id="jobrun_1", **kwargs)

    def append_event(self, **kwargs):
        self.events.append(kwargs)
        return SimpleNamespace(**kwargs)

    def update_status(self, **kwargs):
        return SimpleNamespace(**kwargs)


class SchedulerV4Tests(unittest.TestCase):
    def test_heartbeat_workflow_creates_job_run_and_run(self):
        service = _Service()
        services = SimpleNamespace(
            scheduler=service,
            actor=service,
            endpoint=service,
            workspace=service,
            run=service,
            scheduled_job_run=service,
            run_event=service,
        )

        result = HeartbeatWorkflow(services).run_once(workspace_id="personal")

        self.assertTrue(result["triggered"])
        self.assertEqual(result["actor_id"], "system.heartbeat")
        self.assertEqual([event["type"] for event in service.events], ["run.started", "run.completed"])

    def test_scheduler_service_lists_due_jobs_without_full_scan_contract(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        try:
            scheduler = SchedulerService(Session)
            now = datetime.now(timezone.utc)
            due = scheduler.create_job(
                job_id="due.job",
                kind="scheduled_workflow",
                trigger_type="interval",
                trigger_config={"interval_seconds": 60},
            )
            future = scheduler.create_job(
                job_id="future.job",
                kind="scheduled_workflow",
                trigger_type="interval",
                trigger_config={"interval_seconds": 60},
            )
            scheduler.update_job(job_id=due.job_id, next_fire_at=now - timedelta(seconds=1))
            scheduler.update_job(job_id=future.job_id, next_fire_at=now + timedelta(minutes=5))

            jobs = scheduler.list_due_jobs(now=now, limit=10)

            self.assertEqual([job.job_id for job in jobs], ["due.job"])
            self.assertEqual(scheduler.next_fire_at().replace(tzinfo=timezone.utc), now - timedelta(seconds=1))
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
