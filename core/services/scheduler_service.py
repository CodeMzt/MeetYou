from __future__ import annotations

from uuid import uuid4

from core.db.repositories import ScheduledJobRepository, ScheduledJobRunRepository
from core.db.base import utcnow
from core.services.base import ServiceBase
from core.services.schedule_time import compute_next_fire_at, normalize_daily_trigger_config


def _normalize_trigger_config(
    *,
    trigger_type: str,
    trigger_config: dict | None,
    fallback_config: dict | None = None,
) -> dict:
    config = dict(trigger_config or {})
    kind = str(trigger_type or config.get("type") or "").strip().lower()
    if kind == "daily":
        return normalize_daily_trigger_config(config, fallback_config=fallback_config)
    return config


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
        normalized_trigger_type = str(trigger_type or "interval").strip() or "interval"
        normalized_trigger_config = _normalize_trigger_config(
            trigger_type=normalized_trigger_type,
            trigger_config=trigger_config,
        )
        next_fire_at = compute_next_fire_at(
            trigger_type=normalized_trigger_type,
            trigger_config=normalized_trigger_config,
            timezone_name=timezone,
            after=utcnow(),
        )
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
                trigger_type=normalized_trigger_type,
                trigger_config=normalized_trigger_config,
                timezone=timezone,
                action_ref=action_ref,
                run_template=run_template,
                execution_policy=execution_policy,
                delivery_policy=delivery_policy,
                concurrency_policy=concurrency_policy,
                misfire_policy=misfire_policy,
                next_fire_at=next_fire_at,
                metadata=metadata,
            )

    def list_jobs(self):
        with self.session_scope() as session:
            return ScheduledJobRepository(session).list_all()

    def list_due_jobs(self, *, now=None, limit: int = 50):
        with self.session_scope() as session:
            return ScheduledJobRepository(session).list_due(now=now or utcnow(), limit=limit)

    def ensure_missing_next_fire_times(self, *, limit: int = 50) -> int:
        updated = 0
        with self.session_scope() as session:
            repo = ScheduledJobRepository(session)
            for row in repo.list_missing_next_fire_at(limit=limit):
                row.next_fire_at = compute_next_fire_at(
                    trigger_type=row.trigger_type,
                    trigger_config=row.trigger_config,
                    timezone_name=row.timezone,
                    after=utcnow(),
                )
                updated += 1
            if updated:
                session.flush()
        return updated

    def next_fire_at(self):
        with self.session_scope() as session:
            return ScheduledJobRepository(session).next_fire_at()

    def ensure_system_heartbeat(self, *, interval_seconds: int = 600):
        with self.session_scope() as session:
            repo = ScheduledJobRepository(session)
            row = repo.ensure_system_heartbeat(interval_seconds=interval_seconds)
            if row.next_fire_at is None:
                row.next_fire_at = compute_next_fire_at(
                    trigger_type=row.trigger_type,
                    trigger_config=row.trigger_config,
                    timezone_name=row.timezone,
                    after=utcnow(),
                )
                session.flush()
            return row

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
            repo = ScheduledJobRepository(session)
            row = repo.update_interval(job_id=job_id, interval_seconds=interval_seconds)
            if row is not None:
                row.next_fire_at = compute_next_fire_at(
                    trigger_type=row.trigger_type,
                    trigger_config=row.trigger_config,
                    timezone_name=row.timezone,
                    after=utcnow(),
                )
                session.flush()
            return row

    def update_job(self, *, job_id: str, **updates):
        should_recompute = any(key in updates for key in {"trigger_type", "trigger_config", "timezone"})
        with self.session_scope() as session:
            repo = ScheduledJobRepository(session)
            row = repo.get_by_job_id(job_id)
            if row is None:
                return None
            if "trigger_type" in updates or "trigger_config" in updates:
                next_trigger_type = str(updates.get("trigger_type") or row.trigger_type or "").strip()
                updates["trigger_config"] = _normalize_trigger_config(
                    trigger_type=next_trigger_type,
                    trigger_config=updates.get("trigger_config") if "trigger_config" in updates else row.trigger_config,
                    fallback_config=dict(row.trigger_config or {}),
                )
            row = repo.update(job_id=job_id, **updates)
            if row is not None and should_recompute:
                row.next_fire_at = compute_next_fire_at(
                    trigger_type=row.trigger_type,
                    trigger_config=row.trigger_config,
                    timezone_name=row.timezone,
                    after=utcnow(),
                )
                session.flush()
            return row

    def delete_job(self, *, job_id: str) -> bool:
        with self.session_scope() as session:
            return ScheduledJobRepository(session).delete(job_id=job_id)

    def ensure_next_fire_at(self, *, job_id: str):
        with self.session_scope() as session:
            repo = ScheduledJobRepository(session)
            row = repo.get_by_job_id(job_id)
            if row is None:
                return None
            if row.next_fire_at is None:
                row.next_fire_at = compute_next_fire_at(
                    trigger_type=row.trigger_type,
                    trigger_config=row.trigger_config,
                    timezone_name=row.timezone,
                    after=utcnow(),
                )
                session.flush()
            return row

    def acquire_due_lease(self, *, job_id: str, lease_owner: str, lease_seconds: int = 300):
        with self.session_scope() as session:
            return ScheduledJobRepository(session).acquire_due_lease(
                job_id=job_id,
                now=utcnow(),
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
            )

    def mark_fired(self, *, job_id: str, fired_at=None):
        fired = fired_at or utcnow()
        with self.session_scope() as session:
            repo = ScheduledJobRepository(session)
            row = repo.get_by_job_id(job_id)
            if row is None:
                return None
            next_fire_at = compute_next_fire_at(
                trigger_type=row.trigger_type,
                trigger_config=row.trigger_config,
                timezone_name=row.timezone,
                after=fired,
            )
            return repo.mark_fired(job_id=job_id, fired_at=fired, next_fire_at=next_fire_at)

    def release_lease(self, *, job_id: str):
        with self.session_scope() as session:
            return ScheduledJobRepository(session).release_lease(job_id=job_id)


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
