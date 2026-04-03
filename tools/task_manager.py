"""
Deterministic lightweight task and scheduling management backed by the memory store.
"""

from __future__ import annotations

import copy
import json
import re
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Any

from core.runtime_context import get_event_context

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore[assignment]

_VALID_TASK_STATUSES = {"open", "blocked", "done"}
_VALID_SCHEDULE_KINDS = {"none", "once", "recurring"}
_VALID_NOTIFY_POLICIES = {"on_due", "on_completion", "silent"}
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
            "hour": _clamp_hour(raw.get("hour"), 9),
            "minute": _clamp_minute(raw.get("minute"), 0),
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
            "hour": _clamp_hour(raw.get("hour"), 9),
            "minute": _clamp_minute(raw.get("minute"), 0),
        }
    if freq == "monthly":
        try:
            day = int(raw.get("day"))
        except (TypeError, ValueError):
            day = 1
        return {
            "freq": "monthly",
            "day": max(1, min(day, 31)),
            "hour": _clamp_hour(raw.get("hour"), 9),
            "minute": _clamp_minute(raw.get("minute"), 0),
        }
    if freq == "hourly":
        return {
            "freq": "hourly",
            "minute": _clamp_minute(raw.get("minute"), 0),
        }
    raise ValueError("recurrence freq must be one of: daily, weekly, monthly, hourly.")


