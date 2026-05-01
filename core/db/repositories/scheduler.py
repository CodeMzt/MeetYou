from __future__ import annotations

from datetime import timezone, timedelta

from core.db.base import utcnow
from core.db.models.scheduler import ScheduledJob, ScheduledJobRun
from core.db.repositories.base import RepositoryBase


def _ensure_utc(value):
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ScheduledJobRepository(RepositoryBase):
    def create(
        self,
        *,
        job_id: str,
        kind: str,
        name: str = "",
        workspace_id=None,
        singleton_key: str | None = None,
        enabled: bool = True,
        deletable: bool = True,
        editable_fields: list | None = None,
        trigger_type: str = "interval",
        trigger_config: dict | None = None,
        timezone: str = "UTC",
        action_ref: str = "",
        run_template: dict | None = None,
        execution_policy: dict | None = None,
        delivery_policy: dict | None = None,
        concurrency_policy: dict | None = None,
        misfire_policy: dict | None = None,
        next_fire_at=None,
        last_fire_at=None,
        lease_owner: str = "",
        lease_until_at=None,
        metadata: dict | None = None,
    ) -> ScheduledJob:
        row = ScheduledJob(
            job_id=job_id,
            workspace_id=workspace_id,
            kind=kind,
            singleton_key=singleton_key,
            name=name,
            enabled=bool(enabled),
            deletable=bool(deletable),
            editable_fields=list(editable_fields or []),
            trigger_type=trigger_type,
            trigger_config=dict(trigger_config or {}),
            timezone=timezone,
            action_ref=action_ref,
            run_template=dict(run_template or {}),
            execution_policy=dict(execution_policy or {}),
            delivery_policy=dict(delivery_policy or {}),
            concurrency_policy=dict(concurrency_policy or {}),
            misfire_policy=dict(misfire_policy or {}),
            next_fire_at=next_fire_at,
            last_fire_at=last_fire_at,
            lease_owner=str(lease_owner or ""),
            lease_until_at=lease_until_at,
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def ensure_system_heartbeat(self, *, interval_seconds: int = 600) -> ScheduledJob:
        row = self.get_by_job_id("system.heartbeat")
        if row is None:
            return self.create(
                job_id="system.heartbeat",
                kind="system_heartbeat",
                singleton_key="core.system.heartbeat",
                name="System heartbeat",
                enabled=True,
                deletable=False,
                editable_fields=[
                    "enabled",
                    "trigger_config.interval_seconds",
                ],
                trigger_type="interval",
                trigger_config={"type": "interval", "interval_seconds": int(interval_seconds or 600)},
                timezone="UTC",
                action_ref="core.workflow.heartbeat",
                run_template={"trigger_type": "system_heartbeat", "origin_actor_id": "system.heartbeat"},
                execution_policy={"limits": {"max_runtime_seconds": 120}},
                delivery_policy={"targets": [{"endpoint_id": "core.inbox", "required": True}]},
                concurrency_policy={"mode": "skip_if_running"},
                misfire_policy={"mode": "run_once"},
                next_fire_at=None,
            )
        row.kind = "system_heartbeat"
        row.singleton_key = "core.system.heartbeat"
        row.deletable = False
        row.editable_fields = [
            "enabled",
            "trigger_config.interval_seconds",
        ]
        row.action_ref = "core.workflow.heartbeat"
        if not isinstance(row.trigger_config, dict) or not row.trigger_config:
            row.trigger_config = {"type": "interval", "interval_seconds": int(interval_seconds or 600)}
        self.session.flush()
        return row

    def get_by_job_id(self, job_id: str) -> ScheduledJob | None:
        return self.session.query(ScheduledJob).filter_by(job_id=job_id).one_or_none()

    def list_all(self) -> list[ScheduledJob]:
        return list(self.session.query(ScheduledJob).order_by(ScheduledJob.job_id.asc()).all())

    def list_due(self, *, now, limit: int = 50) -> list[ScheduledJob]:
        normalized_limit = max(1, int(limit or 50))
        return list(
            self.session.query(ScheduledJob)
            .filter(ScheduledJob.enabled.is_(True))
            .filter(ScheduledJob.next_fire_at.is_not(None))
            .filter(ScheduledJob.next_fire_at <= now)
            .order_by(ScheduledJob.next_fire_at.asc(), ScheduledJob.job_id.asc())
            .limit(normalized_limit)
            .all()
        )

    def list_missing_next_fire_at(self, *, limit: int = 50) -> list[ScheduledJob]:
        normalized_limit = max(1, int(limit or 50))
        return list(
            self.session.query(ScheduledJob)
            .filter(ScheduledJob.enabled.is_(True))
            .filter(ScheduledJob.next_fire_at.is_(None))
            .order_by(ScheduledJob.job_id.asc())
            .limit(normalized_limit)
            .all()
        )

    def next_fire_at(self):
        row = (
            self.session.query(ScheduledJob)
            .filter(ScheduledJob.enabled.is_(True))
            .filter(ScheduledJob.next_fire_at.is_not(None))
            .order_by(ScheduledJob.next_fire_at.asc(), ScheduledJob.job_id.asc())
            .first()
        )
        return row.next_fire_at if row is not None else None

    def update(
        self,
        *,
        job_id: str,
        name: str | None = None,
        enabled: bool | None = None,
        trigger_type: str | None = None,
        trigger_config: dict | None = None,
        timezone: str | None = None,
        action_ref: str | None = None,
        run_template: dict | None = None,
        execution_policy: dict | None = None,
        delivery_policy: dict | None = None,
        concurrency_policy: dict | None = None,
        misfire_policy: dict | None = None,
        metadata: dict | None = None,
        next_fire_at=None,
        last_fire_at=None,
        lease_owner: str | None = None,
        lease_until_at=None,
    ) -> ScheduledJob | None:
        row = self.get_by_job_id(job_id)
        if row is None:
            return None
        is_system = not bool(row.deletable)
        if is_system:
            disallowed = [
                field_name
                for field_name, value in (
                    ("name", name),
                    ("trigger_type", trigger_type),
                    ("timezone", timezone),
                    ("action_ref", action_ref),
                    ("run_template", run_template),
                    ("execution_policy", execution_policy),
                    ("delivery_policy", delivery_policy),
                    ("concurrency_policy", concurrency_policy),
                    ("misfire_policy", misfire_policy),
                    ("metadata", metadata),
                )
                if value is not None
            ]
            if disallowed:
                raise ValueError("system.heartbeat only allows enabled and interval_seconds updates.")
            if enabled is not None:
                row.enabled = bool(enabled)
            if trigger_config is not None:
                requested = dict(trigger_config or {})
                unknown = sorted(set(requested) - {"type", "interval_seconds"})
                trigger_type = str(requested.get("type") or "interval").strip() or "interval"
                if unknown or trigger_type != "interval" or "interval_seconds" not in requested:
                    raise ValueError("system.heartbeat trigger_config may only set interval_seconds.")
                interval_seconds = int(requested.get("interval_seconds") or 0)
                if interval_seconds <= 0:
                    raise ValueError("system.heartbeat interval_seconds must be positive.")
                row.trigger_config = {"type": "interval", "interval_seconds": interval_seconds}
            self.session.flush()
            return row

        if name is not None:
            row.name = name
        if enabled is not None:
            row.enabled = bool(enabled)
        if trigger_type is not None:
            row.trigger_type = str(trigger_type or row.trigger_type)
        if trigger_config is not None:
            row.trigger_config = dict(trigger_config or {})
        if timezone is not None:
            row.timezone = timezone
        if action_ref is not None:
            row.action_ref = action_ref
        if run_template is not None:
            row.run_template = dict(run_template or {})
        if execution_policy is not None:
            row.execution_policy = dict(execution_policy or {})
        if delivery_policy is not None:
            row.delivery_policy = dict(delivery_policy or {})
        if concurrency_policy is not None:
            row.concurrency_policy = dict(concurrency_policy or {})
        if misfire_policy is not None:
            row.misfire_policy = dict(misfire_policy or {})
        if metadata is not None:
            row.meta = dict(metadata or {})
        if next_fire_at is not None:
            row.next_fire_at = next_fire_at
        if last_fire_at is not None:
            row.last_fire_at = last_fire_at
        if lease_owner is not None:
            row.lease_owner = str(lease_owner or "")
        if lease_until_at is not None:
            row.lease_until_at = lease_until_at
        self.session.flush()
        return row

    def set_enabled(self, *, job_id: str, enabled: bool) -> ScheduledJob | None:
        row = self.get_by_job_id(job_id)
        if row is None:
            return None
        row.enabled = bool(enabled)
        self.session.flush()
        return row

    def update_interval(self, *, job_id: str, interval_seconds: int) -> ScheduledJob | None:
        row = self.get_by_job_id(job_id)
        if row is None:
            return None
        config = dict(row.trigger_config or {})
        config["type"] = "interval"
        config["interval_seconds"] = int(interval_seconds)
        row.trigger_config = config
        self.session.flush()
        return row

    def delete(self, *, job_id: str) -> bool:
        row = self.get_by_job_id(job_id)
        if row is None:
            return False
        if not bool(row.deletable):
            raise ValueError(f"scheduled job is not deletable: {job_id}")
        self.session.delete(row)
        self.session.flush()
        return True

    def set_next_fire_at(self, *, job_id: str, next_fire_at) -> ScheduledJob | None:
        row = self.get_by_job_id(job_id)
        if row is None:
            return None
        row.next_fire_at = next_fire_at
        self.session.flush()
        return row

    def acquire_due_lease(self, *, job_id: str, now, lease_owner: str, lease_seconds: int = 300) -> ScheduledJob | None:
        row = self.get_by_job_id(job_id)
        if row is None or not bool(row.enabled):
            return None
        due_at = _ensure_utc(row.next_fire_at)
        if due_at is None or due_at > now:
            return None
        lease_until_at = _ensure_utc(row.lease_until_at)
        if lease_until_at is not None and lease_until_at > now and str(row.lease_owner or ""):
            return None
        row.lease_owner = str(lease_owner or "")
        row.lease_until_at = now + timedelta(seconds=max(int(lease_seconds or 300), 1))
        self.session.flush()
        return row

    def mark_fired(self, *, job_id: str, fired_at, next_fire_at) -> ScheduledJob | None:
        row = self.get_by_job_id(job_id)
        if row is None:
            return None
        row.last_fire_at = fired_at
        row.next_fire_at = next_fire_at
        row.lease_owner = ""
        row.lease_until_at = None
        self.session.flush()
        return row

    def release_lease(self, *, job_id: str) -> ScheduledJob | None:
        row = self.get_by_job_id(job_id)
        if row is None:
            return None
        row.lease_owner = ""
        row.lease_until_at = None
        self.session.flush()
        return row


class ScheduledJobRunRepository(RepositoryBase):
    def create(
        self,
        *,
        job_run_id: str,
        job_id,
        scheduled_at=None,
        run_id=None,
        status: str = "queued",
        metadata: dict | None = None,
    ) -> ScheduledJobRun:
        row = ScheduledJobRun(
            job_run_id=job_run_id,
            job_id=job_id,
            run_id=run_id,
            scheduled_at=scheduled_at or utcnow(),
            status=status,
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def update_status(self, *, job_run_id, status: str, error: dict | None = None, metadata: dict | None = None) -> ScheduledJobRun | None:
        row = self.session.query(ScheduledJobRun).filter_by(id=job_run_id).one_or_none()
        if row is None:
            row = self.session.query(ScheduledJobRun).filter_by(job_run_id=str(job_run_id or "")).one_or_none()
        if row is None:
            return None
        row.status = str(status or row.status)
        if row.status == "running" and row.started_at is None:
            row.started_at = utcnow()
        if row.status in {"succeeded", "failed", "cancelled"}:
            row.finished_at = utcnow()
        if error is not None:
            row.error = dict(error or {})
        if metadata:
            merged = dict(row.meta or {})
            merged.update(dict(metadata or {}))
            row.meta = merged
        self.session.flush()
        return row
