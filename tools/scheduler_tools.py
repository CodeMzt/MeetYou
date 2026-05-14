from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from typing import Any

from core.services.schedule_time import normalize_daily_trigger_config
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


def _metadata_summary(metadata: Any) -> dict[str, Any]:
    payload = dict(metadata or {}) if isinstance(metadata, dict) else {}
    rendered = json.dumps(payload, ensure_ascii=False, default=str) if payload else ""
    return {
        "key_count": len(payload),
        "keys": sorted(str(key) for key in payload.keys()),
        "byte_size_estimate": len(rendered.encode("utf-8", errors="ignore")) if rendered else 0,
    }


def _policy_summary(value: Any) -> dict[str, Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    rendered = json.dumps(payload, ensure_ascii=False, default=str) if payload else ""
    return {
        "present": bool(payload),
        "keys": sorted(str(key) for key in payload.keys()),
        "byte_size_estimate": len(rendered.encode("utf-8", errors="ignore")) if rendered else 0,
    }


def _compact_job(job, *, include_details: bool = True) -> dict[str, Any]:
    base = {
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
        "next_fire_at": getattr(job, "next_fire_at", "").isoformat()
        if getattr(job, "next_fire_at", None) is not None
        else "",
        "last_fire_at": getattr(job, "last_fire_at", "").isoformat()
        if getattr(job, "last_fire_at", None) is not None
        else "",
        "lease_owner": str(getattr(job, "lease_owner", "") or ""),
        "lease_until_at": getattr(job, "lease_until_at", "").isoformat()
        if getattr(job, "lease_until_at", None) is not None
        else "",
        "metadata_summary": _metadata_summary(getattr(job, "meta", {}) or {}),
        "run_template_summary": _policy_summary(getattr(job, "run_template", {}) or {}),
        "execution_policy_summary": _policy_summary(getattr(job, "execution_policy", {}) or {}),
        "delivery_policy_summary": _policy_summary(getattr(job, "delivery_policy", {}) or {}),
        "details_included": bool(include_details),
        "created_at": getattr(job, "created_at", "").isoformat()
        if getattr(job, "created_at", None) is not None
        else "",
        "updated_at": getattr(job, "updated_at", "").isoformat()
        if getattr(job, "updated_at", None) is not None
        else "",
    }
    if include_details:
        base.update(
            {
                "run_template": dict(getattr(job, "run_template", {}) or {}),
                "execution_policy": dict(getattr(job, "execution_policy", {}) or {}),
                "delivery_policy": dict(getattr(job, "delivery_policy", {}) or {}),
                "concurrency_policy": dict(getattr(job, "concurrency_policy", {}) or {}),
                "misfire_policy": dict(getattr(job, "misfire_policy", {}) or {}),
                "metadata": dict(getattr(job, "meta", {}) or {}),
            }
        )
    return base


def _job_list_summary(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        jobs,
        key=lambda item: (
            0 if bool(item.get("enabled")) else 1,
            str(item.get("kind") or "").lower(),
            str(item.get("job_id") or "").lower(),
        ),
    )
    lines: list[str] = []
    for item in ordered:
        job_id = str(item.get("job_id") or "")
        if not job_id:
            continue
        schedule = str(item.get("trigger_type") or "")
        trigger_config = item.get("trigger_config") if isinstance(item.get("trigger_config"), dict) else {}
        if trigger_config:
            schedule = f"{schedule}:{json.dumps(trigger_config, ensure_ascii=False, default=str)}"
        lines.append(
            f"{job_id} | kind={item.get('kind') or ''} | enabled={bool(item.get('enabled'))} | "
            f"schedule={schedule} | next_fire_at={item.get('next_fire_at') or ''} | name={item.get('name') or ''}"
        )
    return {
        "job_lines": lines,
        "job_ids": [item["job_id"] for item in ordered if item.get("job_id")],
        "compact_jobs": ordered,
    }


def _is_system_heartbeat_definition(*, job_id: str = "", kind: str = "", action_ref: str = "") -> bool:
    return (
        str(job_id or "").strip() == "system.heartbeat"
        or str(kind or "").strip() == "system_heartbeat"
        or str(action_ref or "").strip() == "core.workflow.heartbeat"
    )


def _normalize_schedule(
    schedule: dict[str, Any] | None,
    *,
    timezone_name: str = "",
    fallback_config: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], str]:
    payload = dict(schedule or {})
    schedule_type = str(payload.get("type") or payload.get("schedule") or "daily").strip().lower() or "daily"
    tz = str(payload.get("timezone") or timezone_name or "Asia/Shanghai").strip() or "Asia/Shanghai"
    if schedule_type == "daily":
        return "daily", normalize_daily_trigger_config(payload, fallback_config=fallback_config), tz
    if schedule_type == "interval":
        interval_seconds = _positive_int(payload.get("interval_seconds"))
        if interval_seconds is None:
            raise ValueError("schedule.interval_seconds is required for interval schedules.")
        return "interval", {"type": "interval", "interval_seconds": interval_seconds}, tz
    if schedule_type == "cron":
        expression = str(payload.get("expression") or payload.get("cron") or "").strip()
        if not expression:
            raise ValueError("schedule.expression is required for cron schedules.")
        return "cron", {"type": "cron", "expression": expression}, tz
    if schedule_type == "one_shot":
        run_at = str(payload.get("run_at") or payload.get("at") or "").strip()
        if not run_at:
            raise ValueError("schedule.run_at is required for one_shot schedules.")
        return "one_shot", {"type": "one_shot", "run_at": run_at}, tz
    raise ValueError("schedule.type must be daily, interval, cron, or one_shot.")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _is_scheduled_delivery_job(job) -> bool:
    kind = str(getattr(job, "kind", "") or "").strip()
    metadata = dict(getattr(job, "meta", {}) or {})
    template = dict(getattr(job, "run_template", {}) or {})
    return kind == "scheduled_delivery" or (
        kind == "scheduled_workflow"
        and str(metadata.get("workflow_subtype") or template.get("workflow_subtype") or "").strip() == "delivery"
    )


