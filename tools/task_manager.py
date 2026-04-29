from __future__ import annotations

import copy
import json
import os
import re
import time
from calendar import monthrange
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.background_jobs import (
    default_job_record,
    delivery_payload,
    failure_payload,
    normalize_delivery,
    normalize_failure,
    normalize_job_record,
)
from core.persistence import atomic_write_json, load_json_with_recovery
from core.repositories import TaskRepository
from core.runtime_context import get_event_context
from core.tool_runtime.models import ToolCallResult, ToolErrorCategory, ToolSourceType
from tools.object_operations import build_object_operation_payload
from tools.system_tools import request_user_confirmation

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore[assignment]

_VALID_TASK_STATUSES = {"open", "blocked", "done"}
_VALID_SCHEDULE_KINDS = {"none", "once", "recurring"}
_VALID_NOTIFY_POLICIES = {"on_due", "on_completion", "silent"}
_VALID_TASK_DOMAINS = {"user_todo", "assistant_schedule"}
_DEFAULT_LIST_LIMIT = 8
_MAX_LIST_LIMIT = 20
_DEFAULT_TIMEZONE = "UTC"
_DEFAULT_LEASE_SECONDS = 120
_DEFAULT_FAILURE_BACKOFF_SECONDS = 900
_DEFAULT_JOB_MAX_RETRIES = 3
_URGENT_DUE_WINDOW = timedelta(hours=6)
_BACKGROUND_DUE_LIST_LIMIT = 3
_REPEATED_FAILURE_THRESHOLD = 2
_STORE_LOCK_POLL_SECONDS = 0.05
_STORE_LOCK_TIMEOUT_SECONDS = 5.0
_STALE_STORE_LOCK_SECONDS = 30.0
_TASK_SCHEMA_VERSION = "2"
_UNSET = object()
_SPACE_RE = re.compile(r"\s+")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T\s]\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?$"
)
_CN_DAILY_RE = re.compile(
    r"(?:每(?:天|日)|每天)(?:凌晨|早上|上午|中午|下午|傍晚|晚上)?\s*(\d{1,2})(?:[:：点时](\d{1,2}))?"
)
_CN_WEEKLY_RE = re.compile(
    r"每(?:周|星期)\s*([一二三四五六日天1-7])(?:凌晨|早上|上午|中午|下午|傍晚|晚上)?\s*(\d{1,2})(?:[:：点时](\d{1,2}))?"
)
_CN_MONTHLY_RE = re.compile(
    r"每月\s*(\d{1,2})[号日]?(?:凌晨|早上|上午|中午|下午|傍晚|晚上)?\s*(\d{1,2})(?:[:：点时](\d{1,2}))?"
)
_EN_DAILY_RE = re.compile(r"(?:every day|daily)(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?", re.IGNORECASE)
_EN_WEEKLY_RE = re.compile(
    r"(?:every|each)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?",
    re.IGNORECASE,
)
_AUTO_RUN_HINTS = ("自动", "auto", "automatically", "scheduled workflow", "定时执行")
_TIMEZONE_ALIASES = {
    "asia/shanghai": "Asia/Shanghai",
    "utc": "UTC",
    "z": "UTC",
}
_WEEKDAY_MAP = {
    "1": 0,
    "一": 0,
    "monday": 0,
    "2": 1,
    "二": 1,
    "tuesday": 1,
    "3": 2,
    "三": 2,
    "wednesday": 2,
    "4": 3,
    "四": 3,
    "thursday": 3,
    "5": 4,
    "五": 4,
    "friday": 4,
    "6": 5,
    "六": 5,
    "saturday": 5,
    "7": 6,
    "日": 6,
    "天": 6,
    "sunday": 6,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utcnow_iso() -> str:
    return _dt_to_iso(_utcnow())


def _iso_to_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
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


def _normalize_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip())


def _normalize_status(value: Any, *, default: str = "open") -> str:
    normalized = str(value or default).strip().lower() or default
    if normalized not in _VALID_TASK_STATUSES:
        raise ValueError("task_status must be one of: open, blocked, done.")
    return normalized


def _default_task_domain(schedule_kind: Any) -> str:
    normalized_schedule_kind = _normalize_schedule_kind(schedule_kind or "none")
    return "assistant_schedule" if normalized_schedule_kind in {"once", "recurring"} else "user_todo"


def _normalize_task_domain(value: Any, *, schedule_kind: Any = "none") -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        normalized = _default_task_domain(schedule_kind)
    if normalized not in _VALID_TASK_DOMAINS:
        raise ValueError("task_domain must be one of: user_todo, assistant_schedule.")
    return normalized


def _normalize_schedule_kind(value: Any, *, default: str = "none") -> str:
    normalized = str(value or default).strip().lower() or default
    if normalized not in _VALID_SCHEDULE_KINDS:
        raise ValueError("schedule_kind must be one of: none, once, recurring.")
    return normalized


def _normalize_notify_policy(value: Any, *, default: str) -> str:
    normalized = str(value or default).strip().lower() or default
    if normalized not in _VALID_NOTIFY_POLICIES:
        raise ValueError("notify_policy must be one of: on_due, on_completion, silent.")
    return normalized


