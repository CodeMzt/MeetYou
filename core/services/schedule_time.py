from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def ensure_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_timezone(value: str) -> ZoneInfo | timezone:
    name = str(value or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def _parse_time_of_day(value: str) -> time:
    text = str(value or "08:00").strip() or "08:00"
    parts = text.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        hour, minute = 8, 0
    return time(hour=max(0, min(hour, 23)), minute=max(0, min(minute, 59)))


def _time_of_day_value(config: dict | None) -> str | None:
    payload = dict(config or {})
    for key in ("time_of_day", "at", "time", "daily_time", "run_time"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip()
    if "hour" in payload or "minute" in payload:
        return f"{payload.get('hour', 0)}:{payload.get('minute', 0)}"
    return None


def canonical_time_of_day(value: str | int | None = None, *, default: str = "08:00") -> str:
    parsed = _parse_time_of_day(str(value if value not in (None, "") else default))
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def normalize_daily_trigger_config(
    trigger_config: dict | None,
    *,
    fallback_config: dict | None = None,
    default_time_of_day: str = "08:00",
) -> dict:
    value = _time_of_day_value(trigger_config)
    if value is None:
        value = _time_of_day_value(fallback_config)
    return {"type": "daily", "time_of_day": canonical_time_of_day(value, default=default_time_of_day)}


def _parse_iso_datetime(value: str, *, tz) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(timezone.utc)


def _field_matches(value: int, expression: str, *, min_value: int, max_value: int) -> bool:
    text = str(expression or "*").strip()
    if not text or text == "*":
        return True
    for part in text.split(","):
        token = part.strip()
        if not token:
            continue
        step = 1
        if "/" in token:
            token, raw_step = token.split("/", 1)
            try:
                step = max(int(raw_step), 1)
            except ValueError:
                step = 1
        if token == "*":
            start, end = min_value, max_value
        elif "-" in token:
            raw_start, raw_end = token.split("-", 1)
            try:
                start, end = int(raw_start), int(raw_end)
            except ValueError:
                continue
        else:
            try:
                start = end = int(token)
            except ValueError:
                continue
        start = max(start, min_value)
        end = min(end, max_value)
        if start <= value <= end and (value - start) % step == 0:
            return True
    return False


def _cron_next_after(expression: str, *, after: datetime, tz) -> datetime | None:
    fields = str(expression or "").strip().split()
    if len(fields) != 5:
        return None
    local = after.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = local + timedelta(days=366)
    while local <= end:
        minute, hour, day, month = local.minute, local.hour, local.day, local.month
        # Python Monday=0; cron Sunday is commonly 0 or 7.
        dow = (local.weekday() + 1) % 7
        cron_dow_match = _field_matches(dow, fields[4], min_value=0, max_value=7) or (
            dow == 0 and _field_matches(7, fields[4], min_value=0, max_value=7)
        )
        if (
            _field_matches(minute, fields[0], min_value=0, max_value=59)
            and _field_matches(hour, fields[1], min_value=0, max_value=23)
            and _field_matches(day, fields[2], min_value=1, max_value=31)
            and _field_matches(month, fields[3], min_value=1, max_value=12)
            and cron_dow_match
        ):
            return local.astimezone(timezone.utc)
        local += timedelta(minutes=1)
    return None


def compute_next_fire_at(
    *,
    trigger_type: str,
    trigger_config: dict | None,
    timezone_name: str = "UTC",
    after: datetime | None = None,
) -> datetime | None:
    now = ensure_utc(after)
    config = dict(trigger_config or {})
    kind = str(trigger_type or config.get("type") or "interval").strip().lower() or "interval"
    tz = parse_timezone(timezone_name)

    if kind == "interval":
        try:
            interval_seconds = int(config.get("interval_seconds") or 0)
        except (TypeError, ValueError):
            interval_seconds = 0
        return now + timedelta(seconds=interval_seconds) if interval_seconds > 0 else None

    if kind == "daily":
        local_now = now.astimezone(tz)
        target_time = _parse_time_of_day(_time_of_day_value(config) or "08:00")
        candidate = local_now.replace(
            hour=target_time.hour,
            minute=target_time.minute,
            second=0,
            microsecond=0,
        )
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)

    if kind == "one_shot":
        run_at = _parse_iso_datetime(str(config.get("run_at") or config.get("at") or ""), tz=tz)
        if run_at is None or run_at <= now:
            return None
        return run_at

    if kind == "cron":
        expression = str(config.get("expression") or config.get("cron") or "").strip()
        return _cron_next_after(expression, after=now, tz=tz)

    return None
