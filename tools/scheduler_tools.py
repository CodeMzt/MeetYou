from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any

from core.services.heartbeat_workflow import HeartbeatWorkflow


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _positive_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError("interval_seconds must be a positive integer") from None
    if parsed <= 0:
        raise ValueError("interval_seconds must be a positive integer")
    return parsed


def _compact_job(job) -> dict[str, Any]:
    return {
        "job_id": str(getattr(job, "job_id", "") or ""),
        "kind": str(getattr(job, "kind", "") or ""),
        "name": str(getattr(job, "name", "") or ""),
        "workspace_id": str(getattr(job, "workspace_id", "") or ""),
        "singleton_key": str(getattr(job, "singleton_key", "") or ""),
        "enabled": bool(getattr(job, "enabled", True)),
        "deletable": bool(getattr(job, "deletable", True)),
        "editable_fields": list(getattr(job, "editable_fields", []) or []),
        "trigger_type": str(getattr(job, "trigger_type", "") or "interval"),
        "trigger_config": dict(getattr(job, "trigger_config", {}) or {}),
        "timezone": str(getattr(job, "timezone", "") or "UTC"),
        "action_ref": str(getattr(job, "action_ref", "") or ""),
        "run_template": dict(getattr(job, "run_template", {}) or {}),
        "execution_policy": dict(getattr(job, "execution_policy", {}) or {}),
        "delivery_policy": dict(getattr(job, "delivery_policy", {}) or {}),
        "concurrency_policy": dict(getattr(job, "concurrency_policy", {}) or {}),
        "misfire_policy": dict(getattr(job, "misfire_policy", {}) or {}),
        "metadata": dict(getattr(job, "meta", {}) or {}),
        "created_at": getattr(job, "created_at", "").isoformat()
        if getattr(job, "created_at", None) is not None
        else "",
        "updated_at": getattr(job, "updated_at", "").isoformat()
        if getattr(job, "updated_at", None) is not None
        else "",
    }


def _is_system_heartbeat_definition(*, job_id: str = "", kind: str = "", action_ref: str = "") -> bool:
    return (
        str(job_id or "").strip() == "system.heartbeat"
        or str(kind or "").strip() == "system_heartbeat"
        or str(action_ref or "").strip() == "core.workflow.heartbeat"
    )