def _explicit_false(value: Any) -> bool:
    if value is False:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"false", "0", "no", "off"}
    return False


def _normalize_workflow_output_policy(output: dict[str, Any]) -> dict[str, Any]:
    if _explicit_false(output.get("persist_message", True)):
        raise ValueError("Scheduled Workflow assistant output must be persisted as a MessageService assistant message.")
    create_thread = not _explicit_false(output.get("create_thread", True))
    thread_id = str(output.get("thread_id") or "").strip()
    session_id = str(output.get("session_id") or "").strip()
    if not create_thread and not (thread_id or session_id):
        raise ValueError("create_thread=false requires an existing thread_id or session_id.")
    return {
        "persist_message": True,
        "create_thread": create_thread,
        "thread_id": thread_id,
        "session_id": session_id,
        "output_kinds": _string_list(output.get("output_kinds")) or ["assistant_message"],
    }


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

    def _trigger_config(
        self,
        trigger_config: dict[str, Any] | None,
        interval_seconds: Any,
        *,
        trigger_type: str = "",
        fallback_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = dict(trigger_config or {})
        interval = _positive_int(interval_seconds)
        if interval is not None:
            config["type"] = "interval"
            config["interval_seconds"] = interval
        kind = str(trigger_type or config.get("type") or (fallback_config or {}).get("type") or "").strip().lower()
        if kind == "daily":
            return normalize_daily_trigger_config(config, fallback_config=fallback_config)
        return config

    def _job_or_raise(self, job_id: str):
        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id is required.")
        job = self._domain().services.scheduler.get_job(normalized)
        if job is None:
            raise ValueError(f"Unknown scheduled job: {normalized}")
        return job

    def _current_actor(self):
        domain = self._domain()
        principal = getattr(domain, "principal", None)
        principal_key = str(getattr(principal, "principal_key", "") or "self").strip() or "self"
        actor = domain.services.actor.get_by_actor_id(f"user:{principal_key}")
        if actor is None:
            actor = domain.services.actor.ensure_actor(
                actor_id=f"user:{principal_key}",
                actor_type="user",
                owner_user_id=principal_key,
                display_name=str(getattr(principal, "display_name", "") or principal_key),
                permission_profile_id="profile.default_user",
                metadata={"principal_key": principal_key},
            )
        return actor

    def _resolve_delivery_target(self, target: dict[str, Any] | None) -> tuple[Any | None, dict[str, Any] | None]:
        domain = self._domain()
        payload = dict(target or {})
        address_id = str(payload.get("address_id") or "").strip()
        if address_id:
            address = domain.services.endpoint_address.get_by_address_id(address_id)
            if address is None:
                raise ValueError(f"Unknown delivery address: {address_id}")
            return address, None
        actor_ref = str(payload.get("actor_ref") or "").strip().lower()
        provider_type = str(payload.get("provider_type") or "").strip().lower()
        alias = str(payload.get("alias") or "me").strip() or "me"
        if actor_ref in {"me", "self", "我"} and provider_type:
            actor = self._current_actor()
            preference = domain.services.actor_delivery_preference.get_default(
                actor_row_id=actor.id,
                provider_type=provider_type,
                alias=alias,
            )
            if preference is None:
                return None, {
                    "requires_binding": True,
                    "actor_ref": "me",
                    "provider_type": provider_type,
                    "alias": alias,
                    "message": "No default delivery preference is bound for this actor/provider.",
                }
            address = domain.services.endpoint_address.get_by_id(getattr(preference, "address_id", None))
            if address is None:
                return None, {
                    "requires_binding": True,
                    "actor_ref": "me",
                    "provider_type": provider_type,
                    "alias": alias,
                    "message": "The bound delivery address no longer exists.",
                }
            return address, None
        raise ValueError("target requires address_id or actor_ref=me with provider_type.")

    @staticmethod
    def _compact_address(address) -> dict[str, Any]:
        return {
            "address_id": str(getattr(address, "address_id", "") or ""),
            "provider_type": str(getattr(address, "provider_type", "") or ""),
            "address_type": str(getattr(address, "address_type", "") or ""),
            "external_ref": str(getattr(address, "external_ref", "") or ""),
            "display_name": str(getattr(address, "display_name", "") or ""),
            "status": str(getattr(address, "status", "") or "unknown"),
        }

    def _resolve_delivery_targets(
        self,
        targets: Any,
        *,
        delivery_policy: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
        if not isinstance(targets, list):
            return [], [], None
        policies: list[dict[str, Any]] = []
        compact_addresses: list[dict[str, Any]] = []
        base_policy = dict(delivery_policy or {})
        for item in targets:
            if not isinstance(item, dict):
                continue
            endpoint_id = str(item.get("endpoint_id") or "").strip()
            if endpoint_id:
                policies.append(
                    {
                        "endpoint_id": endpoint_id,
                        "message_type": str(item.get("message_type") or "message").strip() or "message",
                        "offline_policy": str(item.get("offline_policy") or base_policy.get("offline_policy") or "store_and_retry"),
                    }
                )
                continue
            address, binding_error = self._resolve_delivery_target(item)
            if address is None:
                return [], [], dict(binding_error or {})
            compact = self._compact_address(address)
            compact_addresses.append(compact)
            policies.append(
                {
                    "address_id": compact["address_id"],
                    "provider_type": compact["provider_type"],
                    "address_type": compact["address_type"],
                    "message_type": str(item.get("message_type") or "message").strip() or "message",
                    "offline_policy": str(item.get("offline_policy") or base_policy.get("offline_policy") or "store_and_retry"),
                }
            )
        return policies, compact_addresses, None

    @staticmethod
    def _workflow_tool_policy(tool_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(tool_policy or {})
        max_rounds_explicit = "max_rounds" in payload
        try:
            max_rounds = int(payload.get("max_rounds") or 0)
        except (TypeError, ValueError):
            max_rounds = 0
        return {
            "tool_bundle": _string_list(
                payload.get("tool_bundle")
                or [
                    "get_current_system_time",
                    "emit_progress_notice",
                    "search_knowledge",
                    "search_memory",
                    "search_web",
                    "read_web_page",
                    "remember_knowledge",
                    "summarize_text",
                    "organize_notes",
                    "extract_action_items",
                ]
            ),
            "mcp_servers": _string_list(payload.get("mcp_servers")),
            "preferred_tool_key": str(payload.get("preferred_tool_key") or "").strip(),
            "preferred_target_endpoint_ids": _string_list(payload.get("preferred_target_endpoint_ids")),
            "preferred_endpoint_provider_types": _string_list(payload.get("preferred_endpoint_provider_types")),
            "tool_target_routing_policy": str(payload.get("tool_target_routing_policy") or "balanced").strip() or "balanced",
            "max_rounds": max(max_rounds, 0),
            "max_rounds_explicit": max_rounds_explicit,
        }

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
        timezone: str | None = None,
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
            jobs = [_compact_job(job, include_details=False) for job in domain.services.scheduler.list_jobs()]
            return {"ok": True, "count": len(jobs), **_job_list_summary(jobs), "jobs": jobs}

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
                trigger_config=self._trigger_config(
                    trigger_config,
                    interval_seconds,
                    trigger_type=str(trigger_type or "interval").strip() or "interval",
                ),
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
                updates["trigger_config"] = self._trigger_config(
                    trigger_config,
                    interval_seconds,
                    trigger_type=str(getattr(existing, "trigger_type", "") or ""),
                    fallback_config=dict(getattr(existing, "trigger_config", {}) or {}),
                )
            if timezone not in (None, ""):
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

    async def create_scheduled_workflow(
        self,
        name: str,
        schedule: dict[str, Any],
        instruction: str,
        timezone: str = "Asia/Shanghai",
        workflow_type: str = "assistant_run",
        mode: str = "automation",
        tool_policy: dict[str, Any] | None = None,
        output_policy: dict[str, Any] | None = None,
        workspace_id: str = "personal",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        text = str(instruction or "").strip()
        if not text:
            raise ValueError("instruction is required.")
        workflow_kind = str(workflow_type or "assistant_run").strip() or "assistant_run"
        if workflow_kind not in {"assistant_run", "tool_workflow", "external_workflow"}:
            raise ValueError("workflow_type must be assistant_run, tool_workflow, or external_workflow.")
        workspace = self._workspace_row(workspace_id or "personal")
        if workspace is None:
            raise ValueError("workspace_id is required.")
        trigger_type, trigger_config, tz = _normalize_schedule(schedule, timezone_name=timezone)
        tool_policy_payload = self._workflow_tool_policy(tool_policy)
        output = dict(output_policy or {})
        raw_delivery_targets = output.get("delivery_targets")
        if raw_delivery_targets is None:
            raw_delivery_targets = output.get("targets")
        target_policies, compact_targets, binding_error = self._resolve_delivery_targets(
            raw_delivery_targets,
            delivery_policy=output.get("delivery_policy") if isinstance(output.get("delivery_policy"), dict) else {},
        )
        if binding_error is not None:
            return {"ok": False, **binding_error}
        output_settings = _normalize_workflow_output_policy(output)
        job = self._domain().services.scheduler.create_job(
            kind="scheduled_workflow",
            name=str(name or text[:60] or "Scheduled workflow").strip(),
            workspace_id=workspace.id,
            enabled=bool(enabled),
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            timezone=tz,
            action_ref="core.workflow.scheduled_workflow",
            run_template={
                "schema": "meetyou.scheduler.workflow.v1",
                "workflow_type": workflow_kind,
                "workflow_subtype": str(output.get("workflow_subtype") or "").strip(),
                "mode": str(mode or "automation").strip() or "automation",
                "prompt": text,
                "instruction": text,
                "generation_policy": "generate_at_fire_time",
                "tool_bundle": tool_policy_payload["tool_bundle"],
                "mcp_servers": tool_policy_payload["mcp_servers"],
                "preferred_tool_key": tool_policy_payload["preferred_tool_key"],
                "preferred_target_endpoint_ids": tool_policy_payload["preferred_target_endpoint_ids"],
                "preferred_endpoint_provider_types": tool_policy_payload["preferred_endpoint_provider_types"],
                "tool_target_routing_policy": tool_policy_payload["tool_target_routing_policy"],
                "output_policy": {
                    "persist_message": output_settings["persist_message"],
                    "create_thread": output_settings["create_thread"],
                    "delivery_targets": compact_targets,
                    "output_kinds": output_settings["output_kinds"],
                },
                "max_rounds": tool_policy_payload["max_rounds"],
                "max_rounds_explicit": tool_policy_payload["max_rounds_explicit"],
                "workspace_id": str(getattr(workspace, "workspace_id", "") or workspace_id or "personal"),
                "thread_id": output_settings["thread_id"],
                "session_id": output_settings["session_id"],
                "thread_title": str(name or "Scheduled workflow"),
            },
            delivery_policy={
                **(dict(output.get("delivery_policy") or {}) if isinstance(output.get("delivery_policy"), dict) else {}),
                "thread_id": output_settings["thread_id"],
                "session_id": output_settings["session_id"],
                "create_thread": output_settings["create_thread"],
                "targets": target_policies,
            },
            concurrency_policy={"mode": "skip_if_running"},
            misfire_policy={"mode": "run_once"},
            metadata={
                "created_by_tool": "create_scheduled_workflow",
                "workflow_type": workflow_kind,
                "workflow_protocol": "meetyou.scheduler.workflow.v1",
                **dict(metadata or {}),
            },
        )
        return {
            "ok": True,
            "job": _compact_job(job),
            "workflow": {
                "workflow_type": workflow_kind,
                "schedule": {"trigger_type": trigger_type, "trigger_config": trigger_config, "timezone": tz},
                "output_policy": dict(job.run_template.get("output_policy") or {}),
            },
            "delivery_targets": compact_targets,
        }

    async def create_scheduled_delivery(
        self,
        name: str,
        schedule: dict[str, Any],
        target: dict[str, Any],
        instruction: str,
        timezone: str = "Asia/Shanghai",
        generation_policy: str = "generate_at_fire_time",
        delivery_policy: dict[str, Any] | None = None,
        workspace_id: str = "personal",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        text = str(instruction or "").strip()
        if not text:
            raise ValueError("instruction is required.")
        payload = await self.create_scheduled_workflow(
            name=name,
            schedule=schedule,
            instruction=text,
            timezone=timezone,
            workflow_type="assistant_run",
            mode="automation",
            tool_policy={
                "tool_bundle": ["get_current_system_time", "emit_progress_notice"],
                "max_rounds": 0,
            },
            output_policy={
                "workflow_subtype": "delivery",
                "delivery_targets": [dict(target or {})],
                "delivery_policy": dict(delivery_policy or {}),
                "output_kinds": ["assistant_message", "delivery.message"],
            },
            workspace_id=workspace_id,
            enabled=enabled,
            metadata={
                **dict(metadata or {}),
                "created_by_tool": "create_scheduled_delivery",
                "workflow_subtype": "delivery",
                "generation_policy": str(generation_policy or "generate_at_fire_time"),
            },
        )
        if not payload.get("ok"):
            return payload
        job_id = str(payload.get("job", {}).get("job_id") or "")
        job = self._domain().services.scheduler.get_job(job_id)
        return {
            "ok": True,
            "job": _compact_job(job),
            "target": (payload.get("delivery_targets") or [{}])[0],
            "generation_policy": str(generation_policy or "generate_at_fire_time"),
        }

    async def manage_scheduled_workflows(
        self,
        action: str = "list",
        job_id: str = "",
        enabled: bool | None = None,
        schedule: dict[str, Any] | None = None,
        timezone: str = "",
        instruction: str = "",
        tool_policy: dict[str, Any] | None = None,
        output_policy: dict[str, Any] | None = None,
        workspace_id: str = "personal",
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        normalized_action = str(action or "list").strip().lower()
        domain = self._domain()
        if normalized_action == "list":
            jobs = [
                _compact_job(job, include_details=False)
                for job in domain.services.scheduler.list_jobs()
                if str(getattr(job, "kind", "") or "") == "scheduled_workflow"
            ]
            return {"ok": True, "count": len(jobs), **_job_list_summary(jobs), "jobs": jobs}
        job = self._job_or_raise(job_id)
        if str(getattr(job, "kind", "") or "") != "scheduled_workflow":
            raise ValueError(f"Scheduled job is not a scheduled_workflow: {job_id}")
        if normalized_action == "detail":
            return {"ok": True, "job": _compact_job(job)}
        if normalized_action in {"enable", "disable"}:
            row = domain.services.scheduler.set_enabled(job_id=job.job_id, enabled=normalized_action == "enable")
            return {"ok": True, "job": _compact_job(row)}
        if normalized_action == "delete":
            deleted = domain.services.scheduler.delete_job(job_id=job.job_id)
            return {"ok": True, "job_id": job.job_id, "deleted": bool(deleted)}
        if normalized_action == "trigger":
            return await self.manage_scheduled_jobs(action="trigger", job_id=job.job_id, workspace_id=workspace_id)
        if normalized_action == "update":
            updates: dict[str, Any] = {}
            if enabled is not None:
                updates["enabled"] = bool(enabled)
            if schedule is not None:
                trigger_type, trigger_config, tz = _normalize_schedule(
                    schedule,
                    timezone_name=timezone or getattr(job, "timezone", "UTC"),
                    fallback_config=dict(getattr(job, "trigger_config", {}) or {}),
                )
                updates["trigger_type"] = trigger_type
                updates["trigger_config"] = trigger_config
                updates["timezone"] = tz
                updates["action_ref"] = "core.workflow.scheduled_workflow"
            template = dict(getattr(job, "run_template", {}) or {})
            if instruction:
                template["prompt"] = str(instruction or "").strip()
                template["instruction"] = str(instruction or "").strip()
            if _non_empty_dict(tool_policy):
                normalized_policy = self._workflow_tool_policy(tool_policy)
                template.update(
                    {
                        "tool_bundle": normalized_policy["tool_bundle"],
                        "mcp_servers": normalized_policy["mcp_servers"],
                        "preferred_tool_key": normalized_policy["preferred_tool_key"],
                        "preferred_target_endpoint_ids": normalized_policy["preferred_target_endpoint_ids"],
                        "preferred_endpoint_provider_types": normalized_policy["preferred_endpoint_provider_types"],
                        "tool_target_routing_policy": normalized_policy["tool_target_routing_policy"],
                        "max_rounds": normalized_policy["max_rounds"],
                        "max_rounds_explicit": normalized_policy["max_rounds_explicit"],
                    }
                )
            if _non_empty_dict(output_policy):
                output = dict(output_policy or {})
                output_settings = _normalize_workflow_output_policy(output)
                raw_targets = output.get("delivery_targets")
                if raw_targets is None:
                    raw_targets = output.get("targets")
                target_policies, compact_targets, binding_error = self._resolve_delivery_targets(
                    raw_targets,
                    delivery_policy=output.get("delivery_policy") if isinstance(output.get("delivery_policy"), dict) else {},
                )
                if binding_error is not None:
                    return {"ok": False, **binding_error}
                template["output_policy"] = {
                    "persist_message": output_settings["persist_message"],
                    "create_thread": output_settings["create_thread"],
                    "delivery_targets": compact_targets,
                    "output_kinds": output_settings["output_kinds"],
                }
                policy = {
                    **(dict(output.get("delivery_policy") or {}) if isinstance(output.get("delivery_policy"), dict) else {}),
                    "thread_id": output_settings["thread_id"],
                    "session_id": output_settings["session_id"],
                    "create_thread": output_settings["create_thread"],
                    "targets": target_policies,
                }
                updates["delivery_policy"] = policy
            if template != dict(getattr(job, "run_template", {}) or {}):
                updates["run_template"] = template
            if not updates:
                raise ValueError("update requires at least one mutable field.")
            row = domain.services.scheduler.update_job(job_id=job.job_id, **updates)
            return {"ok": True, "job": _compact_job(row)}
        raise ValueError("action must be list, detail, update, enable, disable, delete, or trigger.")

    async def manage_scheduled_deliveries(
        self,
        action: str = "list",
        job_id: str = "",
        enabled: bool | None = None,
        schedule: dict[str, Any] | None = None,
        timezone: str = "",
        instruction: str = "",
        target: dict[str, Any] | None = None,
        delivery_policy: dict[str, Any] | None = None,
        workspace_id: str = "personal",
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        normalized_action = str(action or "list").strip().lower()
        domain = self._domain()
        if normalized_action == "list":
            jobs = [_compact_job(job, include_details=False) for job in domain.services.scheduler.list_jobs() if _is_scheduled_delivery_job(job)]
            return {"ok": True, "count": len(jobs), **_job_list_summary(jobs), "jobs": jobs}
        job = self._job_or_raise(job_id)
        if not _is_scheduled_delivery_job(job):
            raise ValueError(f"Scheduled job is not a scheduled delivery workflow: {job_id}")
        if normalized_action == "detail":
            return {"ok": True, "job": _compact_job(job)}
        if normalized_action in {"enable", "disable"}:
            row = domain.services.scheduler.set_enabled(job_id=job.job_id, enabled=normalized_action == "enable")
            return {"ok": True, "job": _compact_job(row)}
        if normalized_action == "delete":
            deleted = domain.services.scheduler.delete_job(job_id=job.job_id)
            return {"ok": True, "job_id": job.job_id, "deleted": bool(deleted)}
        if normalized_action == "trigger":
            return await self.manage_scheduled_jobs(action="trigger", job_id=job.job_id, workspace_id=workspace_id)
        if normalized_action == "update":
            updates: dict[str, Any] = {}
            if enabled is not None:
                updates["enabled"] = bool(enabled)
            if schedule is not None:
                trigger_type, trigger_config, tz = _normalize_schedule(
                    schedule,
                    timezone_name=timezone or getattr(job, "timezone", "UTC"),
                    fallback_config=dict(getattr(job, "trigger_config", {}) or {}),
                )
                updates["trigger_type"] = trigger_type
                updates["trigger_config"] = trigger_config
                updates["timezone"] = tz
                updates["action_ref"] = "core.workflow.scheduled_workflow"
            if instruction:
                template = dict(getattr(job, "run_template", {}) or {})
                template["prompt"] = str(instruction or "").strip()
                template["instruction"] = str(instruction or "").strip()
                updates["run_template"] = template
            if _non_empty_dict(target):
                address, binding_error = self._resolve_delivery_target(target)
                if address is None:
                    return {"ok": False, **dict(binding_error or {})}
                policy = dict(getattr(job, "delivery_policy", {}) or {})
                policy["targets"] = [{
                    "address_id": str(getattr(address, "address_id", "") or ""),
                    "provider_type": str(getattr(address, "provider_type", "") or ""),
                    "address_type": str(getattr(address, "address_type", "") or ""),
                    "message_type": "message",
                    "offline_policy": str((delivery_policy or {}).get("offline_policy") or "store_and_retry"),
                }]
                updates["delivery_policy"] = policy
            elif _non_empty_dict(delivery_policy):
                policy = dict(getattr(job, "delivery_policy", {}) or {})
                policy.update(dict(delivery_policy or {}))
                updates["delivery_policy"] = policy
            if not updates:
                raise ValueError("update requires at least one mutable field.")
            row = domain.services.scheduler.update_job(job_id=job.job_id, **updates)
            return {"ok": True, "job": _compact_job(row)}
        raise ValueError("action must be list, detail, update, enable, disable, delete, or trigger.")
