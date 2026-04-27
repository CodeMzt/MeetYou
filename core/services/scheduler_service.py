from __future__ import annotations

from uuid import uuid4

from core.db.repositories import ScheduledJobRepository, ScheduledJobRunRepository
from core.services.base import ServiceBase


class SchedulerService(ServiceBase):
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