class SchedulerTools:
    def __init__(self) -> None:
        self._core_domain = None
        self._trigger_job_callback = None

    def set_core_domain(self, core_domain) -> None:
        self._core_domain = core_domain

    def set_trigger_job_callback(self, callback) -> None:
        self._trigger_job_callback = callback

    def _domain(self):
        if self._core_domain is None:
            raise RuntimeError("Core domain is unavailable.")
        return self._core_domain

    def _workspace_row(self, workspace_id: str = ""):
        domain = self._domain()
        normalized = str(workspace_id or "").strip()
        if not normalized:
            return None
        workspace = domain.services.workspace.get_by_workspace_id(normalized)
        if workspace is None:
            raise ValueError(f"Unknown workspace: {normalized}")
        return workspace

    def _trigger_config(self, trigger_config: dict[str, Any] | None, interval_seconds: Any) -> dict[str, Any]:
        config = dict(trigger_config or {})
        interval = _positive_int(interval_seconds)
        if interval is not None:
            config["type"] = "interval"
            config["interval_seconds"] = interval
        return config

    def _job_or_raise(self, job_id: str):
        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id is required.")
        job = self._domain().services.scheduler.get_job(normalized)
        if job is None:
            raise ValueError(f"Unknown scheduled job: {normalized}")
        return job

    def _trigger_regular_job(self, job, *, workspace_id: str = "") -> dict[str, Any]:
        domain = self._domain()
        scheduler_actor = domain.services.actor.get_by_actor_id("system.scheduler")
        if scheduler_actor is None:
            scheduler_actor = domain.services.actor.ensure_actor(
                actor_id="system.scheduler",
                actor_type="system_scheduler",
                display_name="System Scheduler",
                permission_profile_id="profile.system_scheduler",
            )
        scheduler_endpoint = domain.services.endpoint.get_by_endpoint_id("core.scheduler")
        workspace = None
        if getattr(job, "workspace_id", None) is not None:
            workspace = domain.services.workspace.get_by_id(job.workspace_id)
        if workspace is None:
            workspace = self._workspace_row(workspace_id or "personal")
        if workspace is None:
            raise ValueError("workspace_id is required for triggering this scheduled job.")

        run = domain.services.run.create_run(
            workspace_id=workspace.id,
            trigger_type="scheduled_job",
            origin_actor_id=scheduler_actor.id,
            origin_endpoint_id=getattr(scheduler_endpoint, "id", None),
            status="running",
            input={"job_id": job.job_id, "manual_triggered_at": _utcnow_iso()},
            execution_policy=dict(getattr(job, "execution_policy", {}) or {}),
            delivery_policy=dict(getattr(job, "delivery_policy", {}) or {}),
            metadata={"scheduled_job_id": job.job_id, "action_ref": getattr(job, "action_ref", "") or ""},
        )
        job_run = domain.services.scheduled_job_run.create_job_run(
            job_id=job.id,
            run_id=run.id,
            status="succeeded",
            metadata={"manual_trigger": True, "job_id": job.job_id},
        )
        domain.services.run_event.append_event(
            run_id=run.id,
            type="run.started",
            durable=True,
            payload={"trigger_type": "scheduled_job", "job_id": job.job_id},
        )
        domain.services.run_event.append_event(
            run_id=run.id,
            type="run.completed",
            durable=True,
            payload={"status": "no_op", "job_id": job.job_id},
        )
        domain.services.run.update_status(run_row_id=run.id, status="succeeded", output={"status": "no_op"})
        return {
            "triggered": True,
            "job_id": job.job_id,
            "job_run_id": job_run.job_run_id,
            "run_id": run.run_id,
            "actor_id": "system.scheduler",
        }

    async def manage_scheduled_jobs(
        self,
        action: str = "list",
        job_id: str = "",
        kind: str = "workflow",
        name: str = "",
        workspace_id: str = "",
        singleton_key: str | None = None,
        enabled: bool | None = None,
        trigger_type: str = "interval",
        trigger_config: dict[str, Any] | None = None,
        interval_seconds: int | None = None,
        timezone: str = "UTC",
        action_ref: str = "",
        run_template: dict[str, Any] | None = None,
        execution_policy: dict[str, Any] | None = None,
        delivery_policy: dict[str, Any] | None = None,
        concurrency_policy: dict[str, Any] | None = None,
        misfire_policy: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        normalized_action = str(action or "list").strip().lower()
        domain = self._domain()

        if normalized_action == "list":
            jobs = [_compact_job(job) for job in domain.services.scheduler.list_jobs()]
            return {"ok": True, "count": len(jobs), "jobs": jobs}

        if normalized_action == "detail":
            return {"ok": True, "job": _compact_job(self._job_or_raise(job_id))}

        if normalized_action == "create":
            if _is_system_heartbeat_definition(job_id=job_id, kind=kind, action_ref=action_ref):
                raise ValueError("system.heartbeat is a Scheduler-owned preset job and cannot be created through manage_scheduled_jobs.")
            workspace = self._workspace_row(workspace_id)
            job = domain.services.scheduler.create_job(
                job_id=str(job_id or "").strip() or None,
                kind=str(kind or "workflow").strip() or "workflow",
                name=str(name or "").strip(),
                workspace_id=getattr(workspace, "id", None),
                singleton_key=singleton_key,
                enabled=True if enabled is None else bool(enabled),
                trigger_type=str(trigger_type or "interval").strip() or "interval",
                trigger_config=self._trigger_config(trigger_config, interval_seconds),
                timezone=str(timezone or "UTC").strip() or "UTC",
                action_ref=str(action_ref or "core.workflow.assistant_turn").strip(),
                run_template=dict(run_template or {}),
                execution_policy=dict(execution_policy or {}),
                delivery_policy=dict(delivery_policy or {}),
                concurrency_policy=dict(concurrency_policy or {}),
                misfire_policy=dict(misfire_policy or {}),
                metadata=dict(metadata or {}),
            )
            return {"ok": True, "job": _compact_job(job)}

        if normalized_action == "update":
            existing = self._job_or_raise(job_id)
            if str(getattr(existing, "job_id", "") or "") != "system.heartbeat" and str(action_ref or "").strip() == "core.workflow.heartbeat":
                raise ValueError("Only system.heartbeat may use core.workflow.heartbeat.")
            updates: dict[str, Any] = {}
            if name != "":
                updates["name"] = str(name or "").strip()
            if enabled is not None:
                updates["enabled"] = bool(enabled)
            if trigger_config is not None or interval_seconds is not None:
                updates["trigger_config"] = self._trigger_config(trigger_config, interval_seconds)
            if timezone:
                updates["timezone"] = str(timezone or "").strip()
            if action_ref != "":
                updates["action_ref"] = str(action_ref or "").strip()
            if run_template is not None:
                updates["run_template"] = dict(run_template or {})
            if execution_policy is not None:
                updates["execution_policy"] = dict(execution_policy or {})
            if delivery_policy is not None:
                updates["delivery_policy"] = dict(delivery_policy or {})
            if concurrency_policy is not None:
                updates["concurrency_policy"] = dict(concurrency_policy or {})
            if misfire_policy is not None:
                updates["misfire_policy"] = dict(misfire_policy or {})
            if metadata is not None:
                updates["metadata"] = dict(metadata or {})
            if not updates:
                raise ValueError("update requires at least one mutable field.")
            job = domain.services.scheduler.update_job(job_id=str(job_id or "").strip(), **updates)
            return {"ok": True, "job": _compact_job(job)}

        if normalized_action in {"enable", "disable"}:
            self._job_or_raise(job_id)
            job = domain.services.scheduler.set_enabled(
                job_id=str(job_id or "").strip(),
                enabled=normalized_action == "enable",
            )
            return {"ok": True, "job": _compact_job(job)}

        if normalized_action == "delete":
            self._job_or_raise(job_id)
            deleted = domain.services.scheduler.delete_job(job_id=str(job_id or "").strip())
            return {"ok": True, "job_id": str(job_id or "").strip(), "deleted": bool(deleted)}

        if normalized_action == "trigger":
            job = self._job_or_raise(job_id)
            if self._trigger_job_callback is not None:
                result = self._trigger_job_callback(
                    job_id=str(getattr(job, "job_id", "") or "").strip(),
                    workspace_id=workspace_id,
                    manual=True,
                )
                if inspect.isawaitable(result):
                    result = await result
                return {"ok": True, **dict(result or {})}
            if str(getattr(job, "job_id", "") or "") == "system.heartbeat":
                return {"ok": True, **HeartbeatWorkflow(domain.services).run_once(workspace_id=workspace_id or "personal")}
            return {"ok": True, **self._trigger_regular_job(job, workspace_id=workspace_id)}

        raise ValueError("action must be list, detail, create, update, enable, disable, delete, or trigger.")
