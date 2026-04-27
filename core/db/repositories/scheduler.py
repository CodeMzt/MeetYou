from __future__ import annotations

from core.db.base import utcnow
from core.db.models.scheduler import ScheduledJob, ScheduledJobRun
from core.db.repositories.base import RepositoryBase


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
                    "execution_policy.limits",
                    "delivery_policy",
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
            )
        row.kind = "system_heartbeat"
        row.singleton_key = "core.system.heartbeat"
        row.deletable = False
        row.editable_fields = [
            "enabled",
            "trigger_config.interval_seconds",
            "execution_policy.limits",
            "delivery_policy",
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

    def update(
        self,
        *,
        job_id: str,
        name: str | None = None,
        enabled: bool | None = None,
        trigger_config: dict | None = None,
        timezone: str | None = None,
        action_ref: str | None = None,
        run_template: dict | None = None,
        execution_policy: dict | None = None,
        delivery_policy: dict | None = None,
        concurrency_policy: dict | None = None,
        misfire_policy: dict | None = None,
        metadata: dict | None = None,
    ) -> ScheduledJob | None:
        row = self.get_by_job_id(job_id)
        if row is None:
            return None
        editable = set(row.editable_fields or [])
        is_system = not bool(row.deletable)
        if name is not None and not is_system:
            row.name = name
        if enabled is not None and ("enabled" in editable or not is_system):
            row.enabled = bool(enabled)
        if trigger_config is not None and ("trigger_config" in editable or "trigger_config.interval_seconds" in editable or not is_system):
            row.trigger_config = dict(trigger_config or {})
        if timezone is not None and not is_system:
            row.timezone = timezone
        if action_ref is not None and not is_system:
            row.action_ref = action_ref
        if run_template is not None and not is_system:
            row.run_template = dict(run_template or {})
        if execution_policy is not None and ("execution_policy" in editable or "execution_policy.limits" in editable or not is_system):
            row.execution_policy = dict(execution_policy or {})
        if delivery_policy is not None and ("delivery_policy" in editable or not is_system):
            row.delivery_policy = dict(delivery_policy or {})
        if concurrency_policy is not None and not is_system:
            row.concurrency_policy = dict(concurrency_policy or {})
        if misfire_policy is not None and not is_system:
            row.misfire_policy = dict(misfire_policy or {})
        if metadata is not None and not is_system:
            row.meta = dict(metadata or {})
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
