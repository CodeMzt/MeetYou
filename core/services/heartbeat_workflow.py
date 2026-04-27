from __future__ import annotations

from core.db.base import utcnow


class HeartbeatWorkflow:
    def __init__(self, services):
        self._services = services

    def run_once(self, *, workspace_id: str = "personal") -> dict:
        services = self._services
        job = services.scheduler.get_job("system.heartbeat")
        if job is None:
            job = services.scheduler.ensure_system_heartbeat()
        if not bool(getattr(job, "enabled", True)):
            return {"triggered": False, "reason": "disabled", "job_id": "system.heartbeat"}
        actor = services.actor.get_by_actor_id("system.heartbeat")
        if actor is None:
            actor = services.actor.ensure_actor(
                actor_id="system.heartbeat",
                actor_type="system_heartbeat",
                display_name="System Heartbeat",
                permission_profile_id="profile.system_heartbeat",
            )
        scheduler_endpoint = services.endpoint.get_by_endpoint_id("core.scheduler")
        workspace = services.workspace.get_by_workspace_id(workspace_id)
        if workspace is None:
            return {"triggered": False, "reason": "workspace_not_found", "workspace_id": workspace_id}
        run = services.run.create_run(
            workspace_id=workspace.id,
            trigger_type="system_heartbeat",
            origin_actor_id=actor.id,
            origin_endpoint_id=getattr(scheduler_endpoint, "id", None),
            status="running",
            input={"job_id": "system.heartbeat", "scheduled_at": utcnow().isoformat()},
        )
        job_run = services.scheduled_job_run.create_job_run(
            job_id=job.id,
            run_id=run.id,
            status="running",
            metadata={"trigger_type": "system_heartbeat"},
        )
        services.run_event.append_event(
            run_id=run.id,
            type="run.started",
            durable=True,
            payload={"trigger_type": "system_heartbeat", "job_id": "system.heartbeat"},
        )
        services.run_event.append_event(
            run_id=run.id,
            type="run.completed",
            durable=True,
            payload={"status": "no_op"},
        )
        services.run.update_status(run_row_id=run.id, status="succeeded", output={"status": "no_op"})
        return {
            "triggered": True,
            "job_id": "system.heartbeat",
            "job_run_id": job_run.job_run_id,
            "run_id": run.run_id,
            "actor_id": "system.heartbeat",
        }
