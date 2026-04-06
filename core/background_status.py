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
