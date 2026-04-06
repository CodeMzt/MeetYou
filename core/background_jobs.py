from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

JOB_STATUS_VALUES = {
    "idle",
    "queued",
    "running",
    "succeeded",
    "failed",
    "retry_waiting",
    "awaiting_delivery",
    "completed",
    "stalled",
    "not_applicable",
}
JOB_FAILURE_CATEGORY_VALUES = {
    "retryable",
    "non_retryable",
    "manual_intervention",
    "delivery",
}
JOB_DELIVERY_STATE_VALUES = {
    "not_applicable",
    "pending",
    "delivered",
    "pending_redelivery",
    "suppressed",
    "failed",
}


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def dt_to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utcnow_iso() -> str:
    return dt_to_iso(datetime.now(timezone.utc))


def iso_to_dt(value: Any) -> datetime | None:
    text = normalize_text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def failure_payload(
    *,
    category: Any = "retryable",
    retryable: Any = None,
    code: Any = "job_failure",
    message: Any = "",
    at: Any = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_category = normalize_text(category).lower() or "retryable"
    if normalized_category not in JOB_FAILURE_CATEGORY_VALUES:
        normalized_category = "retryable"
    if retryable is None:
        normalized_retryable = normalized_category in {"retryable", "delivery"}
    else:
        normalized_retryable = bool(retryable)
    return {
        "category": normalized_category,
        "retryable": normalized_retryable,
        "code": normalize_text(code) or "job_failure",
        "message": normalize_text(message),
        "at": normalize_text(at) or utcnow_iso(),
        "details": copy.deepcopy(details) if isinstance(details, dict) else {},
    }


def normalize_failure(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    message = normalize_text(payload.get("message"))
    code = normalize_text(payload.get("code"))
    category = normalize_text(payload.get("category"))
    if not any((message, code, category)):
        return None
    return failure_payload(
        category=payload.get("category"),
        retryable=payload.get("retryable"),
        code=payload.get("code") or "job_failure",
        message=payload.get("message"),
        at=payload.get("at"),
        details=payload.get("details") if isinstance(payload.get("details"), dict) else {},
    )


def delivery_payload(
    *,
    state: Any = "not_applicable",
    delivered: Any = None,
    channel: Any = "",
    message: Any = "",
    event_id: Any = "",
    source_event_id: Any = "",
    at: Any = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_state = normalize_text(state).lower() or "not_applicable"
    if normalized_state not in JOB_DELIVERY_STATE_VALUES:
        normalized_state = "not_applicable"
    if delivered is None:
        normalized_delivered = normalized_state == "delivered"
    else:
        normalized_delivered = bool(delivered)
    return {
        "state": normalized_state,
        "delivered": normalized_delivered,
        "channel": normalize_text(channel),
        "message": normalize_text(message),
        "event_id": normalize_text(event_id) or None,
        "source_event_id": normalize_text(source_event_id) or None,
        "at": normalize_text(at) or utcnow_iso(),
        "details": copy.deepcopy(details) if isinstance(details, dict) else {},
    }


def normalize_delivery(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return delivery_payload()
    return delivery_payload(
        state=payload.get("state"),
        delivered=payload.get("delivered"),
        channel=payload.get("channel"),
        message=payload.get("message"),
        event_id=payload.get("event_id"),
        source_event_id=payload.get("source_event_id"),
        at=payload.get("at"),
        details=payload.get("details") if isinstance(payload.get("details"), dict) else {},
    )


def default_job_record(
    *,
    kind: str,
    name: str,
    max_retries: int = 0,
    status_source: str = "",
) -> dict[str, Any]:
    return {
        "name": normalize_text(name),
        "kind": normalize_text(kind),
        "status": "idle",
        "attempt_count": 0,
        "retry_count": 0,
        "max_retries": max(int(max_retries or 0), 0),
        "next_retry_at": None,
        "last_started_at": None,
        "last_finished_at": None,
        "last_success_at": None,
        "last_runtime_source": normalize_text(status_source),
        "status_source": normalize_text(status_source),
        "last_result": {},
        "last_failure": None,
        "last_delivery": delivery_payload(),
        "metadata": {},
    }


def normalize_job_record(
    payload: Any,
    *,
    kind: str,
    name: str,
    max_retries: int = 0,
    status_source: str = "",
) -> dict[str, Any]:
    normalized = default_job_record(
        kind=kind,
        name=name,
        max_retries=max_retries,
        status_source=status_source,
    )
    if not isinstance(payload, dict):
        return normalized
    merged = copy.deepcopy(payload)
    merged_name = normalize_text(merged.get("name")) or normalized["name"]
    merged_kind = normalize_text(merged.get("kind")) or normalized["kind"]
    merged_status = normalize_text(merged.get("status")).lower() or normalized["status"]
    if merged_status not in JOB_STATUS_VALUES:
        merged_status = normalized["status"]
    normalized.update(
        {
            "name": merged_name,
            "kind": merged_kind,
            "status": merged_status,
            "attempt_count": max(int(merged.get("attempt_count", 0) or 0), 0),
            "retry_count": max(int(merged.get("retry_count", 0) or 0), 0),
            "max_retries": max(int(merged.get("max_retries", normalized["max_retries"]) or 0), 0),
            "next_retry_at": normalize_text(merged.get("next_retry_at")) or None,
            "last_started_at": normalize_text(merged.get("last_started_at")) or None,
            "last_finished_at": normalize_text(merged.get("last_finished_at")) or None,
            "last_success_at": normalize_text(merged.get("last_success_at")) or None,
            "last_runtime_source": normalize_text(merged.get("last_runtime_source")) or normalized["last_runtime_source"],
            "status_source": normalize_text(merged.get("status_source")) or normalized["status_source"],
            "last_result": copy.deepcopy(merged.get("last_result")) if isinstance(merged.get("last_result"), dict) else {},
            "last_failure": normalize_failure(merged.get("last_failure")),
            "last_delivery": normalize_delivery(merged.get("last_delivery")),
            "metadata": copy.deepcopy(merged.get("metadata")) if isinstance(merged.get("metadata"), dict) else {},
        }
    )
    return normalized
