from __future__ import annotations

import copy
import json
import os
import re
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from core.runtime_context import get_event_context

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
_URGENT_DUE_WINDOW = timedelta(hours=6)
_BACKGROUND_DUE_LIST_LIMIT = 3
_REPEATED_FAILURE_THRESHOLD = 2
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


class TaskManager:
    def __init__(self, memory):
        self._memory = memory
        self._task_file_path = self._derive_task_file_path()
        self._store = self._load_store()

    def _derive_task_file_path(self) -> str:
        memory_path = _normalize_text(getattr(self._memory, "_memory_file_path", ""))
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

    def _empty_store(self) -> dict[str, Any]:
        return {
            "metadata": {
                "updated_at": _utcnow_iso(),
            },
            "tasks": [],
        }

    def _load_store(self) -> dict[str, Any]:
        if not self._task_file_path:
            return self._empty_store()
        if not os.path.exists(self._task_file_path):
            return self._empty_store()
        try:
            with open(self._task_file_path, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
            if not raw:
                return self._empty_store()
            data = json.loads(raw)
        except Exception:
            return self._empty_store()
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
            return self._empty_store()
        store = self._empty_store()
        store["metadata"] = data.get("metadata") if isinstance(data.get("metadata"), dict) else store["metadata"]
        store["tasks"] = [item for item in data.get("tasks", []) if isinstance(item, dict)]
        return store

    def _refresh_store_binding(self) -> None:
        task_file_path = self._derive_task_file_path()
        if task_file_path == self._task_file_path:
            return
        self._task_file_path = task_file_path
        self._store = self._load_store()

    def _load_legacy_memory_tasks(self) -> list[dict[str, Any]]:
        memory_store = getattr(self._memory, "_store", {})
        current_records = memory_store.get("records", []) if isinstance(memory_store, dict) else []
        if isinstance(current_records, list):
            current_tasks = [
                copy.deepcopy(record)
                for record in current_records
                if isinstance(record, dict) and record.get("type") == "task"
            ]
            if current_tasks:
                return current_tasks

        memory_path = _normalize_text(getattr(self._memory, "_memory_file_path", ""))
        if not memory_path or not os.path.exists(memory_path):
            return []
        try:
            with open(memory_path, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
            if not raw:
                return []
            data = json.loads(raw)
        except Exception:
            return []
        records = data.get("records", []) if isinstance(data, dict) else []
        if not isinstance(records, list):
            return []
        return [
            copy.deepcopy(record)
            for record in records
            if isinstance(record, dict) and record.get("type") == "task"
        ]

    def _prune_task_records_from_memory_store(self, task_ids: set[str]) -> None:
        memory_store = getattr(self._memory, "_store", {})
        if not isinstance(memory_store, dict):
            return
        records = memory_store.get("records", [])
        if isinstance(records, list):
            memory_store["records"] = [
                record
                for record in records
                if not (isinstance(record, dict) and record.get("type") == "task")
            ]
        edges = memory_store.get("edges", [])
        if not task_ids or not isinstance(edges, list):
            return
        memory_store["edges"] = [
            edge
            for edge in edges
            if isinstance(edge, dict)
            and edge.get("from_id") not in task_ids
            and edge.get("to_id") not in task_ids
        ]

    def _touch_updated(self) -> None:
        self._store.setdefault("metadata", {})
        self._store["metadata"]["updated_at"] = _utcnow_iso()

    async def _save_store(self) -> None:
        if not self._task_file_path:
            return
        self._touch_updated()
        with open(self._task_file_path, "w", encoding="utf-8") as handle:
            json.dump(self._store, handle, ensure_ascii=False, indent=2)

    async def sync_legacy_memory_tasks(self) -> int:
        self._refresh_store_binding()
        legacy_records = self._load_legacy_memory_tasks()
        if not legacy_records:
            return 0
        migrated = 0
        task_ids = {
            _normalize_text(record.get("id"))
            for record in legacy_records
            if isinstance(record, dict) and _normalize_text(record.get("id"))
        }
        for record in legacy_records:
            task_key = _normalize_text(record.get("task_key"))
            if not task_key:
                continue
            if self._find_task_by_key_any_user(task_key) is None:
                task_copy = copy.deepcopy(record)
                self._ensure_task_defaults(task_copy)
                self._store["tasks"].append(task_copy)
                migrated += 1
        self._prune_task_records_from_memory_store(task_ids)
        await self._memory.save_memory_graph()
        if migrated:
            await self._save_store()
        return migrated

    def _iter_user_tasks(self, user_id: str, *, task_domain: str | None = None) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for record in self._store.get("tasks", []):
            if record.get("status") != "active":
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

    def _find_task_record(self, user_id: str, task_key: str, *, task_domain: str | None = None) -> dict[str, Any] | None:
        normalized_key = _normalize_text(task_key)
        if not normalized_key:
            return None
        for record in self._iter_user_tasks(user_id, task_domain=task_domain):
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

    def _orchestration_state(self, record: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
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

        return {
            "cycle_key": cycle_key,
            "cycle_start_at": cycle_start_at or None,
            "cycle_due_at": cycle_due_at or None,
            "cycle_end_at": cycle_end_at or None,
            "scheduler_status": scheduler_status,
            "execution_status": execution_status,
            "delivery_status": delivery_status,
            "completion_status": _normalize_text(schedule_state.get("completion_state")) or "pending",
            "pending_redelivery": bool(pending_payload),
            "visible_channel": "completion_result" if auto_run else "due_reminder",
            "event_kind": event_kind or None,
            "event_id": event_id or None,
            "source_event_id": source_event_id or None,
            "last_transition_at": last_transition_at or None,
        }

    def _sync_orchestration_state(self, record: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        record["orchestration"] = self._orchestration_state(record, now=now)
        return record["orchestration"]

    def _ensure_task_defaults(self, record: dict[str, Any]) -> None:
        if record.get("type") != "task":
            return
        record["schedule_kind"] = _normalize_schedule_kind(record.get("schedule_kind") or "none")
        record["task_domain"] = _normalize_task_domain(
            record.get("task_domain"),
            schedule_kind=record.get("schedule_kind") or "none",
        )
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
        record["orchestration"] = copy.deepcopy(record.get("orchestration")) if isinstance(record.get("orchestration"), dict) else {}
        record["schedule_anchor_at"] = _normalize_text(record.get("schedule_anchor_at")) or _normalize_text(record.get("created_at")) or _normalize_text(record.get("last_updated_at")) or _utcnow_iso()
        record["last_completed_at"] = _normalize_text(record.get("last_completed_at")) or None
        record["last_triggered_at"] = _normalize_text(record.get("last_triggered_at")) or None
        record["last_completion_summary"] = _normalize_text(record.get("last_completion_summary"))
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
        return {
            "task_key": _normalize_text(record.get("task_key")),
            "content": _normalize_text(record.get("content")),
            "summary": _normalize_text(record.get("content")),
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
            "current_cycle_start_at": schedule_state.get("current_cycle_start_at"),
            "current_cycle_end_at": schedule_state.get("current_cycle_end_at"),
            "completed_in_cycle": bool(schedule_state.get("completed_in_cycle", False)),
            "triggered_in_cycle": bool(schedule_state.get("triggered_in_cycle", False)),
            "awaiting_completion": bool(schedule_state.get("awaiting_completion", False)),
            "completion_state": _normalize_text(schedule_state.get("completion_state")),
            "orchestration": copy.deepcopy(record.get("orchestration")) if isinstance(record.get("orchestration"), dict) else self._orchestration_state(record),
            "auto_run": bool(record.get("auto_run", False)),
            "job_prompt": _normalize_text(record.get("job_prompt")),
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
            "type": "task",
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
            "delivery_target": _delivery_target_payload(session_id, source, self._context_target()),
            "origin_session_id": _normalize_text(session_id),
            "run_lock_until": None,
            "active_claim_token": None,
            "run_history": [],
            "pending_delivery": None,
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
            return "Use task_key with manage_scheduled_tasks:update to adjust schedule metadata or completion state."
        scheduled = sum(1 for task in tasks if task.get("schedule_kind") in {"once", "recurring"})
        if scheduled:
            return "Use task_key with manage_scheduled_tasks:update to adjust schedule metadata or completion state."
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
        changed = 0
        now = _utcnow_iso()
        now_dt = _iso_to_dt(now) or _utcnow()
        for record in self._iter_all_active_tasks(task_domain="assistant_schedule"):
            original = json.dumps(self._compact_task(record), ensure_ascii=False, sort_keys=True, default=str)
            derived = self._schedule_payload(
                summary=_normalize_text(record.get("content")),
                deadline=_normalize_text(record.get("deadline")),
                timezone_name=record.get("timezone") or _DEFAULT_TIMEZONE,
                schedule_kind=record.get("schedule_kind") or "none",
                due_at=record.get("due_at"),
                recurrence=record.get("recurrence"),
                auto_run=record.get("auto_run"),
                job_prompt=record.get("job_prompt"),
                notify_policy=record.get("notify_policy"),
                existing=record,
            )
            for key, value in derived.items():
                record[key] = value
            record["schedule_anchor_at"] = _normalize_text(record.get("schedule_anchor_at")) or _normalize_text(record.get("created_at")) or _normalize_text(record.get("last_updated_at")) or now
            record["last_completed_at"] = _normalize_text(record.get("last_completed_at")) or None
            record["last_triggered_at"] = _normalize_text(record.get("last_triggered_at")) or None
            record["active_claim_token"] = _normalize_text(record.get("active_claim_token")) or None
            record["next_run_at"] = self._schedule_state(record, now=now_dt)["next_run_at"]
            self._sync_orchestration_state(record, now=now_dt)
            if record.get("delivery_target") is None and record.get("origin_session_id"):
                record["delivery_target"] = {"kind": "current_session", "id": "", "session_id": record.get("origin_session_id", "")}
            updated = json.dumps(self._compact_task(record), ensure_ascii=False, sort_keys=True, default=str)
            if updated != original:
                record["last_updated_at"] = now
                changed += 1
        if changed:
            await self._persist()
        return changed

    async def claim_due_tasks(
        self,
        *,
        limit: int = 8,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        current = now or _utcnow()
        claimed: list[dict[str, Any]] = []
        for record in self._sort_tasks(self._iter_all_active_tasks(task_domain="assistant_schedule")):
            if len(claimed) >= limit:
                break
            if not self._is_task_due(record, now=current):
                continue
            if record.get("schedule_kind") not in {"once", "recurring"} and not record.get("auto_run"):
                continue
            current_text = _dt_to_iso(current)
            claim_token = uuid4().hex
            record["run_lock_until"] = _dt_to_iso(current + timedelta(seconds=max(lease_seconds, 10)))
            record["active_claim_token"] = claim_token
            record["last_triggered_at"] = current_text
            record["last_run_status"] = "queued" if record.get("auto_run") else "due"
            record["next_run_at"] = self._schedule_state(record, now=current)["next_run_at"]
            self._sync_orchestration_state(record, now=current)
            record["last_updated_at"] = current_text
            self._append_run_history(
                record,
                {
                    "timestamp": current_text,
                    "status": record["last_run_status"],
                    "summary": "Task was claimed by the scheduler for execution." if record.get("auto_run") else "Task was claimed by the scheduler for notification.",
                },
            )
            claimed.append(copy.deepcopy(record))
        if claimed:
            await self._persist()
        return claimed

    async def complete_due_notification(
        self,
        task_key: str,
        *,
        summary: str,
        delivered: bool,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        record = self._find_task_by_key_any_user(task_key)
        if record is None:
            raise ValueError(f"task_key not found: {task_key}")
        current = now or _utcnow()
        cycle_key = _cycle_key(
            record.get("schedule_kind"),
            record.get("next_run_at") or record.get("due_at"),
            None,
            fallback=record.get("due_at"),
        )
        event_id = _cycle_event_id(record.get("task_key"), cycle_key, "task_due")
        record["last_run_at"] = _dt_to_iso(current)
        record["last_run_status"] = "notified" if delivered else "pending_delivery"
        record["last_run_summary"] = _normalize_text(summary)
        record["last_triggered_at"] = _dt_to_iso(current)
        record["run_lock_until"] = None
        record["active_claim_token"] = None
        if not delivered and record.get("notify_policy") != "silent":
            record["pending_delivery"] = {
                "created_at": _dt_to_iso(current),
                "message": _normalize_text(summary),
                "kind": "task_due",
                "event_id": event_id,
                "source_event_id": event_id,
                "cycle_key": cycle_key,
            }
        else:
            record["pending_delivery"] = None
        record["next_run_at"] = self._schedule_state(record, now=current)["next_run_at"]
        self._sync_orchestration_state(record, now=current)
        record["last_updated_at"] = _dt_to_iso(current)
        self._append_run_history(
            record,
            {
                "timestamp": _dt_to_iso(current),
                "status": record["last_run_status"],
                "summary": record["last_run_summary"],
            },
        )
        await self._persist()
        return copy.deepcopy(record)

    async def complete_task_run(
        self,
        task_key: str,
        *,
        succeeded: bool,
        summary: str,
        next_retry_seconds: int = _DEFAULT_FAILURE_BACKOFF_SECONDS,
        delivered: bool = True,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        record = self._find_task_by_key_any_user(task_key)
        if record is None:
            raise ValueError(f"task_key not found: {task_key}")
        current = now or _utcnow()
        cycle_key = _cycle_key(
            record.get("schedule_kind"),
            record.get("next_run_at") or record.get("due_at"),
            None,
            fallback=record.get("due_at"),
        )
        event_id = _cycle_event_id(record.get("task_key"), cycle_key, "task_completion")
        record["last_run_at"] = _dt_to_iso(current)
        record["last_run_status"] = "succeeded" if succeeded else "failed"
        record["last_run_summary"] = _normalize_text(summary)
        record["last_triggered_at"] = _dt_to_iso(current)
        record["active_claim_token"] = None
        if succeeded:
            record["run_lock_until"] = None
        else:
            record["run_lock_until"] = _dt_to_iso(current + timedelta(seconds=max(next_retry_seconds, 60)))
        if not delivered and record.get("notify_policy") == "on_completion":
            record["pending_delivery"] = {
                "created_at": _dt_to_iso(current),
                "message": record["last_run_summary"],
                "kind": "task_completion",
                "event_id": event_id,
                "source_event_id": event_id,
                "cycle_key": cycle_key,
            }
        elif delivered and record.get("notify_policy") == "on_completion":
            record["pending_delivery"] = None
        record["next_run_at"] = self._schedule_state(record, now=current)["next_run_at"]
        self._sync_orchestration_state(record, now=current)
        record["last_updated_at"] = _dt_to_iso(current)
        self._append_run_history(
            record,
            {
                "timestamp": _dt_to_iso(current),
                "status": record["last_run_status"],
                "summary": record["last_run_summary"],
            },
        )
        await self._persist()
        return copy.deepcopy(record)

    async def collect_pending_delivery_messages(self, source=None) -> list[dict[str, Any]]:
        user_id = self._memory._resolve_user_id(source)
        pending: list[dict[str, Any]] = []
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
            pending.append(
                {
                    "task_key": _normalize_text(record.get("task_key")),
                    "summary": _normalize_text(record.get("content")),
                    "message": message,
                    "kind": _normalize_text(payload.get("kind")) or "task_update",
                    "event_id": _normalize_text(payload.get("event_id")) or None,
                    "source_event_id": _normalize_text(payload.get("source_event_id")) or None,
                    "cycle_key": _normalize_text(payload.get("cycle_key")) or None,
                    "created_at": _normalize_text(payload.get("created_at")),
                }
            )
            record["pending_delivery"] = None
            self._sync_orchestration_state(record)
            changed = True
        if changed:
            await self._persist()
        return pending

    def _background_task_snapshot(self, record: dict[str, Any], now: datetime) -> dict[str, Any]:
        self._ensure_task_defaults(record)
        schedule_state = self._schedule_state(record, now=now)
        orchestration = self._orchestration_state(record, now=now)
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
            "auto_run": bool(record.get("auto_run", False)),
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
        now = _utcnow()
        scheduled: list[dict[str, Any]] = []
        due_count = 0
        overdue_count = 0
        awaiting_completion_count = 0
        run_succeeded_pending_completion_count = 0
        recent_failures: list[dict[str, Any]] = []
        recent_runs: list[dict[str, Any]] = []
        pending_delivery_count = 0
        due_candidates: list[tuple[datetime, dict[str, Any]]] = []
        urgent_due_tasks: list[tuple[datetime, dict[str, Any]]] = []
        repeated_failure_tasks: list[dict[str, Any]] = []
        awaiting_completion_tasks: list[dict[str, Any]] = []
        pending_delivery_tasks: list[dict[str, Any]] = []

        for record in self._iter_all_active_tasks():
            schedule_kind = record.get("schedule_kind")
            if schedule_kind not in {"once", "recurring"} and not record.get("auto_run"):
                continue
            scheduled.append(record)
            schedule_state = self._schedule_state(record, now=now)
            next_run_dt = _iso_to_dt(record.get("next_run_at"))
            actionable_user_follow_up = bool(
                not record.get("auto_run")
                and not schedule_state.get("awaiting_completion")
            )
            if bool(schedule_state.get("is_due")):
                due_count += 1
            if bool(schedule_state.get("is_due")) and next_run_dt is not None and next_run_dt <= now - timedelta(minutes=5):
                overdue_count += 1
            if schedule_state.get("awaiting_completion"):
                awaiting_completion_count += 1
                awaiting_completion_tasks.append(self._background_task_snapshot(record, now))
                if _normalize_text(record.get("last_run_status")).lower() == "succeeded":
                    run_succeeded_pending_completion_count += 1
            if actionable_user_follow_up and next_run_dt is not None:
                snapshot = self._background_task_snapshot(record, now)
                due_candidates.append((next_run_dt, snapshot))
                if next_run_dt <= now + _URGENT_DUE_WINDOW:
                    urgent_due_tasks.append((next_run_dt, snapshot))
            if record.get("pending_delivery"):
                pending_delivery_count += 1
                pending_delivery_tasks.append(
                    {
                        **self._background_task_snapshot(record, now),
                        "pending_delivery": copy.deepcopy(record.get("pending_delivery")),
                    }
                )
            status = _normalize_text(record.get("last_run_status")).lower()
            if status == "failed":
                recent_failures.append(
                    {
                        "task_key": _normalize_text(record.get("task_key")),
                        "last_run_at": _normalize_text(record.get("last_run_at")),
                        "summary": _normalize_text(record.get("last_run_summary")),
                    }
                )
            consecutive_failures = self._consecutive_failures(record)
            if consecutive_failures >= _REPEATED_FAILURE_THRESHOLD:
                repeated_failure_tasks.append(
                    {
                        **self._background_task_snapshot(record, now),
                        "consecutive_failures": consecutive_failures,
                        "last_run_at": _normalize_text(record.get("last_run_at")),
                        "last_run_summary": _normalize_text(record.get("last_run_summary")),
                    }
                )
            if status:
                recent_runs.append(
                    {
                        "task_key": _normalize_text(record.get("task_key")),
                        "status": status,
                        "last_run_at": _normalize_text(record.get("last_run_at")),
                        "summary": _normalize_text(record.get("last_run_summary")),
                    }
                )

        recent_failures.sort(key=lambda item: item.get("last_run_at", ""), reverse=True)
        recent_runs.sort(key=lambda item: item.get("last_run_at", ""), reverse=True)
        due_candidates.sort(key=lambda item: item[0])
        urgent_due_tasks.sort(key=lambda item: item[0])
        repeated_failure_tasks.sort(
            key=lambda item: (
                -int(item.get("consecutive_failures", 0) or 0),
                str(item.get("last_run_at") or ""),
            ),
            reverse=False,
        )
        nearest_due_task = due_candidates[0][1] if due_candidates else None
        nearest_due_in_minutes = (
            int(nearest_due_task.get("minutes_until_due"))
            if isinstance(nearest_due_task, dict) and nearest_due_task.get("minutes_until_due") is not None
            else None
        )
        schedule_layer = {
            "scheduled_task_count": len(scheduled),
            "due_task_count": due_count,
            "overdue_task_count": overdue_count,
            "nearest_due_task": nearest_due_task,
            "nearest_due_in_minutes": nearest_due_in_minutes,
            "urgent_due_tasks": [item[1] for item in urgent_due_tasks[:_BACKGROUND_DUE_LIST_LIMIT]],
            "urgent_due_task_count": len(urgent_due_tasks),
        }
        execution_layer = {
            "awaiting_completion_count": awaiting_completion_count,
            "run_succeeded_pending_completion_count": run_succeeded_pending_completion_count,
            "awaiting_completion_tasks": awaiting_completion_tasks[:_BACKGROUND_DUE_LIST_LIMIT],
            "repeated_failure_tasks": repeated_failure_tasks[:_BACKGROUND_DUE_LIST_LIMIT],
            "recent_failures": recent_failures[:5],
            "recent_runs": recent_runs[:8],
        }
        delivery_layer = {
            "pending_redelivery_count": pending_delivery_count,
            "pending_redelivery_tasks": pending_delivery_tasks[:_BACKGROUND_DUE_LIST_LIMIT],
        }

        return {
            "schedule": schedule_layer,
            "execution": execution_layer,
            "delivery": delivery_layer,
            "system": {},
            "scheduled_task_count": len(scheduled),
            "due_task_count": due_count,
            "overdue_task_count": overdue_count,
            "awaiting_completion_count": awaiting_completion_count,
            "run_succeeded_pending_completion_count": run_succeeded_pending_completion_count,
            "pending_delivery_count": pending_delivery_count,
            "nearest_due_task": nearest_due_task,
            "nearest_due_in_minutes": nearest_due_in_minutes,
            "urgent_due_tasks": [item[1] for item in urgent_due_tasks[:_BACKGROUND_DUE_LIST_LIMIT]],
            "urgent_due_task_count": len(urgent_due_tasks),
            "repeated_failure_tasks": repeated_failure_tasks[:_BACKGROUND_DUE_LIST_LIMIT],
            "recent_failures": recent_failures[:5],
            "recent_runs": recent_runs[:8],
        }

    def get_task_by_key(self, task_key: str) -> dict[str, Any] | None:
        record = self._find_task_by_key_any_user(task_key)
        return self._compact_task(record) if record is not None else None

    async def manage_tasks(
        self,
        action: str,
        task_key: str = "",
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
    ) -> str:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"create", "list", "update", "complete"}:
            return "Error: manage_tasks action must be one of create, list, update, complete."

        try:
            safe_limit = max(1, min(int(limit), _MAX_LIST_LIMIT))
        except (TypeError, ValueError):
            safe_limit = _DEFAULT_LIST_LIMIT

        user_id = self._memory._resolve_user_id(source)
        current_session_id = _normalize_text(session_id or get_event_context().get("session_id"))
        normalized_timezone = _resolve_timezone_name(timezone or _DEFAULT_TIMEZONE)
        if self._has_schedule_inputs(
            schedule_kind=schedule_kind,
            due_at=due_at,
            timezone=timezone,
            recurrence=recurrence,
            auto_run=auto_run,
            job_prompt=job_prompt,
            notify_policy=notify_policy,
        ):
            return (
                "Error: manage_tasks only manages user TODO items. "
                "Use manage_scheduled_tasks for any task with trigger time or recurrence."
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
            elif normalized_action == "update":
                record = await self._update_task(
                    user_id=user_id,
                    task_domain="user_todo",
                    task_key=task_key,
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
            else:
                record = await self._update_task(
                    user_id=user_id,
                    task_domain="user_todo",
                    task_key=task_key,
                    task_status="done",
                    completion_summary=completion_summary or summary,
                    session_id=current_session_id,
                    source=source,
                )
                tasks = [self._compact_task(record)]
                filters = self._filters_payload(limit=1, task_domain="user_todo")
        except ValueError as exc:
            return f"Error: manage_tasks failed: {exc}"

        payload = {
            "action": normalized_action,
            "tasks": tasks,
            "task_count": len(tasks),
            "filters_applied": filters,
            "next_action_hint": self._next_action_hint(normalized_action, tasks),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def manage_scheduled_tasks(
        self,
        action: str,
        task_key: str = "",
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
    ) -> str:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"create", "list", "update", "complete"}:
            return "Error: manage_scheduled_tasks action must be one of create, list, update, complete."

        try:
            safe_limit = max(1, min(int(limit), _MAX_LIST_LIMIT))
        except (TypeError, ValueError):
            safe_limit = _DEFAULT_LIST_LIMIT

        user_id = self._memory._resolve_user_id(source)
        current_session_id = _normalize_text(session_id or get_event_context().get("session_id"))
        normalized_timezone = _resolve_timezone_name(timezone or _DEFAULT_TIMEZONE)

        try:
            if normalized_action == "create":
                record = await self._create_task(
                    user_id=user_id,
                    task_domain="assistant_schedule",
                    summary=summary,
                    task_key=task_key,
                    project=project,
                    task_status=task_status or "open",
                    deadline=_normalize_text(deadline),
                    schedule_kind=schedule_kind,
                    due_at=due_at or "",
                    timezone=normalized_timezone,
                    recurrence=recurrence,
                    auto_run=auto_run,
                    job_prompt=job_prompt or "",
                    notify_policy=notify_policy,
                    session_id=current_session_id,
                    source=source,
                )
                tasks = [self._compact_task(record)]
                filters = self._filters_payload(limit=1, task_domain="assistant_schedule")
            elif normalized_action == "list":
                query_text = _normalize_text(query)
                project_filter = _normalize_text(project)
                status_filter = str(task_status or "").strip().lower()
                if status_filter and status_filter not in _VALID_TASK_STATUSES and status_filter != "all":
                    raise ValueError("task_status for list must be open, blocked, done, or all.")

                matched: list[dict[str, Any]] = []
                for record in self._iter_user_tasks(user_id, task_domain="assistant_schedule"):
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
                    task_domain="assistant_schedule",
                    task_status=status_filter or "active",
                    project=project_filter,
                    query=query_text,
                    limit=safe_limit,
                )
            elif normalized_action == "update":
                normalized_schedule_kind = schedule_kind
                if normalized_schedule_kind is not None and _normalize_schedule_kind(normalized_schedule_kind or "none") == "none":
                    raise ValueError("scheduled tasks cannot be updated to schedule_kind=none.")
                record = await self._update_task(
                    user_id=user_id,
                    task_domain="assistant_schedule",
                    task_key=task_key,
                    summary=summary,
                    project=project,
                    task_status=task_status,
                    deadline=deadline,
                    clear_deadline=deadline == "",
                    schedule_kind=schedule_kind,
                    due_at=due_at,
                    timezone_name=normalized_timezone if timezone is not None else None,
                    recurrence=recurrence,
                    auto_run=auto_run,
                    job_prompt=job_prompt,
                    notify_policy=notify_policy,
                    completion_summary=completion_summary,
                    session_id=current_session_id,
                    source=source,
                )
                tasks = [self._compact_task(record)]
                filters = self._filters_payload(limit=1, task_domain="assistant_schedule")
            else:
                record = await self._update_task(
                    user_id=user_id,
                    task_domain="assistant_schedule",
                    task_key=task_key,
                    task_status="done",
                    completion_summary=completion_summary or summary,
                    session_id=current_session_id,
                    source=source,
                )
                tasks = [self._compact_task(record)]
                filters = self._filters_payload(limit=1, task_domain="assistant_schedule")
        except ValueError as exc:
            return f"Error: manage_scheduled_tasks failed: {exc}"

        payload = {
            "action": normalized_action,
            "tasks": tasks,
            "task_count": len(tasks),
            "filters_applied": filters,
            "next_action_hint": self._next_action_hint(normalized_action, tasks),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
