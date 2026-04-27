from __future__ import annotations

import unittest
from types import SimpleNamespace

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


if __name__ == "__main__":
    unittest.main()
