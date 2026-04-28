from __future__ import annotations

from uuid import uuid4

from core.db.repositories import ScheduledJobRepository, ScheduledJobRunRepository
from core.services.base import ServiceBase


class SchedulerService(ServiceBase):
    def create_job(
        self,
        *,
        job_id: str | None = None,
        kind: str,
        name: str = "",
        workspace_id=None,
        singleton_key: str | None = None,
        enabled: bool = True,
        trigger_type: str = "interval",
        trigger_config: dict | None = None,
        timezone: str = "UTC",
        action_ref: str = "",
        run_template: dict | None = None,
        execution_policy: dict | None = None,
        delivery_policy: dict | None = None,
        concurrency_policy: dict | None = None,
        misfire_policy: dict | None = None,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return ScheduledJobRepository(session).create(
                job_id=job_id or f"job_{uuid4().hex}",
                kind=kind,
                name=name,
                workspace_id=workspace_id,
                singleton_key=singleton_key,
                enabled=enabled,
                deletable=True,
                editable_fields=[
                    "name",
                    "enabled",
                    "trigger_config",
                    "timezone",
                    "action_ref",
                    "run_template",
                    "execution_policy",
                    "delivery_policy",
                    "concurrency_policy",
                    "misfire_policy",
                    "metadata",
                ],
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                timezone=timezone,
                action_ref=action_ref,
                run_template=run_template,
                execution_policy=execution_policy,
                delivery_policy=delivery_policy,
                concurrency_policy=concurrency_policy,
                misfire_policy=misfire_policy,
                metadata=metadata,
            )

    def list_jobs(self):
        with self.session_scope() as session:
            return ScheduledJobRepository(session).list_all()

    def ensure_system_heartbeat(self, *, interval_seconds: int = 600):
        with self.session_scope() as session:
            return ScheduledJobRepository(session).ensure_system_heartbeat(interval_seconds=interval_seconds)

    def get_job(self, job_id: str):
        with self.session_scope() as session:
            return ScheduledJobRepository(session).get_by_job_id(job_id)

    def set_enabled(self, *, job_id: str, enabled: bool):
        with self.session_scope() as session:
            return ScheduledJobRepository(session).set_enabled(job_id=job_id, enabled=enabled)

    def update_interval(self, *, job_id: str, interval_seconds: int):
        if int(interval_seconds) <= 0:
            raise ValueError("interval_seconds must be positive")
        with self.session_scope() as session:
            return ScheduledJobRepository(session).update_interval(job_id=job_id, interval_seconds=interval_seconds)

    def update_job(self, *, job_id: str, **updates):
        with self.session_scope() as session:
            return ScheduledJobRepository(session).update(job_id=job_id, **updates)

    def delete_job(self, *, job_id: str) -> bool:
        with self.session_scope() as session:
            return ScheduledJobRepository(session).delete(job_id=job_id)


class ScheduledJobRunService(ServiceBase):
    def create_job_run(self, *, job_id, scheduled_at=None, run_id=None, status: str = "queued", metadata: dict | None = None):
        with self.session_scope() as session:
            return ScheduledJobRunRepository(session).create(
                job_run_id=f"jobrun_{uuid4().hex}",
                job_id=job_id,
                run_id=run_id,
                scheduled_at=scheduled_at,
                status=status,
                metadata=metadata,
            )

    def update_status(self, *, job_run_id, status: str, error: dict | None = None, metadata: dict | None = None):
        with self.session_scope() as session:
            return ScheduledJobRunRepository(session).update_status(
                job_run_id=job_run_id,
                status=status,
                error=error,
                metadata=metadata,
            )