def _next_run_from_recurrence(
    recurrence: dict[str, Any],
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> str | None:
    if not recurrence:
        return None

    current_utc = now or _utcnow()
    zone = _timezone_for_name(timezone_name)
    local_now = current_utc.astimezone(zone)
    freq = str(recurrence.get("freq") or "").strip().lower()

    if freq == "daily":
        hour = _clamp_hour(recurrence.get("hour"), 9)
        minute = _clamp_minute(recurrence.get("minute"), 0)
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return _dt_to_iso(candidate)

    if freq == "weekly":
        weekday = int(recurrence.get("weekday", 0))
        hour = _clamp_hour(recurrence.get("hour"), 9)
        minute = _clamp_minute(recurrence.get("minute"), 0)
        days_ahead = (weekday - local_now.weekday()) % 7
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
        if candidate <= local_now:
            candidate += timedelta(days=7)
        return _dt_to_iso(candidate)

    if freq == "monthly":
        day = int(recurrence.get("day", 1))
        hour = _clamp_hour(recurrence.get("hour"), 9)
        minute = _clamp_minute(recurrence.get("minute"), 0)
        year = local_now.year
        month = local_now.month
        max_day = monthrange(year, month)[1]
        candidate_day = max(1, min(day, max_day))
        candidate = local_now.replace(day=candidate_day, hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local_now:
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
            max_day = monthrange(year, month)[1]
            candidate = candidate.replace(year=year, month=month, day=max(1, min(day, max_day)))
        return _dt_to_iso(candidate)

    if freq == "hourly":
        minute = _clamp_minute(recurrence.get("minute"), 0)
        candidate = local_now.replace(minute=minute, second=0, microsecond=0)
        if candidate <= local_now:
            candidate += timedelta(hours=1)
            candidate = candidate.replace(minute=minute, second=0, microsecond=0)
        return _dt_to_iso(candidate)

    return None


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

    def _iter_user_tasks(self, user_id: str) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for record in self._memory._store.get("records", []):
            if record.get("type") != "task":
                continue
            if record.get("status") != "active":
                continue
            if record.get("scope", {}).get("user_id") not in {user_id, "global"}:
                continue
            self._ensure_task_defaults(record)
            tasks.append(record)
        return tasks

    def _iter_all_active_tasks(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for record in self._memory._store.get("records", []):
            if record.get("type") != "task" or record.get("status") != "active":
                continue
            self._ensure_task_defaults(record)
            tasks.append(record)
        return tasks

    def _find_task_record(self, user_id: str, task_key: str) -> dict[str, Any] | None:
        normalized_key = _normalize_text(task_key)
        if not normalized_key:
            return None
        for record in self._iter_user_tasks(user_id):
            if _normalize_text(record.get("task_key")) == normalized_key:
                return record
        return None

    def _find_task_by_key_any_user(self, task_key: str) -> dict[str, Any] | None:
        normalized_key = _normalize_text(task_key)
        if not normalized_key:
            return None
        for record in self._iter_all_active_tasks():
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

    def _ensure_task_defaults(self, record: dict[str, Any]) -> None:
        if record.get("type") != "task":
            return
        record["schedule_kind"] = _normalize_schedule_kind(record.get("schedule_kind") or "none")
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
        record["run_history"] = copy.deepcopy(record.get("run_history")) if isinstance(record.get("run_history"), list) else []
        record["pending_delivery"] = copy.deepcopy(record.get("pending_delivery")) if isinstance(record.get("pending_delivery"), dict) else None

    def _compact_task(self, record: dict[str, Any]) -> dict[str, Any]:
        self._ensure_task_defaults(record)
        return {
            "task_key": _normalize_text(record.get("task_key")),
            "summary": _normalize_text(record.get("content")),
            "project": _normalize_text(record.get("project")),
            "task_status": _normalize_text(record.get("task_status")),
            "deadline": _normalize_text(record.get("deadline")),
            "schedule_kind": _normalize_text(record.get("schedule_kind")),
            "due_at": _normalize_text(record.get("due_at")),
            "timezone": _normalize_text(record.get("timezone")),
            "recurrence": _serialize_jsonish(record.get("recurrence")),
            "next_run_at": _normalize_text(record.get("next_run_at")),
            "last_run_at": _normalize_text(record.get("last_run_at")),
            "last_run_status": _normalize_text(record.get("last_run_status")),
            "last_run_summary": _normalize_text(record.get("last_run_summary")),
            "auto_run": bool(record.get("auto_run", False)),
            "job_prompt": _normalize_text(record.get("job_prompt")),
            "notify_policy": _normalize_text(record.get("notify_policy")),
            "delivery_target": copy.deepcopy(record.get("delivery_target")) if isinstance(record.get("delivery_target"), dict) else None,
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
        if record is not None and relink and record.get("embedding"):
            try:
                self._memory._link_semantic_edges(record)
            except Exception:
                pass
        await self._memory.save_memory_graph()

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

        derived = _derive_schedule_from_text(summary, deadline, timezone_value)
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
            next_run_at = None
        elif normalized_schedule_kind == "once":
            next_run_at = normalized_due_at
        else:
            next_run_at = _next_run_from_recurrence(normalized_recurrence or {}, timezone_value)

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
            "next_run_at": next_run_at,
            "auto_run": bool(auto_run_value),
            "job_prompt": job_prompt_value,
            "notify_policy": notify_policy_value,
        }

    async def _create_task(
        self,
        *,
        user_id: str,
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
        )
        now = _utcnow_iso()
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
            "project": _normalize_text(project),
            "task_status": status,
            "deadline": _normalize_text(deadline) or None,
            **schedule_payload,
            "last_run_at": None,
            "last_run_status": "",
            "last_run_summary": "",
            "delivery_target": _delivery_target_payload(session_id, source, self._context_target()),
            "origin_session_id": _normalize_text(session_id),
            "run_lock_until": None,
            "run_history": [],
            "pending_delivery": None,
        }
        self._memory._store["records"].append(record)
        await self._persist(record, relink=True)
        return record

    async def _update_task(
        self,
        *,
        user_id: str,
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
        session_id: str = "",
        source=None,
    ) -> dict[str, Any]:
        record = self._find_task_record(user_id, task_key)
        if record is None:
            raise ValueError(f"task_key not found: {task_key}")

        self._ensure_task_defaults(record)
        changed = False
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
            record["task_status"] = _normalize_status(task_status, default=record.get("task_status") or "open")
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
            )
            for key, value in schedule_payload.items():
                if record.get(key) != value:
                    record[key] = value
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

        record["last_updated_at"] = _utcnow_iso()
        await self._persist(record, relink=True)
        return record

    def _filters_payload(
        self,
        *,
        task_status: str = "",
        project: str = "",
        query: str = "",
        limit: int,
    ) -> dict[str, Any]:
        payload = {"limit": limit}
        if task_status:
            payload["task_status"] = task_status
        if project:
            payload["project"] = project
        if query:
            payload["query"] = query
        return payload

    def _next_action_hint(self, action: str, tasks: list[dict[str, Any]]) -> str:
        if action == "create" and tasks:
            return f"Use task_key={tasks[0]['task_key']} to update or complete it later."
        if action == "complete" and tasks:
            return "List active tasks again if you want to review what is still open."
        if not tasks:
            return "No matching tasks were found."
        scheduled = sum(1 for task in tasks if task.get("schedule_kind") in {"once", "recurring"})
        if scheduled:
            return "Use task_key with manage_tasks:update to adjust schedule metadata or completion state."
        blocked_count = sum(1 for task in tasks if task.get("task_status") == "blocked")
        if blocked_count:
            return "Review blocked tasks and decide what dependency needs to be cleared."
        return "Use task_key from this list with manage_tasks:update or manage_tasks:complete."

    def _is_task_due(self, record: dict[str, Any], *, now: datetime | None = None) -> bool:
        self._ensure_task_defaults(record)
        if record.get("task_status") == "done":
            return False
        next_run_dt = _iso_to_dt(record.get("next_run_at"))
        if next_run_dt is None:
            return False
        lock_dt = _iso_to_dt(record.get("run_lock_until"))
        current = now or _utcnow()
        if lock_dt is not None and lock_dt > current:
            return False
        return next_run_dt <= current

    def _advance_task_after_trigger(self, record: dict[str, Any], *, now: datetime | None = None, completed: bool = True) -> None:
        self._ensure_task_defaults(record)
        current = now or _utcnow()
        schedule_kind = record.get("schedule_kind", "none")
        if schedule_kind == "once" and completed:
            record["task_status"] = "done"
            record["next_run_at"] = None
            return
        if schedule_kind == "recurring" and completed:
            recurrence = record.get("recurrence") if isinstance(record.get("recurrence"), dict) else {}
            record["next_run_at"] = _next_run_from_recurrence(recurrence, record.get("timezone") or _DEFAULT_TIMEZONE, now=current)

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
        for record in self._iter_all_active_tasks():
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
        for record in self._sort_tasks(self._iter_all_active_tasks()):
            if len(claimed) >= limit:
                break
            if not self._is_task_due(record, now=current):
                continue
            if record.get("schedule_kind") not in {"once", "recurring"} and not record.get("auto_run"):
                continue
            record["run_lock_until"] = _dt_to_iso(current + timedelta(seconds=max(lease_seconds, 10)))
            record["last_run_status"] = "queued" if record.get("auto_run") else "due"
            record["last_updated_at"] = _dt_to_iso(current)
            self._append_run_history(
                record,
                {
                    "timestamp": _dt_to_iso(current),
                    "status": record["last_run_status"],
                    "summary": "Task became due and was queued by the scheduler." if record.get("auto_run") else "Task became due and is ready for notification.",
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
        record["last_run_at"] = _dt_to_iso(current)
        record["last_run_status"] = "notified" if delivered else "pending_delivery"
        record["last_run_summary"] = _normalize_text(summary)
        record["run_lock_until"] = None
        self._advance_task_after_trigger(record, now=current, completed=True)
        if not delivered and record.get("notify_policy") != "silent":
            record["pending_delivery"] = {
                "created_at": _dt_to_iso(current),
                "message": _normalize_text(summary),
                "kind": "task_due",
            }
        else:
            record["pending_delivery"] = None
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
        record["last_run_at"] = _dt_to_iso(current)
        record["last_run_status"] = "succeeded" if succeeded else "failed"
        record["last_run_summary"] = _normalize_text(summary)
        if succeeded:
            self._advance_task_after_trigger(record, now=current, completed=True)
            record["run_lock_until"] = None
        else:
            record["run_lock_until"] = _dt_to_iso(current + timedelta(seconds=max(next_retry_seconds, 60)))
        if not delivered and record.get("notify_policy") == "on_completion":
            record["pending_delivery"] = {
                "created_at": _dt_to_iso(current),
                "message": record["last_run_summary"],
                "kind": "task_completion",
            }
        elif delivered and record.get("notify_policy") == "on_completion":
            record["pending_delivery"] = None
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
                    "created_at": _normalize_text(payload.get("created_at")),
                }
            )
            record["pending_delivery"] = None
            changed = True
        if changed:
            await self._persist()
        return pending

    def _background_task_snapshot(self, record: dict[str, Any], now: datetime) -> dict[str, Any]:
        self._ensure_task_defaults(record)
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
            "minutes_until_due": minutes_until_due,
            "overdue": overdue,
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
        recent_failures: list[dict[str, Any]] = []
        recent_runs: list[dict[str, Any]] = []
        pending_delivery_count = 0
        due_candidates: list[tuple[datetime, dict[str, Any]]] = []
        urgent_due_tasks: list[tuple[datetime, dict[str, Any]]] = []
        repeated_failure_tasks: list[dict[str, Any]] = []

        for record in self._iter_all_active_tasks():
            schedule_kind = record.get("schedule_kind")
            if schedule_kind not in {"once", "recurring"} and not record.get("auto_run"):
                continue
            scheduled.append(record)
            next_run_dt = _iso_to_dt(record.get("next_run_at"))
            if next_run_dt is not None and next_run_dt <= now:
                due_count += 1
            if next_run_dt is not None and next_run_dt <= now - timedelta(minutes=5):
                overdue_count += 1
            if next_run_dt is not None:
                snapshot = self._background_task_snapshot(record, now)
                due_candidates.append((next_run_dt, snapshot))
                if next_run_dt <= now + _URGENT_DUE_WINDOW:
                    urgent_due_tasks.append((next_run_dt, snapshot))
            if record.get("pending_delivery"):
                pending_delivery_count += 1
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

        return {
            "scheduled_task_count": len(scheduled),
            "due_task_count": due_count,
            "overdue_task_count": overdue_count,
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
        return copy.deepcopy(record) if record is not None else None

    async def manage_tasks(
        self,
        action: str,
        task_key: str = "",
        summary: str = "",
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

        try:
            if normalized_action == "create":
                record = await self._create_task(
                    user_id=user_id,
                    summary=summary,
                    task_key=task_key,
                    project=project,
                    task_status=task_status or "open",
                    deadline=_normalize_text(deadline),
                    schedule_kind=schedule_kind or "none",
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
                filters = self._filters_payload(limit=1)
            elif normalized_action == "list":
                query_text = _normalize_text(query)
                project_filter = _normalize_text(project)
                status_filter = str(task_status or "").strip().lower()
                if status_filter and status_filter not in _VALID_TASK_STATUSES and status_filter != "all":
                    raise ValueError("task_status for list must be open, blocked, done, or all.")

                matched: list[dict[str, Any]] = []
                for record in self._iter_user_tasks(user_id):
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
                    task_status=status_filter or "active",
                    project=project_filter,
                    query=query_text,
                    limit=safe_limit,
                )
            elif normalized_action == "update":
                record = await self._update_task(
                    user_id=user_id,
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
                    session_id=current_session_id,
                    source=source,
                )
                tasks = [self._compact_task(record)]
                filters = self._filters_payload(limit=1)
            else:
                record = await self._update_task(
                    user_id=user_id,
                    task_key=task_key,
                    task_status="done",
                    session_id=current_session_id,
                    source=source,
                )
                record["next_run_at"] = None
                record["run_lock_until"] = None
                record["last_updated_at"] = _utcnow_iso()
                await self._persist(record, relink=False)
                tasks = [self._compact_task(record)]
                filters = self._filters_payload(limit=1)
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
