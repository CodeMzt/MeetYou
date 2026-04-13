from __future__ import annotations

from typing import Any


def build_system_issue_candidates(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if payload.get("scheduler_stalled"):
        issues.append("scheduler_stalled")
    if payload.get("housekeeping_stalled"):
        issues.append("housekeeping_stalled")
    if payload.get("pending_consolidation_stale"):
        issues.append("pending_consolidation_stale")
    if str(payload.get("last_housekeeping_error") or "").strip():
        issues.append("housekeeping_error")
    if payload.get("repeated_failure_tasks"):
        issues.append("repeated_task_failures")
    return issues


def build_temporal_attention_candidates(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if int(payload.get("pending_delivery_count") or 0) > 0:
        issues.append("pending_redelivery")
    if int(payload.get("awaiting_completion_count") or 0) > 0:
        issues.append("awaiting_completion")
    if int(payload.get("run_succeeded_pending_completion_count") or 0) > 0:
        issues.append("completion_confirmation_pending")
    if int(payload.get("overdue_task_count") or 0) > 0:
        issues.append("overdue_follow_up")
    return issues


def build_system_issue_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    issues = build_system_issue_candidates(payload)
    return {
        "scheduler_stalled": bool(payload.get("scheduler_stalled")),
        "housekeeping_stalled": bool(payload.get("housekeeping_stalled")),
        "pending_consolidation_stale": bool(payload.get("pending_consolidation_stale")),
        "last_housekeeping_error": str(payload.get("last_housekeeping_error") or ""),
        "repeated_failure_task_count": len(payload.get("repeated_failure_tasks") or []),
        "system_issue_candidates": issues,
    }


def build_temporal_attention_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    issues = build_temporal_attention_candidates(payload)
    return {
        "pending_redelivery_count": int(payload.get("pending_delivery_count") or 0),
        "awaiting_completion_count": int(payload.get("awaiting_completion_count") or 0),
        "run_succeeded_pending_completion_count": int(payload.get("run_succeeded_pending_completion_count") or 0),
        "overdue_task_count": int(payload.get("overdue_task_count") or 0),
        "temporal_attention_candidates": issues,
    }