def _normalize_bool(value: Any, *, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    if default is not None:
        return default
    raise ValueError("auto_run must be a boolean.")


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = _normalize_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _normalize_routing_policy(value: Any, *, default: str = "balanced") -> str:
    normalized = _normalize_text(value or default).lower() or default
    if normalized not in {"balanced", "prefer_origin_endpoint", "strict_preferred_endpoint"}:
        return default
    return normalized


def _cycle_key(schedule_kind: Any, cycle_start_at: Any, cycle_end_at: Any = None, *, fallback: Any = "") -> str:
    normalized_schedule_kind = _normalize_schedule_kind(schedule_kind or "none")
    start_text = _normalize_text(cycle_start_at)
    end_text = _normalize_text(cycle_end_at)
    fallback_text = _normalize_text(fallback)
    if normalized_schedule_kind == "none":
        return ""
    if start_text and end_text:
        return f"{normalized_schedule_kind}:{start_text}->{end_text}"
    if start_text:
        return f"{normalized_schedule_kind}:{start_text}"
    if fallback_text:
        return f"{normalized_schedule_kind}:upcoming:{fallback_text}"
    return normalized_schedule_kind


def _cycle_event_id(task_key: Any, cycle_key: Any, event_kind: Any) -> str:
    normalized_task_key = _normalize_text(task_key)
    normalized_cycle_key = _normalize_text(cycle_key)
    normalized_event_kind = _normalize_text(event_kind)
    if not (normalized_task_key and normalized_cycle_key and normalized_event_kind):
        return ""
    return f"{normalized_task_key}:{normalized_cycle_key}:{normalized_event_kind}"


def _pending_delivery_identity(record: dict[str, Any], payload: dict[str, Any]) -> str:
    source_event_id = _normalize_text(payload.get("source_event_id"))
    if source_event_id:
        return source_event_id
    event_id = _normalize_text(payload.get("event_id"))
    if event_id:
        return event_id
    cycle_key = _normalize_text(payload.get("cycle_key"))
    kind = _normalize_text(payload.get("kind")) or "task_update"
    cycle_event_id = _cycle_event_id(record.get("task_key"), cycle_key, kind)
    if cycle_event_id:
        return cycle_event_id
    task_key = _normalize_text(record.get("task_key"))
    if task_key:
        return f"{task_key}:{kind}"
    return kind


def _slugify(value: str) -> str:
    lowered = re.sub(r"\s+", "-", str(value or "").strip().lower())
    lowered = _SLUG_RE.sub("-", lowered).strip("-")
    return lowered or "task"


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ""
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def _serialize_jsonish(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    if value in ("", None):
        return None
    return value


def _looks_like_match(record: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystacks = [
        _normalize_text(record.get("task_key")),
        _normalize_text(record.get("content")),
        _normalize_text(record.get("project")),
        _normalize_text(record.get("deadline")),
        _normalize_text(record.get("due_at")),
        _normalize_text(record.get("next_run_at")),
        _normalize_text(record.get("job_prompt")),
    ]
    lowered = query.lower()
    return any(lowered in item.lower() for item in haystacks if item)


def _resolve_timezone_name(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return _DEFAULT_TIMEZONE
    aliased = _TIMEZONE_ALIASES.get(normalized.lower(), normalized)
    if ZoneInfo is None:
        return aliased
    try:
        ZoneInfo(aliased)
        return aliased
    except Exception:
        return _DEFAULT_TIMEZONE


def _timezone_for_name(name: str):
    resolved = _resolve_timezone_name(name)
    if resolved == "UTC" or ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(resolved)
    except Exception:
        return timezone.utc


def _clamp_hour(value: Any, default: int = 9) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(parsed, 23))


def _clamp_minute(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(parsed, 59))


def _parse_iso_or_date(value: Any, timezone_name: str) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    if _ISO_DATETIME_RE.match(text):
        parsed = _iso_to_dt(text)
        return _dt_to_iso(parsed) if parsed is not None else None
    if _ISO_DATE_RE.match(text):
        date_value = datetime.strptime(text, "%Y-%m-%d")
        localized = datetime(
            date_value.year,
            date_value.month,
            date_value.day,
            9,
            0,
            tzinfo=_timezone_for_name(timezone_name),
        )
        return _dt_to_iso(localized)
    return None


def _parse_bounded_int(
    value: Any,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
    default: int | None = None,
    required: bool = False,
) -> int:
    if value in (None, ""):
        if required:
            raise ValueError(f"{field_name} is required.")
        if default is None:
            raise ValueError(f"{field_name} is required.")
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer.") from None
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}.")
    return parsed


def _recurrence_from_text(text: str) -> dict[str, Any] | None:
    normalized = _normalize_text(text).lower()
    if not normalized:
        return None

    match = _CN_DAILY_RE.search(normalized)
    if match:
        return {
            "freq": "daily",
            "hour": _clamp_hour(match.group(1), 9),
            "minute": _clamp_minute(match.group(2), 0),
        }

    match = _EN_DAILY_RE.search(normalized)
    if match:
        return {
            "freq": "daily",
            "hour": _clamp_hour(match.group(1), 9),
            "minute": _clamp_minute(match.group(2), 0),
        }

    match = _CN_WEEKLY_RE.search(normalized)
    if match:
        return {
            "freq": "weekly",
            "weekday": _WEEKDAY_MAP.get(match.group(1), 0),
            "hour": _clamp_hour(match.group(2), 9),
            "minute": _clamp_minute(match.group(3), 0),
        }

    match = _EN_WEEKLY_RE.search(normalized)
    if match:
        return {
            "freq": "weekly",
            "weekday": _WEEKDAY_MAP.get(match.group(1).lower(), 0),
            "hour": _clamp_hour(match.group(2), 9),
            "minute": _clamp_minute(match.group(3), 0),
        }

    match = _CN_MONTHLY_RE.search(normalized)
    if match:
        return {
            "freq": "monthly",
            "day": max(1, min(int(match.group(1)), 31)),
            "hour": _clamp_hour(match.group(2), 9),
            "minute": _clamp_minute(match.group(3), 0),
        }

    if "hourly" in normalized or "每小时" in normalized:
        return {"freq": "hourly", "minute": 0}

    return None


def _normalize_recurrence(value: Any) -> dict[str, Any] | None:
    raw = _maybe_json(value)
    if raw in ("", None):
        return None

    if isinstance(raw, str):
        parsed = _recurrence_from_text(raw)
        if parsed is None:
            raise ValueError("recurrence must be a supported string or object.")
        return parsed

    if not isinstance(raw, dict):
        raise ValueError("recurrence must be a string or object.")

    freq = str(raw.get("freq") or raw.get("kind") or "").strip().lower()
    if freq == "daily":
        return {
            "freq": "daily",
            "hour": _parse_bounded_int(
                raw.get("hour"),
                field_name="daily recurrence hour",
                minimum=0,
                maximum=23,
                required=True,
            ),
            "minute": _parse_bounded_int(
                raw.get("minute"),
                field_name="daily recurrence minute",
                minimum=0,
                maximum=59,
                default=0,
            ),
        }
    if freq == "weekly":
        weekday_raw = raw.get("weekday")
        if isinstance(weekday_raw, str):
            weekday = _WEEKDAY_MAP.get(weekday_raw.strip().lower())
        else:
            try:
                weekday = int(weekday_raw)
            except (TypeError, ValueError):
                weekday = None
        if weekday is None or weekday not in range(7):
            raise ValueError("weekly recurrence requires weekday from 0-6 or monday-sunday.")
        return {
            "freq": "weekly",
            "weekday": weekday,
            "hour": _parse_bounded_int(
                raw.get("hour"),
                field_name="weekly recurrence hour",
                minimum=0,
                maximum=23,
                required=True,
            ),
            "minute": _parse_bounded_int(
                raw.get("minute"),
                field_name="weekly recurrence minute",
                minimum=0,
                maximum=59,
                default=0,
            ),
        }
    if freq == "monthly":
        return {
            "freq": "monthly",
            "day": _parse_bounded_int(
                raw.get("day"),
                field_name="monthly recurrence day",
                minimum=1,
                maximum=31,
                required=True,
            ),
            "hour": _parse_bounded_int(
                raw.get("hour"),
                field_name="monthly recurrence hour",
                minimum=0,
                maximum=23,
                required=True,
            ),
            "minute": _parse_bounded_int(
                raw.get("minute"),
                field_name="monthly recurrence minute",
                minimum=0,
                maximum=59,
                default=0,
            ),
        }
    if freq == "hourly":
        return {
            "freq": "hourly",
            "minute": _parse_bounded_int(
                raw.get("minute"),
                field_name="hourly recurrence minute",
                minimum=0,
                maximum=59,
                default=0,
            ),
        }
    raise ValueError("recurrence freq must be one of: daily, weekly, monthly, hourly.")


def _month_shift(year: int, month: int, delta: int) -> tuple[int, int]:
    absolute = year * 12 + (month - 1) + delta
    return absolute // 12, absolute % 12 + 1


def _recurrence_occurrence_at_or_before(
    recurrence: dict[str, Any],
    timezone_name: str,
    *,
    reference: datetime,
) -> datetime | None:
    if not recurrence:
        return None

    zone = _timezone_for_name(timezone_name)
    local_reference = reference.astimezone(zone)
    freq = str(recurrence.get("freq") or "").strip().lower()

    if freq == "daily":
        hour = _clamp_hour(recurrence.get("hour"), 9)
        minute = _clamp_minute(recurrence.get("minute"), 0)
        candidate = local_reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > local_reference:
            candidate -= timedelta(days=1)
        return candidate.astimezone(timezone.utc)

    if freq == "weekly":
        weekday = int(recurrence.get("weekday", 0))
        hour = _clamp_hour(recurrence.get("hour"), 9)
        minute = _clamp_minute(recurrence.get("minute"), 0)
        days_back = (local_reference.weekday() - weekday) % 7
        candidate = local_reference.replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(days=days_back)
        if candidate > local_reference:
            candidate -= timedelta(days=7)
        return candidate.astimezone(timezone.utc)

    if freq == "monthly":
        day = int(recurrence.get("day", 1))
        hour = _clamp_hour(recurrence.get("hour"), 9)
        minute = _clamp_minute(recurrence.get("minute"), 0)
        year = local_reference.year
        month = local_reference.month
        max_day = monthrange(year, month)[1]
        candidate_day = max(1, min(day, max_day))
        candidate = local_reference.replace(day=candidate_day, hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > local_reference:
            year, month = _month_shift(year, month, -1)
            max_day = monthrange(year, month)[1]
            candidate = candidate.replace(year=year, month=month, day=max(1, min(day, max_day)))
        return candidate.astimezone(timezone.utc)

    if freq == "hourly":
        minute = _clamp_minute(recurrence.get("minute"), 0)
        candidate = local_reference.replace(minute=minute, second=0, microsecond=0)
        if candidate > local_reference:
            candidate -= timedelta(hours=1)
            candidate = candidate.replace(minute=minute, second=0, microsecond=0)
        return candidate.astimezone(timezone.utc)

    return None


def _next_run_from_recurrence(
    recurrence: dict[str, Any],
    timezone_name: str,
    *,
    now: datetime | None = None,
    inclusive: bool = False,
) -> str | None:
    if not recurrence:
        return None

    reference = now or _utcnow()
    zone = _timezone_for_name(timezone_name)
    local_reference = reference.astimezone(zone)
    freq = str(recurrence.get("freq") or "").strip().lower()

    if freq == "daily":
        hour = _clamp_hour(recurrence.get("hour"), 9)
        minute = _clamp_minute(recurrence.get("minute"), 0)
        candidate = local_reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < local_reference or (candidate == local_reference and not inclusive):
            candidate += timedelta(days=1)
        return _dt_to_iso(candidate)

    if freq == "weekly":
        weekday = int(recurrence.get("weekday", 0))
        hour = _clamp_hour(recurrence.get("hour"), 9)
        minute = _clamp_minute(recurrence.get("minute"), 0)
        days_ahead = (weekday - local_reference.weekday()) % 7
        candidate = local_reference.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
        if candidate < local_reference or (candidate == local_reference and not inclusive):
            candidate += timedelta(days=7)
        return _dt_to_iso(candidate)

    if freq == "monthly":
        day = int(recurrence.get("day", 1))
        hour = _clamp_hour(recurrence.get("hour"), 9)
        minute = _clamp_minute(recurrence.get("minute"), 0)
        year = local_reference.year
        month = local_reference.month
        max_day = monthrange(year, month)[1]
        candidate = local_reference.replace(
            day=max(1, min(day, max_day)),
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if candidate < local_reference or (candidate == local_reference and not inclusive):
            year, month = _month_shift(year, month, 1)
            max_day = monthrange(year, month)[1]
            candidate = candidate.replace(year=year, month=month, day=max(1, min(day, max_day)))
        return _dt_to_iso(candidate)

    if freq == "hourly":
        minute = _clamp_minute(recurrence.get("minute"), 0)
        candidate = local_reference.replace(minute=minute, second=0, microsecond=0)
        if candidate < local_reference or (candidate == local_reference and not inclusive):
            candidate += timedelta(hours=1)
            candidate = candidate.replace(minute=minute, second=0, microsecond=0)
        return _dt_to_iso(candidate)

    return None


def _timestamp_in_window(timestamp: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    if timestamp is None or start is None:
        return False
    if timestamp < start:
        return False
    if end is None:
        return True
    return timestamp < end


def _guess_auto_run(summary: str, job_prompt: str, schedule_kind: str) -> bool:
    text = f"{summary} {job_prompt}".lower()
    if schedule_kind == "none":
        return False
    return any(token in text for token in _AUTO_RUN_HINTS)


def _derive_schedule_from_text(summary: str, deadline: str, timezone_name: str) -> dict[str, Any]:
    recurrence = _recurrence_from_text(summary)
    if recurrence is not None:
        return {
            "schedule_kind": "recurring",
            "due_at": None,
            "recurrence": recurrence,
            "next_run_at": _next_run_from_recurrence(recurrence, timezone_name),
        }

    due_at = _parse_iso_or_date(deadline, timezone_name) or _parse_iso_or_date(summary, timezone_name)
    if due_at:
        return {
            "schedule_kind": "once",
            "due_at": due_at,
            "recurrence": None,
            "next_run_at": due_at,
        }

    return {
        "schedule_kind": "none",
        "due_at": None,
        "recurrence": None,
        "next_run_at": None,
    }


def _delivery_target_payload(session_id: str, source, explicit_target: Any | None = None) -> dict[str, Any] | None:
    target = explicit_target if isinstance(explicit_target, dict) else {}
    kind = str(target.get("kind") or "current_session").strip() or "current_session"
    target_id = str(target.get("id") or "").strip()
    source_kind = getattr(source, "kind", "") or (source.get("kind") if isinstance(source, dict) else "")
    source_id = getattr(source, "id", "") or (source.get("id") if isinstance(source, dict) else "")

    payload = {
        "kind": kind,
        "id": target_id,
        "session_id": str(session_id or "").strip(),
        "source_kind": str(source_kind or "").strip(),
        "source_id": str(source_id or "").strip(),
    }
    if not any(payload.values()):
        return None
    return payload


class TaskManager(TaskRepository):
    def __init__(self, memory, task_file_path: str = "", store_backend=None):
        self._memory = memory
        self._task_file_path_override = _normalize_text(task_file_path)
        self._store = self._empty_store()
        self._db_sync_callback = None
        self._store_backend = store_backend
        self._task_file_path = self._resolve_task_file_path()
        self._migrate_legacy_store(self._task_file_path)
        self._store = self._load_store()

    def _derive_task_file_path(self, memory_path: str | None = None) -> str:
        if memory_path is None:
            memory_path = getattr(self._memory, "_memory_file_path", "")
        memory_path = _normalize_text(memory_path)
        if not memory_path:
            return ""
        base_dir = os.path.dirname(memory_path) or "."
        filename = os.path.basename(memory_path)
        if filename.lower().endswith(".json"):
            stem = filename[:-5]
            if stem.endswith("_graph"):
                stem = stem[:-6]
            return os.path.join(base_dir, f"{stem}_tasks.json")
        return os.path.join(base_dir, "tasks.json")

    def _resolve_task_file_path(self) -> str:
        if self._task_file_path_override:
            return self._task_file_path_override
        return self._derive_task_file_path()

    def _empty_store(self) -> dict[str, Any]:
        return {
            "metadata": {
                "schema_version": _TASK_SCHEMA_VERSION,
                "revision": 0,
                "updated_at": _utcnow_iso(),
            },
            "tasks": [],
        }

    def _normalize_store_metadata(self) -> None:
        metadata = self._store.setdefault("metadata", {})
        metadata["schema_version"] = str(metadata.get("schema_version") or _TASK_SCHEMA_VERSION)
        try:
            metadata["revision"] = max(int(metadata.get("revision", 0) or 0), 0)
        except (TypeError, ValueError):
            metadata["revision"] = 0
        metadata["updated_at"] = str(metadata.get("updated_at") or _utcnow_iso())

    def _coerce_store(self, data: Any) -> dict[str, Any]:
        store = self._empty_store()
        if isinstance(data, dict):
            store["metadata"] = data.get("metadata") if isinstance(data.get("metadata"), dict) else store["metadata"]
            store["tasks"] = [item for item in data.get("tasks", []) if isinstance(item, dict)]
        original_store = getattr(self, "_store", self._empty_store())
        try:
            self._store = store
            self._normalize_store_metadata()
            return self._store
        finally:
            self._store = original_store

    def _load_store_snapshot(self, file_path: str) -> dict[str, Any] | None:
        normalized_path = _normalize_text(file_path)
        if not normalized_path:
            return None
        path = Path(normalized_path)
        backup_path = path.with_name(f"{path.name}.bak")
        if not path.exists() and not backup_path.exists():
            return None
        try:
            data = load_json_with_recovery(
                normalized_path,
                validator=lambda payload: isinstance(payload, dict) and isinstance(payload.get("tasks"), list),
            )
        except Exception:
            return None
        return {
            "path": normalized_path,
            "store": self._coerce_store(data),
        }

    def _store_priority(self, store: dict[str, Any]) -> tuple[int, datetime, int]:
        metadata = store.get("metadata") if isinstance(store.get("metadata"), dict) else {}
        try:
            revision = max(int(metadata.get("revision", 0) or 0), 0)
        except (TypeError, ValueError):
            revision = 0
        updated_at = _iso_to_dt(metadata.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc)
        tasks = store.get("tasks") if isinstance(store.get("tasks"), list) else []
        return revision, updated_at, len(tasks)

    def _delete_store_files(self, file_path: str) -> None:
        normalized_path = _normalize_text(file_path)
        if not normalized_path:
            return
        path = Path(normalized_path)
        backup_path = path.with_name(f"{path.name}.bak")
        for candidate in (path, backup_path):
            try:
                if candidate.exists():
                    candidate.unlink()
            except OSError:
                continue

    def _legacy_store_candidates(self, target_path: str) -> list[str]:
        candidates: list[str] = []
        for candidate in (self._derive_task_file_path(), self._task_file_path):
            normalized = _normalize_text(candidate)
            if not normalized or normalized == target_path or normalized in candidates:
                continue
            candidates.append(normalized)
        return candidates

    def _migrate_legacy_store(self, target_path: str) -> bool:
        normalized_target = _normalize_text(target_path)
        if not normalized_target:
            return False

        target_snapshot = self._load_store_snapshot(normalized_target)
        legacy_snapshots = [
            snapshot
            for snapshot in (
                self._load_store_snapshot(candidate)
                for candidate in self._legacy_store_candidates(normalized_target)
            )
            if snapshot is not None
        ]
        if not legacy_snapshots:
            return False

        winning_snapshot = max(
            ([target_snapshot] if target_snapshot is not None else []) + legacy_snapshots,
            key=lambda snapshot: self._store_priority(snapshot["store"]),
        )
        rewritten_target = target_snapshot is None or winning_snapshot["path"] != normalized_target
        if rewritten_target:
            atomic_write_json(normalized_target, winning_snapshot["store"])
        for snapshot in legacy_snapshots:
            self._delete_store_files(snapshot["path"])
        return rewritten_target

    def _load_store(self) -> dict[str, Any]:
        if self._store_backend is not None:
            try:
                data = self._store_backend.load()
            except Exception:
                return self._empty_store()
            store = self._coerce_store(data)
            self._store = store
            return store
        if not self._task_file_path:
            return self._empty_store()
        try:
            data = load_json_with_recovery(
                self._task_file_path,
                validator=lambda payload: isinstance(payload, dict) and isinstance(payload.get("tasks"), list),
                default_factory=self._empty_store,
            )
        except Exception:
            return self._empty_store()
        store = self._coerce_store(data)
        self._store = store
        return store

    def refresh_storage_binding(self, *, task_file_path: str | None = None, migrate_legacy: bool = False) -> None:
        if task_file_path is not None:
            self._task_file_path_override = _normalize_text(task_file_path)
        resolved_path = self._resolve_task_file_path()
        migrated = self._migrate_legacy_store(resolved_path) if migrate_legacy else False
        if resolved_path == self._task_file_path and not migrated:
            return
        self._task_file_path = resolved_path
        self._store = self._load_store()

    def _store_lock_path(self) -> str:
        if self._store_backend is not None or not self._task_file_path:
            return ""
        return f"{self._task_file_path}.lock"

    @contextmanager
    def _acquire_store_lock(self):
        lock_path = self._store_lock_path()
        if not lock_path:
            yield
            return
        path = Path(lock_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        owner = f"{os.getpid()}:{uuid4().hex}"
        deadline = time.monotonic() + _STORE_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(owner)
                break
            except FileExistsError:
                try:
                    age_seconds = time.time() - path.stat().st_mtime
                except OSError:
                    age_seconds = 0.0
                if age_seconds >= _STALE_STORE_LOCK_SECONDS:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for task store lock: {lock_path}")
                time.sleep(_STORE_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            try:
                if path.exists() and path.read_text(encoding="utf-8") == owner:
                    path.unlink()
            except OSError:
                pass

    def _touch_updated(self) -> None:
        self._normalize_store_metadata()
        self._store["metadata"]["updated_at"] = _utcnow_iso()

    async def _save_store(self) -> None:
        if self._store_backend is not None:
            self._touch_updated()
            self._store["metadata"]["revision"] = int(self._store["metadata"].get("revision", 0) or 0) + 1
            self._store_backend.save(self._store)
            return
        if not self._task_file_path:
            return
        self._touch_updated()
        self._store["metadata"]["revision"] = int(self._store["metadata"].get("revision", 0) or 0) + 1
        atomic_write_json(self._task_file_path, self._store)

    def set_store_backend(self, backend, *, migrate_current: bool = False) -> None:
        self._store_backend = backend
        if not migrate_current:
            self._store = self._load_store()
            return
        loaded = self._store_backend.load()
        if isinstance(loaded, dict) and loaded.get("tasks"):
            self._store = self._coerce_store(loaded)
        else:
            self._store_backend.save(self._store)

    def _iter_user_tasks(
        self,
        user_id: str,
        *,
        task_domain: str | None = None,
        statuses: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for record in self._store.get("tasks", []):
            record_status = _normalize_text(record.get("status")) or "active"
            if statuses is not None and record_status not in statuses:
                continue
            if statuses is None and record_status != "active":
                continue
            if record.get("scope", {}).get("user_id") not in {user_id, "global"}:
                continue
            self._ensure_task_defaults(record)
            if task_domain and record.get("task_domain") != task_domain:
                continue
            tasks.append(record)
        return tasks

    def _iter_all_active_tasks(self, *, task_domain: str | None = None) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for record in self._store.get("tasks", []):
            if record.get("status") != "active":
                continue
            self._ensure_task_defaults(record)
            if task_domain and record.get("task_domain") != task_domain:
                continue
            tasks.append(record)
        return tasks

    def _find_task_record(
        self,
        user_id: str,
        task_key: str,
        *,
        task_domain: str | None = None,
        statuses: set[str] | None = None,
    ) -> dict[str, Any] | None:
        normalized_key = _normalize_text(task_key)
        if not normalized_key:
            return None
        for record in self._iter_user_tasks(user_id, task_domain=task_domain, statuses=statuses):
            if _normalize_text(record.get("task_key")) == normalized_key:
                return record
        return None

    def _find_task_by_key_any_user(self, task_key: str, *, task_domain: str | None = None) -> dict[str, Any] | None:
        normalized_key = _normalize_text(task_key)
        if not normalized_key:
            return None
        for record in self._iter_all_active_tasks(task_domain=task_domain):
            if _normalize_text(record.get("task_key")) == normalized_key:
                return record
        return None

    @staticmethod
    def _task_record_type(task_domain: str) -> str:
        return "scheduled_task" if task_domain == "assistant_schedule" else "todo"

    @classmethod
    def _task_object_type(cls, task_domain: str) -> str:
        return cls._task_record_type(task_domain)

    def _task_candidate_payload(self, record: dict[str, Any]) -> dict[str, Any]:
        compact = self._compact_task(record)
        return {
            "object_type": compact.get("object_type"),
            "object_id": compact.get("object_id"),
            "record_id": compact.get("record_id"),
            "title": compact.get("summary"),
            "summary": compact.get("summary"),
            "status": compact.get("status"),
            "task_status": compact.get("task_status"),
            "schedule_kind": compact.get("schedule_kind"),
            "next_run_at": compact.get("next_run_at"),
            "due_at": compact.get("due_at"),
        }

    def _find_task_targets(
        self,
        *,
        user_id: str,
        task_domain: str,
        task_key: str = "",
        query: str = "",
        summary: str = "",
        include_deleted: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
        statuses = {"active", "deleted"} if include_deleted else {"active"}
        exact = self._find_task_record(user_id, task_key, task_domain=task_domain, statuses=statuses)
        if exact is not None:
            return [exact], [self._task_candidate_payload(exact)], True
        needle = _normalize_text(query or summary)
        if not needle:
            return [], [], False
        pool = self._iter_user_tasks(user_id, task_domain=task_domain, statuses=statuses)
        exact_matches = [
            record
            for record in pool
            if needle.lower()
            in {
                _normalize_text(record.get("task_key")).lower(),
                _normalize_text(record.get("content")).lower(),
                _normalize_text(record.get("id")).lower(),
            }
        ]
        if len(exact_matches) == 1:
            return exact_matches, [self._task_candidate_payload(exact_matches[0])], True
        matched = [record for record in pool if _looks_like_match(record, needle)]
        matched = self._sort_tasks(matched)
        return matched, [self._task_candidate_payload(record) for record in matched[:5]], False

    async def _confirm_task_operation(
        self,
        *,
        action: str,
        object_type: str,
        task_count: int,
        summary: str,
        session_id: str,
        source,
    ) -> bool:
        action_label = {
            "delete": "删除",
            "restore": "恢复",
            "cancel": "取消执行",
            "disable": "禁用",
        }.get(action, action)
        prompt = f"即将{action_label}{task_count}个{object_type}：{summary}"
        return await request_user_confirmation(
            prompt,
            session_id=session_id,
            source=source,
            timeout_seconds=30,
        )

    def _task_operation_payload(
        self,
        *,
        action: str,
        task_domain: str,
        status: str,
        tasks: list[dict[str, Any]],
        summary: str = "",
        candidates: list[dict[str, Any]] | None = None,
        error: dict[str, Any] | None = None,
        filters: dict[str, Any] | None = None,
        next_action_hint: str = "",
    ) -> dict[str, Any]:
        return build_object_operation_payload(
            action=action,
            object_type=self._task_object_type(task_domain),
            status=status,
            objects=tasks,
            summary=summary,
            candidates=candidates,
            error=error,
            filters_applied=filters,
            next_action_hint=next_action_hint,
            extra={
                "tasks": tasks,
                "task_count": len(tasks),
            },
        )

    def _ensure_unique_task_key(self, user_id: str, preferred_key: str) -> str:
        base = _slugify(preferred_key)
        candidate = base
        index = 2
        while self._find_task_record(user_id, candidate) is not None:
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def _schedule_anchor_at(self, record: dict[str, Any], *, now: datetime | None = None) -> datetime:
        anchor_dt = _iso_to_dt(record.get("schedule_anchor_at"))
        if anchor_dt is not None:
            return anchor_dt
        for field_name in ("created_at", "last_updated_at"):
            value = _iso_to_dt(record.get(field_name))
            if value is not None:
                return value
        return now or _utcnow()

    def _schedule_state(self, record: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        current = now or _utcnow()
        schedule_kind = _normalize_schedule_kind(record.get("schedule_kind") or "none")
        task_status = _normalize_text(record.get("task_status")).lower()
        last_completed_at = _iso_to_dt(record.get("last_completed_at"))
        last_triggered_at = _iso_to_dt(record.get("last_triggered_at"))
        run_lock_until = _iso_to_dt(record.get("run_lock_until"))
        last_run_status = _normalize_text(record.get("last_run_status")).lower()

        if schedule_kind == "none":
            return {
                "next_run_at": None,
                "current_cycle_start_at": None,
                "current_cycle_end_at": None,
                "is_due": False,
                "completed_in_cycle": False,
                "triggered_in_cycle": False,
                "awaiting_completion": False,
                "completion_state": "completed" if task_status == "done" else "unscheduled",
                "lock_active": bool(run_lock_until is not None and run_lock_until > current),
            }

        if schedule_kind == "once":
            due_dt = _iso_to_dt(record.get("due_at"))
            completed = task_status == "done" or _timestamp_in_window(last_completed_at, due_dt, None)
            triggered = _timestamp_in_window(last_triggered_at, due_dt, None)
            awaiting_completion = bool(due_dt is not None and triggered and not completed)
            retryable_failure = awaiting_completion and last_run_status == "failed"
            return {
                "next_run_at": None if completed else _dt_to_iso(due_dt) if due_dt is not None else None,
                "current_cycle_start_at": _dt_to_iso(due_dt) if due_dt is not None else None,
                "current_cycle_end_at": None,
                "is_due": bool(
                    due_dt is not None
                    and not completed
                    and due_dt <= current
                    and not (run_lock_until is not None and run_lock_until > current)
                    and (not triggered or retryable_failure)
                ),
                "completed_in_cycle": completed,
                "triggered_in_cycle": triggered,
                "awaiting_completion": awaiting_completion,
                "completion_state": (
                    "completed"
                    if completed
                    else "awaiting_retry"
                    if retryable_failure
                    else "awaiting_completion"
                    if awaiting_completion
                    else "pending"
                ),
                "lock_active": bool(run_lock_until is not None and run_lock_until > current),
            }

        recurrence = record.get("recurrence") if isinstance(record.get("recurrence"), dict) else {}
        timezone_name = record.get("timezone") or _DEFAULT_TIMEZONE
        anchor_dt = self._schedule_anchor_at(record, now=current)
        first_occurrence_text = _next_run_from_recurrence(
            recurrence,
            timezone_name,
            now=anchor_dt,
            inclusive=True,
        )
        first_occurrence_dt = _iso_to_dt(first_occurrence_text)
        latest_due_dt = _recurrence_occurrence_at_or_before(
            recurrence,
            timezone_name,
            reference=current,
        )

        if (
            latest_due_dt is None
            or first_occurrence_dt is None
            or latest_due_dt < first_occurrence_dt
        ):
            next_run_dt = first_occurrence_dt
            return {
                "next_run_at": _dt_to_iso(next_run_dt) if next_run_dt is not None else None,
                "current_cycle_start_at": None,
                "current_cycle_end_at": None,
                "is_due": False,
                "completed_in_cycle": False,
                "triggered_in_cycle": False,
                "awaiting_completion": False,
                "completion_state": "pending",
                "lock_active": bool(run_lock_until is not None and run_lock_until > current),
            }

        next_after_due_text = _next_run_from_recurrence(
            recurrence,
            timezone_name,
            now=latest_due_dt,
            inclusive=False,
        )
        next_after_due_dt = _iso_to_dt(next_after_due_text)
        completed_in_cycle = _timestamp_in_window(last_completed_at, latest_due_dt, next_after_due_dt)
        triggered_in_cycle = _timestamp_in_window(last_triggered_at, latest_due_dt, next_after_due_dt)
        next_run_dt = next_after_due_dt if completed_in_cycle else latest_due_dt
        awaiting_completion = bool(triggered_in_cycle and not completed_in_cycle)
        retryable_failure = awaiting_completion and last_run_status == "failed"
        is_due = (
            not completed_in_cycle
            and next_run_dt is not None
            and next_run_dt <= current
            and not (run_lock_until is not None and run_lock_until > current)
            and (not triggered_in_cycle or retryable_failure)
        )
        return {
            "next_run_at": _dt_to_iso(next_run_dt) if next_run_dt is not None else None,
            "current_cycle_start_at": _dt_to_iso(latest_due_dt) if latest_due_dt is not None else None,
            "current_cycle_end_at": _dt_to_iso(next_after_due_dt) if next_after_due_dt is not None else None,
            "is_due": bool(is_due),
            "completed_in_cycle": completed_in_cycle,
            "triggered_in_cycle": triggered_in_cycle,
            "awaiting_completion": awaiting_completion,
            "completion_state": (
                "completed_for_cycle"
                if completed_in_cycle
                else "awaiting_retry"
                if retryable_failure
                else "awaiting_completion"
                if awaiting_completion
                else "pending"
            ),
            "lock_active": bool(run_lock_until is not None and run_lock_until > current),
        }

    def _structured_task_state(self, record: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        current = now or _utcnow()
        schedule_state = self._schedule_state(record, now=current)
        cycle_start_at = _normalize_text(schedule_state.get("current_cycle_start_at"))
        cycle_end_at = _normalize_text(schedule_state.get("current_cycle_end_at"))
        cycle_due_at = _normalize_text(schedule_state.get("next_run_at") or record.get("due_at"))
        cycle_key = _cycle_key(
            record.get("schedule_kind"),
            cycle_start_at,
            cycle_end_at,
            fallback=cycle_due_at,
        )
        pending_payload = record.get("pending_delivery") if isinstance(record.get("pending_delivery"), dict) else {}
        last_run_status = _normalize_text(record.get("last_run_status")).lower()
        notify_policy = _normalize_text(record.get("notify_policy")).lower()
        auto_run = bool(record.get("auto_run", False))
        job = normalize_job_record(
            record.get("job"),
            kind=self._task_job_kind(record),
            name=self._task_job_name(record),
            max_retries=self._task_job_max_retries(record),
            status_source="task_manager.defaults",
        )
        last_failure = normalize_failure(job.get("last_failure"))
        last_delivery = normalize_delivery(job.get("last_delivery"))

        if schedule_state.get("is_due") and not schedule_state.get("triggered_in_cycle"):
            scheduler_status = "due"
        elif schedule_state.get("triggered_in_cycle") and schedule_state.get("lock_active"):
            scheduler_status = "claimed"
        elif schedule_state.get("triggered_in_cycle"):
            scheduler_status = "handled"
        elif schedule_state.get("next_run_at"):
            scheduler_status = "scheduled"
        else:
            scheduler_status = "idle"

        if auto_run:
            if last_run_status == "queued":
                execution_status = "queued"
            elif last_run_status == "succeeded":
                execution_status = "succeeded"
            elif last_run_status == "failed":
                execution_status = "failed"
            elif schedule_state.get("triggered_in_cycle"):
                execution_status = "claimed"
            elif schedule_state.get("next_run_at"):
                execution_status = "pending"
            else:
                execution_status = "idle"
        else:
            execution_status = "not_applicable"

        if notify_policy == "silent":
            delivery_status = "suppressed" if schedule_state.get("triggered_in_cycle") else "pending"
        elif pending_payload:
            delivery_status = "pending_redelivery"
        elif auto_run and notify_policy != "on_completion":
            delivery_status = "not_applicable"
        elif auto_run:
            delivery_status = "delivered" if last_run_status in {"succeeded", "failed"} else "pending"
        else:
            delivery_status = "delivered" if last_run_status == "notified" else "pending"

        event_kind = _normalize_text(pending_payload.get("kind"))
        if not event_kind and schedule_state.get("triggered_in_cycle"):
            event_kind = "task_completion" if auto_run else "task_due"
        event_id = _normalize_text(pending_payload.get("event_id")) or _cycle_event_id(
            record.get("task_key"),
            cycle_key,
            event_kind,
        )
        source_event_id = _normalize_text(pending_payload.get("source_event_id")) or event_id
        last_transition_at = (
            _normalize_text(pending_payload.get("created_at"))
            or _normalize_text(record.get("last_run_at"))
            or _normalize_text(record.get("last_completed_at"))
            or _normalize_text(record.get("last_triggered_at"))
            or _normalize_text(record.get("last_updated_at"))
        )
        completion_status = _normalize_text(schedule_state.get("completion_state")) or "pending"

        return {
            "schedule": {
                "status": scheduler_status,
                "cycle_key": cycle_key,
                "cycle_start_at": cycle_start_at or None,
                "cycle_due_at": cycle_due_at or None,
                "cycle_end_at": cycle_end_at or None,
                "next_run_at": _normalize_text(record.get("next_run_at")) or None,
                "due_at": _normalize_text(record.get("due_at")) or None,
                "triggered_in_cycle": bool(schedule_state.get("triggered_in_cycle")),
                "completed_in_cycle": bool(schedule_state.get("completed_in_cycle")),
                "lock_active": bool(schedule_state.get("lock_active")),
            },
            "execution": {
                "status": execution_status,
                "job_status": job.get("status"),
                "attempt_count": int(job.get("attempt_count", 0) or 0),
                "retry_count": int(job.get("retry_count", 0) or 0),
                "next_retry_at": job.get("next_retry_at"),
                "status_source": job.get("status_source"),
                "last_runtime_source": job.get("last_runtime_source"),
                "failure_category": last_failure.get("category") if last_failure else None,
                "failure_retryable": bool(last_failure.get("retryable")) if last_failure else False,
            },
            "delivery": {
                "status": delivery_status,
                "pending_redelivery": bool(pending_payload),
                "visible_channel": "completion_result" if auto_run else "due_reminder",
                "event_kind": event_kind or None,
                "event_id": event_id or None,
                "source_event_id": source_event_id or None,
                "last_transition_at": last_transition_at or None,
                "result": copy.deepcopy(last_delivery),
                "pending": copy.deepcopy(pending_payload) if pending_payload else None,
            },
            "orchestration": {
                "completion_status": completion_status,
                "awaiting_completion": bool(schedule_state.get("awaiting_completion", False)),
                "auto_run": auto_run,
                "notify_policy": notify_policy,
            },
        }

    def _orchestration_state(self, record: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        state = self._structured_task_state(record, now=now)
        return {
            **copy.deepcopy(state),
            "cycle_key": state["schedule"]["cycle_key"],
            "cycle_start_at": state["schedule"]["cycle_start_at"],
            "cycle_due_at": state["schedule"]["cycle_due_at"],
            "cycle_end_at": state["schedule"]["cycle_end_at"],
            "scheduler_status": state["schedule"]["status"],
            "execution_status": state["execution"]["status"],
            "delivery_status": state["delivery"]["status"],
            "completion_status": state["orchestration"]["completion_status"],
            "pending_redelivery": state["delivery"]["pending_redelivery"],
            "visible_channel": state["delivery"]["visible_channel"],
            "event_kind": state["delivery"]["event_kind"],
            "event_id": state["delivery"]["event_id"],
            "source_event_id": state["delivery"]["source_event_id"],
            "last_transition_at": state["delivery"]["last_transition_at"],
            "job_status": state["execution"]["job_status"],
            "attempt_count": state["execution"]["attempt_count"],
            "retry_count": state["execution"]["retry_count"],
            "next_retry_at": state["execution"]["next_retry_at"],
            "status_source": state["execution"]["status_source"],
            "last_runtime_source": state["execution"]["last_runtime_source"],
            "failure_category": state["execution"]["failure_category"],
            "failure_retryable": state["execution"]["failure_retryable"],
            "delivery_result": copy.deepcopy(state["delivery"]["result"]),
        }

    def _sync_orchestration_state(self, record: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        record["orchestration"] = self._orchestration_state(record, now=now)
        return record["orchestration"]

    def _task_job_kind(self, record: dict[str, Any]) -> str:
        if record.get("task_domain") != "assistant_schedule":
            return "user_task"
        if record.get("auto_run"):
            return "scheduled_task"
        return "scheduled_reminder"

    def _task_job_name(self, record: dict[str, Any]) -> str:
        return _normalize_text(record.get("task_key")) or _normalize_text(record.get("content")) or "task"

    def _task_job_max_retries(self, record: dict[str, Any]) -> int:
        return _DEFAULT_JOB_MAX_RETRIES if record.get("auto_run") else 0

    def _task_default_delivery_state(self, record: dict[str, Any]) -> str:
        if self._task_job_kind(record) == "user_task":
            return "not_applicable"
        if _normalize_text(record.get("notify_policy")).lower() == "silent":
            return "suppressed"
        return "pending"

    def _update_task_job(
        self,
        record: dict[str, Any],
        *,
        status: Any = _UNSET,
        runtime_source: Any = _UNSET,
        started_at: Any = _UNSET,
        finished_at: Any = _UNSET,
        success_at: Any = _UNSET,
        next_retry_at: Any = _UNSET,
        last_result: dict[str, Any] | None | object = _UNSET,
        last_failure: dict[str, Any] | None | object = _UNSET,
        last_delivery: dict[str, Any] | None | object = _UNSET,
        retry_count: Any = _UNSET,
        increment_attempt: bool = False,
        metadata: dict[str, Any] | None | object = _UNSET,
    ) -> dict[str, Any]:
        job = normalize_job_record(
            record.get("job"),
            kind=self._task_job_kind(record),
            name=self._task_job_name(record),
            max_retries=self._task_job_max_retries(record),
            status_source="task_manager.defaults",
        )
        if increment_attempt:
            job["attempt_count"] = max(int(job.get("attempt_count", 0) or 0), 0) + 1
        if status is not _UNSET:
            normalized_status = _normalize_text(status).lower()
            if normalized_status:
                job["status"] = normalized_status
        if runtime_source is not _UNSET:
            normalized_source = _normalize_text(runtime_source)
            job["last_runtime_source"] = normalized_source
            job["status_source"] = normalized_source
        if started_at is not _UNSET:
            job["last_started_at"] = _normalize_text(started_at) or None
        if finished_at is not _UNSET:
            job["last_finished_at"] = _normalize_text(finished_at) or None
        if success_at is not _UNSET:
            job["last_success_at"] = _normalize_text(success_at) or None
        if next_retry_at is not _UNSET:
            job["next_retry_at"] = _normalize_text(next_retry_at) or None
        if retry_count is not _UNSET:
            try:
                job["retry_count"] = max(int(retry_count or 0), 0)
            except (TypeError, ValueError):
                job["retry_count"] = 0
        if last_result is not _UNSET:
            job["last_result"] = copy.deepcopy(last_result) if isinstance(last_result, dict) else {}
        if last_failure is not _UNSET:
            job["last_failure"] = normalize_failure(last_failure)
        if last_delivery is not _UNSET:
            job["last_delivery"] = normalize_delivery(last_delivery)
        if metadata is not _UNSET:
            job["metadata"] = copy.deepcopy(metadata) if isinstance(metadata, dict) else {}
        record["job"] = job
        return job

    def _ensure_task_defaults(self, record: dict[str, Any]) -> None:
        record_type = _normalize_text(record.get("type")).lower()
        if record_type not in {"task", "todo", "scheduled_task"}:
            return
        record["schedule_kind"] = _normalize_schedule_kind(record.get("schedule_kind") or "none")
        record["task_domain"] = _normalize_task_domain(
            record.get("task_domain"),
            schedule_kind=record.get("schedule_kind") or "none",
        )
        record["type"] = self._task_record_type(record["task_domain"])
        record["timezone"] = _resolve_timezone_name(record.get("timezone") or _DEFAULT_TIMEZONE)
        record["recurrence"] = _serialize_jsonish(_normalize_recurrence(record.get("recurrence")) if record.get("recurrence") not in (None, "") else None)
        record["due_at"] = _normalize_text(record.get("due_at")) or None
        record["next_run_at"] = _normalize_text(record.get("next_run_at")) or None
        record["last_run_at"] = _normalize_text(record.get("last_run_at")) or None
        record["last_run_status"] = _normalize_text(record.get("last_run_status"))
        record["last_run_summary"] = _normalize_text(record.get("last_run_summary"))
        record["auto_run"] = bool(record.get("auto_run", False))
        record["job_prompt"] = _normalize_text(record.get("job_prompt"))
        record["notify_policy"] = _normalize_notify_policy(
            record.get("notify_policy"),
            default="on_completion" if record.get("auto_run") else "on_due",
        )
        record["delivery_target"] = copy.deepcopy(record.get("delivery_target")) if isinstance(record.get("delivery_target"), dict) else None
        record["origin_session_id"] = _normalize_text(record.get("origin_session_id"))
        record["run_lock_until"] = _normalize_text(record.get("run_lock_until")) or None
        record["active_claim_token"] = _normalize_text(record.get("active_claim_token")) or None
        record["run_history"] = copy.deepcopy(record.get("run_history")) if isinstance(record.get("run_history"), list) else []
        record["pending_delivery"] = copy.deepcopy(record.get("pending_delivery")) if isinstance(record.get("pending_delivery"), dict) else None
        record["preferred_tool_key"] = _normalize_text(record.get("preferred_tool_key"))
        record["preferred_target_endpoint_ids"] = _normalize_string_list(
            record.get("preferred_target_endpoint_ids")
        )
        record["preferred_endpoint_provider_types"] = _normalize_string_list(
            record.get("preferred_endpoint_provider_types")
        )
        record["tool_target_routing_policy"] = _normalize_routing_policy(
            record.get("tool_target_routing_policy"),
            default="balanced",
        )
        record["last_operation_id"] = _normalize_text(record.get("last_operation_id")) or None
        record["last_operation_status"] = _normalize_text(record.get("last_operation_status")) or None
        record["job"] = normalize_job_record(
            record.get("job"),
            kind=self._task_job_kind(record),
            name=self._task_job_name(record),
            max_retries=self._task_job_max_retries(record),
            status_source="task_manager.defaults",
        )
        record["orchestration"] = copy.deepcopy(record.get("orchestration")) if isinstance(record.get("orchestration"), dict) else {}
        record["schedule_anchor_at"] = _normalize_text(record.get("schedule_anchor_at")) or _normalize_text(record.get("created_at")) or _normalize_text(record.get("last_updated_at")) or _utcnow_iso()
        record["last_completed_at"] = _normalize_text(record.get("last_completed_at")) or None
        record["last_triggered_at"] = _normalize_text(record.get("last_triggered_at")) or None
        record["last_completion_summary"] = _normalize_text(record.get("last_completion_summary"))
        if self._task_job_kind(record) == "user_task":
            self._update_task_job(
                record,
                status="not_applicable",
                next_retry_at=None,
                last_delivery=delivery_payload(state="not_applicable"),
            )
        elif record.get("pending_delivery"):
            payload = record.get("pending_delivery") or {}
            self._update_task_job(
                record,
                status="awaiting_delivery",
                next_retry_at=record.get("run_lock_until"),
                last_delivery=delivery_payload(
                    state="pending_redelivery",
                    delivered=False,
                    channel="task_update",
                    message=payload.get("message"),
                    event_id=payload.get("event_id"),
                    source_event_id=payload.get("source_event_id"),
                    at=payload.get("created_at"),
                ),
            )
        elif not record["job"].get("last_delivery") or record["job"]["last_delivery"].get("state") == "not_applicable":
            self._update_task_job(
                record,
                last_delivery=delivery_payload(state=self._task_default_delivery_state(record)),
            )
        if record.get("schedule_kind") == "recurring" and record.get("task_status") == "done":
            record["last_completed_at"] = (
                record.get("last_completed_at")
                or record.get("last_run_at")
                or _normalize_text(record.get("last_updated_at"))
                or _normalize_text(record.get("created_at"))
                or _utcnow_iso()
            )
            record["task_status"] = "open"
        if record.get("next_run_at") in ("", None):
            record["next_run_at"] = self._schedule_state(record)["next_run_at"]
        self._sync_orchestration_state(record)

    def _compact_task(self, record: dict[str, Any]) -> dict[str, Any]:
        self._ensure_task_defaults(record)
        schedule_state = self._schedule_state(record)
        orchestration = copy.deepcopy(record.get("orchestration")) if isinstance(record.get("orchestration"), dict) else self._orchestration_state(record)
        return {
            "record_id": _normalize_text(record.get("id")),
            "object_id": _normalize_text(record.get("task_key")),
            "object_type": self._task_object_type(_normalize_text(record.get("task_domain"))),
            "task_key": _normalize_text(record.get("task_key")),
            "content": _normalize_text(record.get("content")),
            "summary": _normalize_text(record.get("content")),
            "status": _normalize_text(record.get("status")) or "active",
            "task_domain": _normalize_text(record.get("task_domain")),
            "project": _normalize_text(record.get("project")),
            "task_status": _normalize_text(record.get("task_status")),
            "deadline": _normalize_text(record.get("deadline")),
            "schedule_kind": _normalize_text(record.get("schedule_kind")),
            "due_at": _normalize_text(record.get("due_at")) or None,
            "timezone": _normalize_text(record.get("timezone")),
            "recurrence": _serialize_jsonish(record.get("recurrence")),
            "next_run_at": _normalize_text(record.get("next_run_at")) or None,
            "schedule_anchor_at": _normalize_text(record.get("schedule_anchor_at")),
            "last_completed_at": _normalize_text(record.get("last_completed_at")),
            "last_triggered_at": _normalize_text(record.get("last_triggered_at")),
            "last_completion_summary": _normalize_text(record.get("last_completion_summary")),
            "last_run_at": _normalize_text(record.get("last_run_at")),
            "last_run_status": _normalize_text(record.get("last_run_status")),
            "last_run_summary": _normalize_text(record.get("last_run_summary")),
            "active_claim_token": _normalize_text(record.get("active_claim_token")) or None,
            "job": copy.deepcopy(record.get("job")) if isinstance(record.get("job"), dict) else {},
            "current_cycle_start_at": schedule_state.get("current_cycle_start_at"),
            "current_cycle_end_at": schedule_state.get("current_cycle_end_at"),
            "completed_in_cycle": bool(schedule_state.get("completed_in_cycle", False)),
            "triggered_in_cycle": bool(schedule_state.get("triggered_in_cycle", False)),
            "awaiting_completion": bool(schedule_state.get("awaiting_completion", False)),
            "completion_state": _normalize_text(schedule_state.get("completion_state")),
            "orchestration": orchestration,
            "state": copy.deepcopy(orchestration),
            "auto_run": bool(record.get("auto_run", False)),
            "job_prompt": _normalize_text(record.get("job_prompt")),
            "preferred_tool_key": _normalize_text(record.get("preferred_tool_key")),
            "preferred_target_endpoint_ids": copy.deepcopy(record.get("preferred_target_endpoint_ids")) if isinstance(record.get("preferred_target_endpoint_ids"), list) else [],
            "preferred_endpoint_provider_types": copy.deepcopy(record.get("preferred_endpoint_provider_types")) if isinstance(record.get("preferred_endpoint_provider_types"), list) else [],
            "tool_target_routing_policy": _normalize_text(record.get("tool_target_routing_policy")) or "balanced",
            "last_operation_id": _normalize_text(record.get("last_operation_id")) or None,
            "last_operation_status": _normalize_text(record.get("last_operation_status")) or None,
            "notify_policy": _normalize_text(record.get("notify_policy")),
            "delivery_target": copy.deepcopy(record.get("delivery_target")) if isinstance(record.get("delivery_target"), dict) else None,
            "scope": copy.deepcopy(record.get("scope")) if isinstance(record.get("scope"), dict) else {},
            "created_at": _normalize_text(record.get("created_at")),
            "updated_at": _normalize_text(record.get("last_updated_at")),
        }

    def _sort_tasks(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        status_rank = {"open": 0, "blocked": 1, "done": 2}

        def sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
            next_run_at = _normalize_text(record.get("next_run_at")) or "9999-99-99T99:99:99Z"
            deadline = _normalize_text(record.get("deadline")) or "9999-99-99"
            updated_at = _normalize_text(record.get("last_updated_at")) or ""
            return (
                status_rank.get(_normalize_text(record.get("task_status")), 9),
                next_run_at,
                deadline,
                -len(updated_at),
                updated_at,
            )

        return sorted(tasks, key=sort_key)

    async def _maybe_embed(self, text: str) -> list[float]:
        try:
            return await self._memory._get_embedding(text)
        except Exception:
            return []

    async def _persist(self, record: dict[str, Any] | None = None, *, relink: bool = False) -> None:
        del record, relink
        await self._save_store()
        if self._db_sync_callback is not None:
            await self._db_sync_callback()

    async def remember_task_operation(
        self,
        task_key: str,
        *,
        operation_id: str,
        status: str,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        record = self._find_task_by_key_any_user(task_key)
        if record is None:
            return None
        current = now or _utcnow()
        record["last_operation_id"] = _normalize_text(operation_id) or None
        record["last_operation_status"] = _normalize_text(status) or None
        record["last_updated_at"] = _dt_to_iso(current)
        self._ensure_task_defaults(record)
        await self._persist(record)
        return copy.deepcopy(record)

    def set_db_sync_callback(self, callback) -> None:
        self._db_sync_callback = callback

    def _context_target(self) -> dict[str, Any]:
        target = get_event_context().get("target")
        if target is None:
            return {}
        return {
            "kind": getattr(target, "kind", "") or "",
            "id": getattr(target, "id", "") or "",
        }

    def _schedule_payload(
        self,
        *,
        summary: str,
        deadline: str,
        timezone_name: str,
        schedule_kind: Any = None,
        due_at: Any = None,
        recurrence: Any = None,
        auto_run: Any = None,
        job_prompt: Any = None,
        notify_policy: Any = None,
        existing: dict[str, Any] | None = None,
        allow_clear: bool = False,
        infer_from_text: bool = True,
    ) -> dict[str, Any]:
        existing = existing or {}
        if existing:
            self._ensure_task_defaults(existing)
        timezone_value = _resolve_timezone_name(timezone_name or existing.get("timezone") or _DEFAULT_TIMEZONE)
        explicit_schedule_kind = schedule_kind if schedule_kind is not None else existing.get("schedule_kind", "none")
        normalized_schedule_kind = _normalize_schedule_kind(explicit_schedule_kind, default="none")

        if allow_clear and due_at == "":
            normalized_due_at = None
        else:
            normalized_due_at = _parse_iso_or_date(due_at, timezone_value) if due_at not in (None, "") else existing.get("due_at")

        if allow_clear and recurrence == "":
            normalized_recurrence = None
        else:
            normalized_recurrence = (
                _normalize_recurrence(recurrence)
                if recurrence not in (None, "")
                else copy.deepcopy(existing.get("recurrence"))
            )

        derived = (
            _derive_schedule_from_text(summary, deadline, timezone_value)
            if infer_from_text
            else {"schedule_kind": "none", "due_at": None, "recurrence": None}
        )
        if normalized_schedule_kind == "none" and (not existing or existing.get("schedule_kind") == "none"):
            if normalized_recurrence:
                normalized_schedule_kind = "recurring"
            elif normalized_due_at:
                normalized_schedule_kind = "once"
            else:
                normalized_schedule_kind = derived["schedule_kind"]

        if normalized_schedule_kind == "recurring" and not normalized_recurrence:
            normalized_recurrence = derived["recurrence"]
        if normalized_schedule_kind == "once" and not normalized_due_at:
            normalized_due_at = derived["due_at"]

        if normalized_schedule_kind == "recurring" and not normalized_recurrence:
            raise ValueError("recurring tasks require recurrence or a parseable recurring summary.")
        if normalized_schedule_kind == "once" and not normalized_due_at:
            raise ValueError("once tasks require due_at/deadline or a parseable due time.")

        if normalized_schedule_kind == "none":
            normalized_due_at = None
            normalized_recurrence = None

        job_prompt_value = _normalize_text(job_prompt) if job_prompt is not None else _normalize_text(existing.get("job_prompt"))
        auto_run_value = _normalize_bool(auto_run, default=None) if auto_run is not None else existing.get("auto_run")
        if auto_run_value is None:
            auto_run_value = _guess_auto_run(summary, job_prompt_value, normalized_schedule_kind)

        notify_default = "on_completion" if auto_run_value else "on_due"
        notify_policy_value = (
            _normalize_notify_policy(notify_policy, default=notify_default)
            if notify_policy is not None
            else _normalize_notify_policy(existing.get("notify_policy"), default=notify_default)
        )

        return {
            "schedule_kind": normalized_schedule_kind,
            "due_at": normalized_due_at,
            "timezone": timezone_value,
            "recurrence": _serialize_jsonish(normalized_recurrence),
            "auto_run": bool(auto_run_value),
            "job_prompt": job_prompt_value,
            "notify_policy": notify_policy_value,
        }

    async def _create_task(
        self,
        *,
        user_id: str,
        task_domain: str,
        summary: str,
        task_key: str = "",
        project: str = "",
        task_status: str = "open",
        deadline: str = "",
        schedule_kind: str | None = None,
        due_at: str | None = None,
        timezone: str | None = None,
        recurrence: Any = None,
        auto_run: Any = None,
        job_prompt: str | None = None,
        notify_policy: str | None = None,
        preferred_tool_key: str | None = None,
        preferred_target_endpoint_ids: list[str] | None = None,
        preferred_endpoint_provider_types: list[str] | None = None,
        tool_target_routing_policy: str | None = None,
        session_id: str = "",
        source=None,
    ) -> dict[str, Any]:
        normalized_summary = _normalize_text(summary)
        if not normalized_summary:
            raise ValueError("create requires a non-empty summary.")

        status = _normalize_status(task_status or "open")
        task_key_value = self._ensure_unique_task_key(user_id, task_key or normalized_summary)
        normalized_task_domain = _normalize_task_domain(task_domain, schedule_kind=schedule_kind or "none")
        schedule_payload = self._schedule_payload(
            summary=normalized_summary,
            deadline=_normalize_text(deadline),
            timezone_name=timezone or _DEFAULT_TIMEZONE,
            schedule_kind=schedule_kind,
            due_at=due_at,
            recurrence=recurrence,
            auto_run=auto_run,
            job_prompt=job_prompt,
            notify_policy=notify_policy,
            infer_from_text=normalized_task_domain == "assistant_schedule",
        )
        if normalized_task_domain == "assistant_schedule" and schedule_payload["schedule_kind"] == "none":
            raise ValueError("scheduled tasks require trigger time or recurrence.")
        now = _utcnow_iso()
        now_dt = _iso_to_dt(now) or _utcnow()
        embedding = await self._maybe_embed(normalized_summary)
        record = {
            "id": f"task_{task_key_value}_{now.replace(':', '').replace('-', '').replace('T', '_').replace('Z', '')}",
            "type": self._task_record_type(normalized_task_domain),
            "scope": self._memory._record_scope(user_id, "", "task"),
            "content": normalized_summary,
            "canonical_text": normalized_summary.lower(),
            "embedding": embedding,
            "embedding_model": self._memory._embedding_model,
            "strength": 0.72,
            "importance": 0.7,
            "confidence": 1.0,
            "created_at": now,
            "last_accessed_at": now,
            "last_updated_at": now,
            "access_count": 0,
            "status": "active",
            "tags": [],
            "entity_keys": [],
            "source_record_ids": [],
            "task_key": task_key_value,
            "task_domain": normalized_task_domain,
            "project": _normalize_text(project),
            "task_status": status,
            "deadline": _normalize_text(deadline) or None,
            **schedule_payload,
            "schedule_anchor_at": now,
            "last_completed_at": None,
            "last_triggered_at": None,
            "last_completion_summary": "",
            "last_run_at": None,
            "last_run_status": "",
            "last_run_summary": "",
            "preferred_tool_key": _normalize_text(preferred_tool_key),
            "preferred_target_endpoint_ids": _normalize_string_list(preferred_target_endpoint_ids),
            "preferred_endpoint_provider_types": _normalize_string_list(preferred_endpoint_provider_types),
            "tool_target_routing_policy": _normalize_routing_policy(tool_target_routing_policy, default="balanced"),
            "delivery_target": _delivery_target_payload(session_id, source, self._context_target()),
            "origin_session_id": _normalize_text(session_id),
            "run_lock_until": None,
            "active_claim_token": None,
            "run_history": [],
            "pending_delivery": None,
            "job": default_job_record(
                kind="scheduled_task" if schedule_payload.get("auto_run") else "scheduled_reminder" if normalized_task_domain == "assistant_schedule" else "user_task",
                name=task_key_value,
                max_retries=_DEFAULT_JOB_MAX_RETRIES if schedule_payload.get("auto_run") else 0,
                status_source="task_manager.create",
            ),
            "orchestration": {},
        }
        record["next_run_at"] = self._schedule_state(record, now=now_dt)["next_run_at"]
        self._sync_orchestration_state(record, now=now_dt)
        self._store["tasks"].append(record)
        await self._persist(record, relink=True)
        return record

    async def _update_task(
        self,
        *,
        user_id: str,
        task_domain: str | None = None,
        task_key: str,
        summary: str = "",
        project: str = "",
        task_status: str = "",
        deadline: str | None = None,
        clear_deadline: bool = False,
        schedule_kind: str | None = None,
        due_at: str | None = None,
        timezone_name: str | None = None,
        recurrence: Any = None,
        auto_run: Any = None,
        job_prompt: str | None = None,
        notify_policy: str | None = None,
        preferred_tool_key: str | None = None,
        preferred_target_endpoint_ids: list[str] | None = None,
        preferred_endpoint_provider_types: list[str] | None = None,
        tool_target_routing_policy: str | None = None,
        completion_summary: str = "",
        session_id: str = "",
        source=None,
    ) -> dict[str, Any]:
        expected_task_domain = (
            _normalize_task_domain(task_domain, schedule_kind="none")
            if task_domain is not None
            else None
        )
        record = self._find_task_record(user_id, task_key, task_domain=expected_task_domain)
        if record is None:
            if expected_task_domain == "assistant_schedule":
                raise ValueError(f"scheduled task not found: {task_key}")
            raise ValueError(f"task_key not found: {task_key}")

        self._ensure_task_defaults(record)
        changed = False
        schedule_changed = False
        current = _utcnow()
        current_text = _dt_to_iso(current)
        normalized_summary = _normalize_text(summary) or _normalize_text(record.get("content"))
        if _normalize_text(summary):
            record["content"] = normalized_summary
            record["canonical_text"] = normalized_summary.lower()
            record["embedding"] = await self._maybe_embed(normalized_summary)
            record["embedding_model"] = self._memory._embedding_model
            changed = True

        normalized_project = _normalize_text(project)
        if project != "":
            record["project"] = normalized_project
            changed = True

        if task_status:
            normalized_task_status = _normalize_status(task_status, default=record.get("task_status") or "open")
            if normalized_task_status == "done":
                self._mark_task_completed(
                    record,
                    now=current,
                    summary=completion_summary or "Task marked complete.",
                )
                changed = True
            elif record.get("task_status") != normalized_task_status:
                record["task_status"] = normalized_task_status
                if normalized_task_status != "done":
                    record["last_completion_summary"] = ""
                changed = True

        if clear_deadline:
            record["deadline"] = None
            changed = True
        elif deadline is not None:
            record["deadline"] = _normalize_text(deadline) or None
            changed = True

        if any(value is not None for value in (schedule_kind, due_at, recurrence, auto_run, job_prompt, notify_policy, timezone_name)):
            schedule_payload = self._schedule_payload(
                summary=normalized_summary,
                deadline=_normalize_text(record.get("deadline")),
                timezone_name=timezone_name or record.get("timezone") or _DEFAULT_TIMEZONE,
                schedule_kind=schedule_kind if schedule_kind is not None else record.get("schedule_kind", "none"),
                due_at=due_at,
                recurrence=recurrence,
                auto_run=auto_run,
                job_prompt=job_prompt,
                notify_policy=notify_policy,
                existing=record,
                allow_clear=True,
                infer_from_text=record.get("task_domain") == "assistant_schedule",
            )
            for key, value in schedule_payload.items():
                if record.get(key) != value:
                    record[key] = value
                    changed = True
                    schedule_changed = True
            if schedule_changed:
                record["schedule_anchor_at"] = current_text
                if record.get("schedule_kind") == "none":
                    record["last_completed_at"] = None
                    record["last_triggered_at"] = None
                    record["last_completion_summary"] = ""
                    record["active_claim_token"] = None
                    record["pending_delivery"] = None
                    record["orchestration"] = {}

        if preferred_tool_key is not None:
            record["preferred_tool_key"] = _normalize_text(preferred_tool_key)
            changed = True
        if preferred_target_endpoint_ids is not None:
            record["preferred_target_endpoint_ids"] = _normalize_string_list(preferred_target_endpoint_ids)
            changed = True
        if preferred_endpoint_provider_types is not None:
            record["preferred_endpoint_provider_types"] = _normalize_string_list(preferred_endpoint_provider_types)
            changed = True
        if tool_target_routing_policy is not None:
            record["tool_target_routing_policy"] = _normalize_routing_policy(tool_target_routing_policy, default="balanced")
            changed = True

        if not changed:
            raise ValueError("update requires at least one field to change.")

        if session_id or source is not None:
            record["origin_session_id"] = _normalize_text(session_id) or _normalize_text(record.get("origin_session_id"))
            record["delivery_target"] = _delivery_target_payload(
                record.get("origin_session_id", ""),
                source,
                self._context_target(),
            ) or record.get("delivery_target")

        record["next_run_at"] = self._schedule_state(record, now=current)["next_run_at"]
        self._sync_orchestration_state(record, now=current)
        record["last_updated_at"] = current_text
        await self._persist(record, relink=True)
        return record

    def _filters_payload(
        self,
        *,
        task_status: str = "",
        project: str = "",
        query: str = "",
        limit: int,
        task_domain: str = "",
    ) -> dict[str, Any]:
        payload = {"limit": limit}
        if task_domain:
            payload["task_domain"] = task_domain
        if task_status:
            payload["task_status"] = task_status
        if project:
            payload["project"] = project
        if query:
            payload["query"] = query
        return payload

    def _has_schedule_inputs(
        self,
        *,
        schedule_kind: str | None = None,
        due_at: str | None = None,
        timezone: str | None = None,
        recurrence: Any = None,
        auto_run: Any = None,
        job_prompt: str | None = None,
        notify_policy: str | None = None,
    ) -> bool:
        return any(
            value not in (None, "", [])
            for value in (schedule_kind, due_at, timezone, recurrence, auto_run, job_prompt, notify_policy)
        )

    def _next_action_hint(self, action: str, tasks: list[dict[str, Any]]) -> str:
        if action == "create" and tasks:
            return f"Use task_key={tasks[0]['task_key']} to update or complete it later."
        if action == "complete" and tasks:
            return "List active tasks again if you want to review what is still open."
        if not tasks:
            return "No matching tasks were found."
        scheduled_domain = sum(1 for task in tasks if task.get("task_domain") == "assistant_schedule")
        if scheduled_domain:
            return "Use create_scheduled_workflow or manage_scheduled_workflows for Core scheduled workflows; user TODO state stays in manage_tasks."
        scheduled = sum(1 for task in tasks if task.get("schedule_kind") in {"once", "recurring"})
        if scheduled:
            return "Use create_scheduled_workflow or manage_scheduled_workflows for Core scheduled workflows; user TODO state stays in manage_tasks."
        blocked_count = sum(1 for task in tasks if task.get("task_status") == "blocked")
        if blocked_count:
            return "Review blocked tasks and decide what dependency needs to be cleared."
        return "Use task_key from this list with manage_tasks:update or manage_tasks:complete."

    def _is_task_due(self, record: dict[str, Any], *, now: datetime | None = None) -> bool:
        self._ensure_task_defaults(record)
        return self._schedule_state(record, now=now).get("is_due", False)

    def _claim_token_active(self, record: dict[str, Any], *, claim_token: str, now: datetime | None = None) -> bool:
        self._ensure_task_defaults(record)
        normalized_claim_token = _normalize_text(claim_token)
        if not normalized_claim_token:
            return False
        if _normalize_text(record.get("active_claim_token")) != normalized_claim_token:
            return False
        current = now or _utcnow()
        run_lock_until = _iso_to_dt(record.get("run_lock_until"))
        return bool(run_lock_until is not None and run_lock_until > current)

    def has_current_claim(self, task_key: str, claim_token: str, *, now: datetime | None = None) -> bool:
        record = self._find_task_by_key_any_user(task_key)
        if record is None:
            return False
        return self._claim_token_active(record, claim_token=claim_token, now=now)

    def _mark_task_completed(self, record: dict[str, Any], *, now: datetime | None = None, summary: str = "") -> None:
        self._ensure_task_defaults(record)
        current = now or _utcnow()
        current_text = _dt_to_iso(current)
        record["last_completed_at"] = current_text
        record["last_completion_summary"] = _normalize_text(summary) or "Task marked complete."
        record["last_triggered_at"] = record.get("last_triggered_at") or current_text
        record["run_lock_until"] = None
        record["active_claim_token"] = None
        record["pending_delivery"] = None
        if record.get("schedule_kind") == "recurring":
            record["task_status"] = "open"
        else:
            record["task_status"] = "done"
        self._update_task_job(
            record,
            status="completed",
            runtime_source="task_manager.complete",
            finished_at=current_text,
            success_at=current_text,
            next_retry_at=None,
            retry_count=0,
            last_failure=None,
            last_result={
                "status": "completed",
                "summary": record["last_completion_summary"],
                "at": current_text,
            },
        )
        record["next_run_at"] = self._schedule_state(record, now=current)["next_run_at"]
        self._sync_orchestration_state(record, now=current)

    def _advance_task_after_trigger(self, record: dict[str, Any], *, now: datetime | None = None, completed: bool = True) -> None:
        self._ensure_task_defaults(record)
        current = now or _utcnow()
        record["last_triggered_at"] = _dt_to_iso(current)
        if completed:
            self._mark_task_completed(record, now=current, summary=record.get("last_completion_summary") or "")
        record["next_run_at"] = self._schedule_state(record, now=current)["next_run_at"]

    def _append_run_history(self, record: dict[str, Any], payload: dict[str, Any]) -> None:
        history = record.setdefault("run_history", [])
        if not isinstance(history, list):
            history = []
            record["run_history"] = history
        history.append(payload)
        if len(history) > 8:
            del history[:-8]

    async def backfill_scheduled_tasks(self) -> int:
        return 0

    async def claim_due_tasks(
        self,
        *,
        limit: int = 8,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        del limit, lease_seconds, now
        return []

    async def complete_due_notification(
        self,
        task_key: str,
        *,
        summary: str,
        delivered: bool,
        runtime_source: str = "",
        delivery_channel: str = "task_update",
        delivery_details: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        del task_key, summary, delivered, runtime_source, delivery_channel, delivery_details, now
        raise RuntimeError("Legacy TaskManager scheduled reminders are removed; use V4 Scheduler jobs and Delivery.")

    async def complete_task_run(
        self,
        task_key: str,
        *,
        succeeded: bool,
        summary: str,
        next_retry_seconds: int = _DEFAULT_FAILURE_BACKOFF_SECONDS,
        delivered: bool = True,
        completed: bool = False,
        failure_category: str = "",
        failure_retryable: bool | None = None,
        failure_code: str = "",
        failure_details: dict[str, Any] | None = None,
        runtime_source: str = "",
        delivery_channel: str = "task_update",
        delivery_details: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        del (
            task_key,
            succeeded,
            summary,
            next_retry_seconds,
            delivered,
            completed,
            failure_category,
            failure_retryable,
            failure_code,
            failure_details,
            runtime_source,
            delivery_channel,
            delivery_details,
            now,
        )
        raise RuntimeError("Legacy TaskManager scheduled task runs are removed; use V4 Scheduler jobs and RunEventLog.")

    async def _pending_delivery_messages(self, source=None, *, clear: bool) -> list[dict[str, Any]]:
        user_id = self._memory._resolve_user_id(source)
        pending: list[dict[str, Any]] = []
        seen_delivery_keys: set[str] = set()
        changed = False
        for record in self._iter_user_tasks(user_id):
            payload = record.get("pending_delivery")
            if not isinstance(payload, dict):
                continue
            message = _normalize_text(payload.get("message"))
            if not message:
                record["pending_delivery"] = None
                changed = True
                continue
            raw_event_id = _normalize_text(payload.get("event_id")) or None
            raw_source_event_id = _normalize_text(payload.get("source_event_id")) or None
            delivery_key = _pending_delivery_identity(record, payload)
            if delivery_key not in seen_delivery_keys:
                seen_delivery_keys.add(delivery_key)
                pending.append(
                    {
                        "task_key": _normalize_text(record.get("task_key")),
                        "summary": _normalize_text(record.get("content")),
                        "message": message,
                        "kind": _normalize_text(payload.get("kind")) or "task_update",
                        "event_id": raw_event_id,
                        "source_event_id": raw_source_event_id or raw_event_id,
                        "cycle_key": _normalize_text(payload.get("cycle_key")) or None,
                        "delivery_key": delivery_key,
                        "created_at": _normalize_text(payload.get("created_at")),
                    }
                )
            if clear:
                record["pending_delivery"] = None
                self._update_task_job(
                    record,
                    status="completed" if record.get("task_domain") == "assistant_schedule" else "not_applicable",
                    runtime_source="app.pending_redelivery",
                    finished_at=_normalize_text(payload.get("created_at")) or _utcnow_iso(),
                    next_retry_at=None,
                    last_failure=None,
                    last_delivery=delivery_payload(
                        state="delivered",
                        delivered=True,
                        channel="task_update",
                        message=message,
                        event_id=raw_event_id,
                        source_event_id=raw_source_event_id,
                    ),
                )
                self._sync_orchestration_state(record)
                changed = True
        if changed:
            await self._persist()
        return pending

    async def peek_pending_delivery_messages(self, source=None) -> list[dict[str, Any]]:
        return await self._pending_delivery_messages(source=source, clear=False)

    async def collect_pending_delivery_messages(self, source=None) -> list[dict[str, Any]]:
        return await self._pending_delivery_messages(source=source, clear=True)

    async def acknowledge_pending_delivery_messages(
        self,
        *,
        source=None,
        event_ids: list[str] | None = None,
        now: datetime | None = None,
    ) -> int:
        user_id = self._memory._resolve_user_id(source)
        target_ids = {
            _normalize_text(item)
            for item in (event_ids or [])
            if _normalize_text(item)
        }
        changed = 0
        current_text = _dt_to_iso(now or _utcnow())
        for record in self._iter_user_tasks(user_id):
            payload = record.get("pending_delivery")
            if not isinstance(payload, dict):
                continue
            event_id = _normalize_text(payload.get("event_id"))
            source_event_id = _normalize_text(payload.get("source_event_id"))
            delivery_key = _pending_delivery_identity(record, payload)
            if target_ids and not ({event_id, source_event_id, delivery_key} & target_ids):
                continue
            message = _normalize_text(payload.get("message"))
            record["pending_delivery"] = None
            self._update_task_job(
                record,
                status="completed" if record.get("last_run_status") in {"notified", "succeeded"} else record.get("job", {}).get("status") or "completed",
                runtime_source="app.pending_redelivery",
                finished_at=current_text,
                next_retry_at=None,
                last_failure=None,
                last_delivery=delivery_payload(
                    state="delivered",
                    delivered=True,
                    channel="task_update",
                    message=message,
                    event_id=payload.get("event_id"),
                    source_event_id=payload.get("source_event_id"),
                    at=current_text,
                ),
            )
            self._sync_orchestration_state(record)
            record["last_updated_at"] = current_text
            changed += 1
        if changed:
            await self._persist()
        return changed

    def _background_task_snapshot(self, record: dict[str, Any], now: datetime) -> dict[str, Any]:
        self._ensure_task_defaults(record)
        schedule_state = self._schedule_state(record, now=now)
        orchestration = self._orchestration_state(record, now=now)
        job = normalize_job_record(
            record.get("job"),
            kind=self._task_job_kind(record),
            name=self._task_job_name(record),
            max_retries=self._task_job_max_retries(record),
            status_source="task_manager.defaults",
        )
        last_failure = normalize_failure(job.get("last_failure"))
        last_delivery = normalize_delivery(job.get("last_delivery"))
        next_run_text = _normalize_text(record.get("next_run_at"))
        due_at_text = _normalize_text(record.get("due_at"))
        next_run_dt = _iso_to_dt(next_run_text or due_at_text)
        minutes_until_due = None
        overdue = False
        if next_run_dt is not None:
            minutes_until_due = int((next_run_dt - now).total_seconds() / 60)
            overdue = next_run_dt <= now
        return {
            "task_key": _normalize_text(record.get("task_key")),
            "summary": _normalize_text(record.get("content")),
            "preferred_tool_key": _normalize_text(record.get("preferred_tool_key")),
            "preferred_target_endpoint_ids": copy.deepcopy(record.get("preferred_target_endpoint_ids")) if isinstance(record.get("preferred_target_endpoint_ids"), list) else [],
            "preferred_endpoint_provider_types": copy.deepcopy(record.get("preferred_endpoint_provider_types")) if isinstance(record.get("preferred_endpoint_provider_types"), list) else [],
            "tool_target_routing_policy": _normalize_text(record.get("tool_target_routing_policy")) or "balanced",
            "last_operation_id": _normalize_text(record.get("last_operation_id")) or None,
            "last_operation_status": _normalize_text(record.get("last_operation_status")) or None,
            "schedule_kind": _normalize_text(record.get("schedule_kind")),
            "next_run_at": next_run_text or None,
            "due_at": due_at_text or None,
            "current_cycle_start_at": schedule_state.get("current_cycle_start_at"),
            "current_cycle_end_at": schedule_state.get("current_cycle_end_at"),
            "cycle_key": orchestration.get("cycle_key"),
            "minutes_until_due": minutes_until_due,
            "overdue": overdue,
            "awaiting_completion": bool(schedule_state.get("awaiting_completion", False)),
            "completion_state": _normalize_text(schedule_state.get("completion_state")),
            "orchestration": orchestration,
            "state": copy.deepcopy(orchestration),
            "auto_run": bool(record.get("auto_run", False)),
            "job": copy.deepcopy(job),
            "job_status": job.get("status"),
            "retry_count": int(job.get("retry_count", 0) or 0),
            "next_retry_at": job.get("next_retry_at"),
            "status_source": job.get("status_source"),
            "failure_category": last_failure.get("category") if last_failure else None,
            "failure_retryable": bool(last_failure.get("retryable")) if last_failure else False,
            "delivery_state": last_delivery.get("state"),
        }

    def _consecutive_failures(self, record: dict[str, Any]) -> int:
        self._ensure_task_defaults(record)
        history = record.get("run_history")
        if isinstance(history, list) and history:
            count = 0
            for item in reversed(history):
                status = _normalize_text(item.get("status")).lower()
                if status != "failed":
                    break
                count += 1
            if count:
                return count
        return 1 if _normalize_text(record.get("last_run_status")).lower() == "failed" else 0

    def build_background_status(self) -> dict[str, Any]:
        failure_category_counts = {
            "retryable": 0,
            "non_retryable": 0,
            "manual_intervention": 0,
            "delivery": 0,
        }
        delivery_state_counts = {
            "pending": 0,
            "delivered": 0,
            "pending_redelivery": 0,
            "suppressed": 0,
            "failed": 0,
            "not_applicable": 0,
        }
        schedule_layer = {
            "scheduled_task_count": 0,
            "due_task_count": 0,
            "overdue_task_count": 0,
            "nearest_due_task": None,
            "nearest_due_in_minutes": None,
            "urgent_due_tasks": [],
            "urgent_due_task_count": 0,
        }
        execution_layer = {
            "awaiting_completion_count": 0,
            "run_succeeded_pending_completion_count": 0,
            "awaiting_completion_tasks": [],
            "retry_waiting_tasks": [],
            "job_status_counts": {},
            "repeated_failure_tasks": [],
            "failure_summary": {"by_category": failure_category_counts},
            "recent_failures": [],
            "recent_runs": [],
        }
        delivery_layer = {
            "pending_redelivery_count": 0,
            "pending_redelivery_tasks": [],
            "delivery_state_counts": delivery_state_counts,
        }
        return {
            "schedule": schedule_layer,
            "execution": execution_layer,
            "delivery": delivery_layer,
            "system": {},
            "background_status_sources": ["task_manager.user_todo"],
            "scheduled_task_count": 0,
            "due_task_count": 0,
            "overdue_task_count": 0,
            "awaiting_completion_count": 0,
            "run_succeeded_pending_completion_count": 0,
            "pending_delivery_count": 0,
            "nearest_due_task": None,
            "nearest_due_in_minutes": None,
            "urgent_due_tasks": [],
            "urgent_due_task_count": 0,
            "job_status_counts": {},
            "retry_waiting_tasks": [],
            "failure_summary": {"by_category": failure_category_counts},
            "delivery_state_counts": delivery_state_counts,
            "repeated_failure_tasks": [],
            "recent_failures": [],
            "recent_runs": [],
        }
    def get_task_by_key(self, task_key: str) -> dict[str, Any] | None:
        record = self._find_task_by_key_any_user(task_key)
        return self._compact_task(record) if record is not None else None

    async def manage_tasks(
        self,
        action: str,
        task_key: str = "",
        task_keys: list[str] | None = None,
        summary: str = "",
        completion_summary: str = "",
        project: str = "",
        task_status: str = "",
        deadline: str | None = None,
        query: str = "",
        limit: int = _DEFAULT_LIST_LIMIT,
        schedule_kind: str | None = None,
        due_at: str | None = None,
        timezone: str | None = None,
        recurrence: Any = None,
        auto_run: Any = None,
        job_prompt: str | None = None,
        notify_policy: str | None = None,
        session_id: str = "",
        source=None,
    ) -> str | ToolCallResult:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"create", "list", "detail", "update", "complete", "delete", "restore"}:
            return ToolCallResult.failure(
                tool_name="manage_tasks",
                source=ToolSourceType.BUILTIN,
                action_risk="write",
                code="task_action_invalid",
                category=ToolErrorCategory.VALIDATION,
                message="manage_tasks action must be one of create, list, detail, update, complete, delete, restore.",
                details={"action": normalized_action},
            )

        try:
            safe_limit = max(1, min(int(limit), _MAX_LIST_LIMIT))
        except (TypeError, ValueError):
            safe_limit = _DEFAULT_LIST_LIMIT

        user_id = self._memory._resolve_user_id(source)
        current_session_id = _normalize_text(session_id or get_event_context().get("session_id"))
        normalized_timezone = _resolve_timezone_name(timezone or _DEFAULT_TIMEZONE)
        normalized_task_keys = [
            _normalize_text(item)
            for item in (task_keys or [])
            if _normalize_text(item)
        ]
        if self._has_schedule_inputs(
            schedule_kind=schedule_kind,
            due_at=due_at,
            timezone=timezone,
            recurrence=recurrence,
            auto_run=auto_run,
            job_prompt=job_prompt,
            notify_policy=notify_policy,
        ):
            return ToolCallResult.failure(
                tool_name="manage_tasks",
                source=ToolSourceType.BUILTIN,
                action_risk="write",
                code="task_domain_invalid",
                category=ToolErrorCategory.VALIDATION,
                message=(
                    "manage_tasks only manages user TODO items. "
                    "Use create_scheduled_workflow/manage_scheduled_workflows for Core scheduled workflows with trigger time or recurrence."
                ),
                details={"action": normalized_action},
            )

        try:
            if normalized_action == "create":
                record = await self._create_task(
                    user_id=user_id,
                    task_domain="user_todo",
                    summary=summary,
                    task_key=task_key,
                    project=project,
                    task_status=task_status or "open",
                    deadline=_normalize_text(deadline),
                    schedule_kind="none",
                    due_at="",
                    timezone=normalized_timezone,
                    recurrence=None,
                    auto_run=False,
                    job_prompt="",
                    notify_policy=None,
                    session_id=current_session_id,
                    source=source,
                )
                tasks = [self._compact_task(record)]
                filters = self._filters_payload(limit=1, task_domain="user_todo")
                payload = self._task_operation_payload(
                    action=normalized_action,
                    task_domain="user_todo",
                    status="success",
                    tasks=tasks,
                    summary=f"已创建任务 {tasks[0]['task_key']}。",
                    filters=filters,
                    next_action_hint=self._next_action_hint(normalized_action, tasks),
                )
            elif normalized_action == "list":
                query_text = _normalize_text(query)
                project_filter = _normalize_text(project)
                status_filter = str(task_status or "").strip().lower()
                if status_filter and status_filter not in _VALID_TASK_STATUSES and status_filter != "all":
                    raise ValueError("task_status for list must be open, blocked, done, or all.")

                matched: list[dict[str, Any]] = []
                for record in self._iter_user_tasks(user_id, task_domain="user_todo"):
                    current_status = _normalize_text(record.get("task_status")).lower()
                    if status_filter:
                        if status_filter != "all" and current_status != status_filter:
                            continue
                    elif current_status == "done":
                        continue
                    if project_filter and _normalize_text(record.get("project")).lower() != project_filter.lower():
                        continue
                    if not _looks_like_match(record, query_text):
                        continue
                    matched.append(record)
                tasks = [self._compact_task(record) for record in self._sort_tasks(matched)[:safe_limit]]
                filters = self._filters_payload(
                    task_domain="user_todo",
                    task_status=status_filter or "active",
                    project=project_filter,
                    query=query_text,
                    limit=safe_limit,
                )
                payload = self._task_operation_payload(
                    action=normalized_action,
                    task_domain="user_todo",
                    status="success",
                    tasks=tasks,
                    summary=f"已返回 {len(tasks)} 个任务。",
                    filters=filters,
                    next_action_hint=self._next_action_hint(normalized_action, tasks),
                )
            elif normalized_action == "detail":
                matched, candidates, exact = self._find_task_targets(
                    user_id=user_id,
                    task_domain="user_todo",
                    task_key=task_key,
                    query=query,
                    summary=summary,
                )
                if not matched:
                    payload = self._task_operation_payload(
                        action=normalized_action,
                        task_domain="user_todo",
                        status="not_found",
                        tasks=[],
                        summary="未找到匹配的任务。",
                        candidates=candidates,
                        error={"code": "task_not_found", "message": "未找到匹配的任务。", "details": {"task_key": task_key, "query": query}},
                        next_action_hint="请先列出任务，或提供更明确的 task_key。",
                    )
                elif len(matched) > 1 and not exact:
                    payload = self._task_operation_payload(
                        action=normalized_action,
                        task_domain="user_todo",
                        status="ambiguous",
                        tasks=[],
                        summary="存在多个相似任务，请先明确目标。",
                        candidates=candidates,
                        error={"code": "task_ambiguous", "message": "存在多个相似任务，请先明确目标。", "details": {"candidate_count": len(matched)}},
                        next_action_hint="请改用 task_key 指定要查看的任务。",
                    )
                else:
                    tasks = [self._compact_task(matched[0])]
                    payload = self._task_operation_payload(
                        action=normalized_action,
                        task_domain="user_todo",
                        status="success",
                        tasks=tasks,
                        summary=f"已定位任务 {tasks[0]['task_key']}。",
                        filters=self._filters_payload(limit=1, task_domain="user_todo"),
                        next_action_hint="如需修改，可继续使用 update、complete、delete 或 restore。",
                    )
            elif normalized_action == "update":
                resolved_task_key = task_key
                if not resolved_task_key and query:
                    matched, candidates, exact = self._find_task_targets(
                        user_id=user_id,
                        task_domain="user_todo",
                        query=query,
                    )
                    if not matched:
                        payload = self._task_operation_payload(
                            action=normalized_action,
                            task_domain="user_todo",
                            status="not_found",
                            tasks=[],
                            summary="未找到可更新的任务。",
                            candidates=candidates,
                            error={"code": "task_not_found", "message": "未找到可更新的任务。", "details": {"query": query}},
                            next_action_hint="请先列出任务，或提供更明确的 task_key。",
                        )
                        return json.dumps(payload, ensure_ascii=False, indent=2)
                    if len(matched) > 1 and not exact:
                        payload = self._task_operation_payload(
                            action=normalized_action,
                            task_domain="user_todo",
                            status="ambiguous",
                            tasks=[],
                            summary="存在多个相似任务，暂不执行更新。",
                            candidates=candidates,
                            error={"code": "task_ambiguous", "message": "存在多个相似任务，暂不执行更新。", "details": {"candidate_count": len(matched)}},
                            next_action_hint="请改用 task_key 指定要更新的任务。",
                        )
                        return json.dumps(payload, ensure_ascii=False, indent=2)
                    resolved_task_key = _normalize_text(matched[0].get("task_key"))
                record = await self._update_task(
                    user_id=user_id,
                    task_domain="user_todo",
                    task_key=resolved_task_key,
                    summary=summary,
                    project=project,
                    task_status=task_status,
                    deadline=deadline,
                    clear_deadline=deadline == "",
                    schedule_kind=None,
                    due_at=None,
                    timezone_name=None,
                    recurrence=None,
                    auto_run=None,
                    job_prompt=None,
                    notify_policy=None,
                    completion_summary=completion_summary,
                    session_id=current_session_id,
                    source=source,
                )
                tasks = [self._compact_task(record)]
                filters = self._filters_payload(limit=1, task_domain="user_todo")
                payload = self._task_operation_payload(
                    action=normalized_action,
                    task_domain="user_todo",
                    status="success",
                    tasks=tasks,
                    summary=f"已更新任务 {tasks[0]['task_key']}。",
                    filters=filters,
                    next_action_hint=self._next_action_hint(normalized_action, tasks),
                )
            elif normalized_action == "complete":
                resolved_task_key = task_key
                if not resolved_task_key and query:
                    matched, candidates, exact = self._find_task_targets(
                        user_id=user_id,
                        task_domain="user_todo",
                        query=query,
                    )
                    if not matched:
                        payload = self._task_operation_payload(
                            action=normalized_action,
                            task_domain="user_todo",
                            status="not_found",
                            tasks=[],
                            summary="未找到可完成的任务。",
                            candidates=candidates,
                            error={"code": "task_not_found", "message": "未找到可完成的任务。", "details": {"query": query}},
                            next_action_hint="请先列出任务，或提供更明确的 task_key。",
                        )
                        return json.dumps(payload, ensure_ascii=False, indent=2)
                    if len(matched) > 1 and not exact:
                        payload = self._task_operation_payload(
                            action=normalized_action,
                            task_domain="user_todo",
                            status="ambiguous",
                            tasks=[],
                            summary="存在多个相似任务，暂不执行完成。",
                            candidates=candidates,
                            error={"code": "task_ambiguous", "message": "存在多个相似任务，暂不执行完成。", "details": {"candidate_count": len(matched)}},
                            next_action_hint="请改用 task_key 指定要完成的任务。",
                        )
                        return json.dumps(payload, ensure_ascii=False, indent=2)
                    resolved_task_key = _normalize_text(matched[0].get("task_key"))
                record = await self._update_task(
                    user_id=user_id,
                    task_domain="user_todo",
                    task_key=resolved_task_key,
                    task_status="done",
                    completion_summary=completion_summary or summary,
                    session_id=current_session_id,
                    source=source,
                )
                tasks = [self._compact_task(record)]
                filters = self._filters_payload(limit=1, task_domain="user_todo")
                payload = self._task_operation_payload(
                    action=normalized_action,
                    task_domain="user_todo",
                    status="success",
                    tasks=tasks,
                    summary=f"已完成任务 {tasks[0]['task_key']}。",
                    filters=filters,
                    next_action_hint=self._next_action_hint(normalized_action, tasks),
                )
            else:
                if normalized_task_keys:
                    matched = [
                        record
                        for key in normalized_task_keys
                        if (record := self._find_task_record(
                            user_id,
                            key,
                            task_domain="user_todo",
                            statuses={"active", "deleted"},
                        ))
                        is not None
                    ]
                    candidates = [self._task_candidate_payload(record) for record in matched]
                    exact = True
                else:
                    matched, candidates, exact = self._find_task_targets(
                        user_id=user_id,
                        task_domain="user_todo",
                        task_key=task_key,
                        query=query,
                        summary=summary,
                        include_deleted=normalized_action == "restore",
                    )
                if not matched:
                    payload = self._task_operation_payload(
                        action=normalized_action,
                        task_domain="user_todo",
                        status="not_found",
                        tasks=[],
                        summary="未找到匹配的任务。",
                        candidates=candidates,
                        error={"code": "task_not_found", "message": "未找到匹配的任务。", "details": {"task_key": task_key, "query": query}},
                        next_action_hint="请先列出任务，或提供更明确的 task_key。",
                    )
                elif len(matched) > 1 and not exact:
                    payload = self._task_operation_payload(
                        action=normalized_action,
                        task_domain="user_todo",
                        status="ambiguous",
                        tasks=[],
                        summary="存在多个相似任务，暂不执行对象操作。",
                        candidates=candidates,
                        error={"code": "task_ambiguous", "message": "存在多个相似任务，暂不执行对象操作。", "details": {"candidate_count": len(matched)}},
                        next_action_hint="请改用 task_key 指定目标任务。",
                    )
                else:
                    prompt_summary = "、".join(
                        _normalize_text(record.get("content")) or _normalize_text(record.get("task_key"))
                        for record in matched[:3]
                    )
                    confirmed = await self._confirm_task_operation(
                        action=normalized_action,
                        object_type="任务",
                        task_count=len(matched),
                        summary=prompt_summary,
                        session_id=current_session_id,
                        source=source,
                    )
                    if not confirmed:
                        payload = self._task_operation_payload(
                            action=normalized_action,
                            task_domain="user_todo",
                            status="cancelled",
                            tasks=[],
                            summary="用户未确认任务对象操作，未执行变更。",
                            candidates=candidates,
                            next_action_hint="如需继续，请重新发起操作并在确认框中同意。",
                        )
                    else:
                        current_text = _utcnow_iso()
                        for record in matched:
                            if normalized_action == "delete":
                                record["status"] = "deleted"
                            else:
                                record["status"] = "active"
                            record["last_updated_at"] = current_text
                        await self._persist()
                        tasks = [self._compact_task(record) for record in matched]
                        payload = self._task_operation_payload(
                            action=normalized_action,
                            task_domain="user_todo",
                            status="success",
                            tasks=tasks,
                            summary="已删除任务。" if normalized_action == "delete" else "已恢复任务。",
                            filters=self._filters_payload(limit=len(tasks), task_domain="user_todo"),
                            next_action_hint="可继续使用 detail 查看结果。",
                        )
        except ValueError as exc:
            return ToolCallResult.failure(
                tool_name="manage_tasks",
                source=ToolSourceType.BUILTIN,
                action_risk="write",
                code="task_operation_invalid",
                category=ToolErrorCategory.VALIDATION,
                message=str(exc),
                details={"action": normalized_action},
            )
        return json.dumps(payload, ensure_ascii=False, indent=2)
