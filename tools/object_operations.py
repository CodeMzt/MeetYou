from __future__ import annotations

from typing import Any


def build_object_operation_payload(
    *,
    action: str,
    object_type: str,
    status: str,
    objects: list[dict[str, Any]] | None = None,
    summary: str = "",
    requires_confirmation: bool = False,
    confirmation: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    error: dict[str, Any] | None = None,
    filters_applied: dict[str, Any] | None = None,
    next_action_hint: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "kind": "object_operation",
        "action": str(action or "").strip().lower(),
        "object_type": str(object_type or "").strip(),
        "status": str(status or "").strip().lower() or "success",
        "objects": [dict(item) for item in (objects or []) if isinstance(item, dict)],
        "object_count": len(objects or []),
        "summary": str(summary or "").strip(),
        "requires_confirmation": bool(requires_confirmation),
        "confirmation": dict(confirmation or {}),
        "candidates": [dict(item) for item in (candidates or []) if isinstance(item, dict)],
        "error": dict(error or {}),
        "filters_applied": dict(filters_applied or {}),
        "next_action_hint": str(next_action_hint or "").strip(),
    }
    if extra:
        for key, value in dict(extra).items():
            if key not in payload:
                payload[key] = value
    return payload


def redacted_object_debug_entry(entry: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(entry or {})
    objects = []
    for item in payload.get("objects", []):
        if not isinstance(item, dict):
            continue
        sanitized = dict(item)
        for key in ("content", "canonical_text", "fact_value", "full_content"):
            sanitized.pop(key, None)
        if sanitized.get("object_type") == "memory":
            preview = str(sanitized.get("preview") or "").strip()
            if preview:
                sanitized["preview"] = preview[:72]
        objects.append(sanitized)
    candidates = []
    for item in payload.get("candidates", []):
        if not isinstance(item, dict):
            continue
        sanitized = dict(item)
        for key in ("content", "canonical_text", "fact_value", "full_content"):
            sanitized.pop(key, None)
        if sanitized.get("object_type") == "memory":
            preview = str(sanitized.get("preview") or "").strip()
            if preview:
                sanitized["preview"] = preview[:72]
        candidates.append(sanitized)
    error = dict(payload.get("error") or {})
    details = dict(error.get("details") or {})
    for key in ("content", "memory_text", "full_content"):
        details.pop(key, None)
    if details:
        error["details"] = details
    payload["objects"] = objects
    payload["object_count"] = len(objects)
    payload["candidates"] = candidates
    payload["error"] = error
    return payload
