"""
Background scheduling, housekeeping, and heartbeat loops.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

try:
    import aiohttp
except ImportError:  # pragma: no cover - optional dependency
    aiohttp = None

from core.background_agent import BackgroundAgentRunner
from core.background_jobs import (
    default_job_record,
    delivery_payload,
    failure_payload,
    normalize_delivery,
    normalize_failure,
    normalize_job_record,
)
from core.background_status import (
    build_system_issue_candidates,
    build_system_issue_snapshot,
    build_temporal_attention_candidates,
    build_temporal_attention_snapshot,
)
from core.io_protocol import EventTarget, EventType, InboundEvent, OutboundEvent, SourceKind, TargetKind, make_source
from core.runtime_context import bind_event_context, reset_event_context

logger = logging.getLogger("meetyou.heart")

_URGENT_DUE_WINDOW = timedelta(hours=6)
_DEFAULT_IDLE_POKE_AFTER_SECONDS = 3600
_DEFAULT_IDLE_POKE_COOLDOWN_SECONDS = 3600
_DEFAULT_SIGNAL_COOLDOWN_SECONDS = 1800
_STALL_MIN_WINDOW = 300
_PENDING_CONSOLIDATION_STALE_WINDOW = timedelta(hours=4)
_UNSET = object()


class _FallbackClientSession:
    async def close(self):
        return None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _config_bool(value: Any, *, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


class Heart:
    def __init__(
        self,
        adapter,
        config,
        tools_manager,
        memory,
        task_manager,
        event_bus,
        exception_router,
        status_callback=None,
    ):
        self._adapter = adapter
        self._config = config
        self._tools_manager = tools_manager
        self._memory = memory
        self._task_manager = task_manager
        self._event_bus = event_bus
        self._exception_router = exception_router
        self._status_callback = status_callback
        self._agent_runner = BackgroundAgentRunner(adapter, tools_manager)
        self._session_manager = None
        self._core_services = None

        self._prompt = ""
        self._heartbeat_interval = 180
        self._housekeeping_interval = 60
        self._scheduler_interval = 15
        self._api_key = ""
        self._api_url = ""
        self._model = ""
        self._http_session: aiohttp.ClientSession | None = None
        self._source = make_source(SourceKind.HEART.value, "system")
        self._session_id = "system:heart"
        self._memory.set_housekeeping_adapter(adapter)

        self._last_scheduler_tick_at = ""
        self._last_housekeeping_at = ""
        self._last_housekeeping_error = ""
        self._last_heartbeat_at = ""
        self._last_heartbeat_decision = "ok"
        self._last_heartbeat_summary = ""
        self._last_heartbeat_error = ""
        self._last_scheduler_claim_count = 0
        self._last_heartbeat_signal_kind = "none"
        self._last_heartbeat_signal_at = ""
        self._last_heartbeat_signal_message = ""
        self._last_heartbeat_signal_fingerprint = ""
        self._last_idle_poke_at = ""
        self._last_idle_poke_session_id = ""
        self._last_idle_poke_message = ""
        self._last_proactive_delivery_at = ""
        self._last_proactive_delivery_status = ""
        self._idle_poke_enabled = True
        self._idle_poke_after_seconds = _DEFAULT_IDLE_POKE_AFTER_SECONDS
        self._idle_poke_cooldown_seconds = _DEFAULT_IDLE_POKE_COOLDOWN_SECONDS
        self._idle_context_compaction_enabled = True
        self._job_specs = {
            "scheduler": {"kind": "scheduler", "max_retries": 0},
            "housekeeping": {"kind": "housekeeping", "max_retries": 0},
            "heartbeat": {"kind": "heartbeat", "max_retries": 0},
            "background_agent": {"kind": "background_agent", "max_retries": 2},
        }
        self._jobs = {
            name: default_job_record(
                kind=spec["kind"],
                name=name,
                max_retries=spec["max_retries"],
                status_source="heart.init",
            )
            for name, spec in self._job_specs.items()
        }

    async def init_heart(self):
        await self.refresh_config()
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession() if aiohttp is not None else _FallbackClientSession()
        self._memory.set_housekeeping_adapter(self._adapter)
        logger.info(
            "Heart initialized: heartbeat=%ss housekeeping=%ss scheduler=%ss model=%s",
            self._heartbeat_interval,
            self._housekeeping_interval,
            self._scheduler_interval,
            self._model,
        )

    async def refresh_config(self):
        try:
            self._prompt = self._config.get_prompt("heartbeat")
        except Exception as exc:
            logger.error("Failed to load heartbeat prompt: %s", exc)

        self._heartbeat_interval = int(self._config.get("heartbeat_interval") or 180)
        self._housekeeping_interval = int(self._config.get("housekeeping_interval") or 60)
        self._scheduler_interval = int(self._config.get("scheduler_interval") or 15)
        self._idle_poke_enabled = _config_bool(self._config.get("heartbeat_idle_poke_enabled"), default=True)
        self._idle_poke_after_seconds = _positive_int(
            self._config.get("heartbeat_idle_poke_after_seconds"),
            default=_DEFAULT_IDLE_POKE_AFTER_SECONDS,
        )
        self._idle_poke_cooldown_seconds = _positive_int(
            self._config.get("heartbeat_idle_poke_cooldown_seconds"),
            default=_DEFAULT_IDLE_POKE_COOLDOWN_SECONDS,
        )
        self._idle_context_compaction_enabled = _config_bool(
            self._config.get("heartbeat_idle_context_compaction_enabled"),
            default=True,
        )
        self._api_url = self._config.get("heartbeat_api_url") or ""
        self._api_key = self._config.get("heartbeat_api_key") or ""
        self._model = self._config.get("heart_model") or ""
        logger.info(
            "Heart config refreshed: heartbeat=%ss housekeeping=%ss scheduler=%ss idle_poke=%s/%ss cooldown=%ss compact=%s model=%s",
            self._heartbeat_interval,
            self._housekeeping_interval,
            self._scheduler_interval,
            self._idle_poke_enabled,
            self._idle_poke_after_seconds,
            self._idle_poke_cooldown_seconds,
            self._idle_context_compaction_enabled,
            self._model,
        )

    def set_adapter(self, adapter):
        self._adapter = adapter
        self._memory.set_housekeeping_adapter(adapter)
        self._agent_runner = BackgroundAgentRunner(adapter, self._tools_manager)

    def set_session_manager(self, session_manager):
        self._session_manager = session_manager

    def set_core_services(self, core_services):
        self._core_services = core_services

    async def close_heart(self):
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
        logger.info("Heart closed")

    async def _set_status(self, status: str, detail: str = ""):
        if self._status_callback:
            await self._status_callback(status, detail)

    def _job_record(self, name: str) -> dict[str, Any]:
        spec = self._job_specs.get(name, {"kind": name, "max_retries": 0})
        job = normalize_job_record(
            self._jobs.get(name),
            kind=spec["kind"],
            name=name,
            max_retries=spec["max_retries"],
            status_source="heart.init",
        )
        self._jobs[name] = job
        return job

    def _bind_job_context(self, job_id: str):
        return bind_event_context(
            trace_id=uuid4().hex,
            session_id=self._session_id,
            source=self._source,
            job_id=job_id,
        )

    def _update_job(
        self,
        name: str,
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
        job = self._job_record(name)
        if increment_attempt:
            job["attempt_count"] = max(int(job.get("attempt_count", 0) or 0), 0) + 1
        if status is not _UNSET:
            normalized_status = str(status or "").strip().lower()
            if normalized_status:
                job["status"] = normalized_status
        if runtime_source is not _UNSET:
            normalized_source = str(runtime_source or "").strip()
            job["last_runtime_source"] = normalized_source
            job["status_source"] = normalized_source
        if started_at is not _UNSET:
            job["last_started_at"] = str(started_at or "").strip() or None
        if finished_at is not _UNSET:
            job["last_finished_at"] = str(finished_at or "").strip() or None
        if success_at is not _UNSET:
            job["last_success_at"] = str(success_at or "").strip() or None
        if next_retry_at is not _UNSET:
            job["next_retry_at"] = str(next_retry_at or "").strip() or None
        if retry_count is not _UNSET:
            try:
                job["retry_count"] = max(int(retry_count or 0), 0)
            except (TypeError, ValueError):
                job["retry_count"] = 0
        if last_result is not _UNSET:
            job["last_result"] = dict(last_result) if isinstance(last_result, dict) else {}
        if last_failure is not _UNSET:
            job["last_failure"] = normalize_failure(last_failure)
        if last_delivery is not _UNSET:
            job["last_delivery"] = normalize_delivery(last_delivery)
        if metadata is not _UNSET:
            job["metadata"] = dict(metadata) if isinstance(metadata, dict) else {}
        self._jobs[name] = job
        return job

    def _pending_consolidation_snapshot(self) -> dict[str, Any]:
        pending = [
            record
            for record in self._memory._store.get("records", [])
            if record.get("type") == "episode" and "pending_consolidation" in record.get("tags", [])
        ]
        oldest = ""
        if pending:
            oldest = min(str(record.get("created_at") or "") for record in pending)
        return {
            "pending_consolidation_count": len(pending),
            "oldest_pending_consolidation_at": oldest,
        }

    def _latest_user_activity(self) -> dict[str, Any]:
        if self._session_manager is None:
            return {
                "last_user_activity_at": "",
                "recent_user_session_id": "",
                "recent_user_target_kind": "",
            }

        list_recent = getattr(self._session_manager, "list_recent_bindings", None)
        if not callable(list_recent):
            return {
                "last_user_activity_at": "",
                "recent_user_session_id": "",
                "recent_user_target_kind": "",
            }

        for binding in list_recent():
            session_id = str(getattr(binding, "session_id", "") or "").strip()
            if not session_id or session_id.startswith("system:"):
                continue
            source = getattr(binding, "source", None)
            source_kind = str(getattr(source, "kind", "") or "").strip().lower()
            if source_kind not in {SourceKind.WEB.value, SourceKind.FEISHU.value, SourceKind.WECHAT.value, SourceKind.CLI.value}:
                continue
            last_active = str(getattr(binding, "metadata", {}).get("last_active_at", "") or "").strip()
            try:
                last_active_iso = (
                    datetime.fromtimestamp(float(last_active), tz=timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
            except (TypeError, ValueError, OSError):
                last_active_iso = ""
            target = getattr(binding, "default_target", None)
            return {
                "last_user_activity_at": last_active_iso,
                "recent_user_session_id": session_id,
                "recent_user_target_kind": str(getattr(target, "kind", "") or ""),
            }

        return {
            "last_user_activity_at": "",
            "recent_user_session_id": "",
            "recent_user_target_kind": "",
        }

    @staticmethod
    def _loop_stalled(last_seen_at: str, interval_seconds: int) -> bool:
        last_seen = _iso_to_dt(last_seen_at)
        if last_seen is None:
            return False
        grace_seconds = max(int(interval_seconds or 0) * 4, _STALL_MIN_WINDOW)
        return last_seen <= datetime.now(timezone.utc) - timedelta(seconds=grace_seconds)

    @staticmethod
    def _pending_consolidation_stale(snapshot: dict[str, Any]) -> bool:
        oldest = _iso_to_dt(snapshot.get("oldest_pending_consolidation_at"))
        if oldest is None:
            return False
        return oldest <= datetime.now(timezone.utc) - _PENDING_CONSOLIDATION_STALE_WINDOW

    def _build_system_issue_candidates(self, payload: dict[str, Any]) -> list[str]:
        return build_system_issue_candidates(payload)

    def _build_temporal_attention_candidates(self, payload: dict[str, Any]) -> list[str]:
        return build_temporal_attention_candidates(payload)

    @staticmethod
    def _normalize_signal_kind(value: Any) -> str:
        normalized = str(value or "none").strip().lower() or "none"
        if normalized == "urgent_deadline":
            normalized = "temporal_attention"
        if normalized not in {"none", "system_issue", "temporal_attention", "idle_poke"}:
            return "none"
        return normalized

    @staticmethod
    def _sanitize_message(text: Any, *, single_sentence: bool = False) -> str:
        raw = str(text or "").replace("\r", " ").strip()
        if not raw:
            return ""
        lines = [line.strip() for line in raw.split("\n") if line.strip()]
        raw = re.sub(r"\s+", " ", " ".join(lines)).strip()
        if single_sentence:
            for sep in ("。", "！", "？", ".", "!", "?"):
                if sep in raw:
                    prefix = raw.split(sep, 1)[0].strip()
                    if prefix:
                        raw = prefix + (sep if sep in {"。", "！", "？"} else "")
                    break
        return raw[:120].strip()

    def _fallback_signal_message(self, signal_kind: str, payload: dict[str, Any]) -> str:
        if signal_kind == "system_issue":
            if payload.get("repeated_failure_tasks"):
                task = payload["repeated_failure_tasks"][0]
                summary = str(task.get("summary") or task.get("task_key") or "后台任务").strip()
                return f"任务“{summary}”已连续失败，可能需要检查。"
            if payload.get("scheduler_stalled"):
                return "调度器长时间没有活动，可能影响定时任务触发。"
            if payload.get("housekeeping_stalled"):
                return "Housekeeping 长时间没有活动，可能影响后台整理。"
            if payload.get("pending_consolidation_stale"):
                return "待整理记忆已积压过久，可能影响后台状态判断。"
            if str(payload.get("last_housekeeping_error") or "").strip():
                return "后台整理出现错误，可能影响任务执行或提醒。"
            return "后台出现了可能影响任务执行的异常，建议检查。"
        if signal_kind == "temporal_attention":
            pending_delivery_tasks = payload.get("delivery", {}).get("pending_redelivery_tasks") or payload.get(
                "pending_redelivery_tasks"
            ) or []
            if pending_delivery_tasks:
                task = pending_delivery_tasks[0]
                summary = str(task.get("summary") or task.get("task_key") or "定时提醒").strip()
                return f"已触发的事项“{summary}”仍在等待送达，可能需要尽快跟进。"
            awaiting_completion_tasks = payload.get("execution", {}).get("awaiting_completion_tasks") or payload.get(
                "awaiting_completion_tasks"
            ) or []
            if awaiting_completion_tasks:
                task = awaiting_completion_tasks[0]
                summary = str(task.get("summary") or task.get("task_key") or "定时任务").strip()
                if task.get("auto_run"):
                    return f"定时任务“{summary}”已执行，但仍等待完成确认。"
                return f"定时事项“{summary}”已触发，但仍等待完成确认。"
            nearest_due_task = payload.get("nearest_due_task") if isinstance(payload.get("nearest_due_task"), dict) else {}
            if nearest_due_task and nearest_due_task.get("overdue"):
                summary = str(nearest_due_task.get("summary") or nearest_due_task.get("task_key") or "定时事项").strip()
                return f"定时事项“{summary}”已经逾期，可能需要尽快处理。"
            return "后台存在需要时间关注的定时事项，建议尽快检查。"
        if signal_kind == "idle_poke":
            return "当前没有紧急事项，用户已沉默较久，可用一句自然短句确认是否需要帮助。"
        return ""

    def _canonical_signal_message(self, signal_kind: str, payload: dict[str, Any]) -> str:
        if signal_kind == "system_issue":
            if payload.get("repeated_failure_tasks"):
                task = payload["repeated_failure_tasks"][0]
                summary = str(task.get("summary") or task.get("task_key") or "background task").strip()
                return f'Task "{summary}" has failed repeatedly. Keep the follow-up brief and practical.'
            if payload.get("scheduler_stalled"):
                return (
                    "The scheduler looks stalled and scheduled jobs may stop firing. "
                    "Keep the follow-up brief and practical."
                )
            if payload.get("housekeeping_stalled"):
                return (
                    "Background housekeeping looks stalled. "
                    "Mention it only if it may affect task execution or reminders."
                )
            if payload.get("pending_consolidation_stale"):
                return (
                    "Pending memory consolidation has been stale for too long. "
                    "Mention it only if it may affect memory freshness or reminders."
                )
            if str(payload.get("last_housekeeping_error") or "").strip():
                return "Background housekeeping is erroring. Keep the follow-up short and action-oriented."
            return (
                "There is a concrete background issue that may affect task execution or reminders. "
                "Keep the follow-up short."
            )
        if signal_kind == "temporal_attention":
            pending_delivery_tasks = payload.get("delivery", {}).get("pending_redelivery_tasks") or payload.get(
                "pending_redelivery_tasks"
            ) or []
            if pending_delivery_tasks:
                task = pending_delivery_tasks[0]
                summary = str(task.get("summary") or task.get("task_key") or "scheduled follow-up").strip()
                return (
                    f'Triggered follow-up "{summary}" is still waiting to be delivered. '
                    "Keep the follow-up brief and practical."
                )
            awaiting_completion_tasks = payload.get("execution", {}).get("awaiting_completion_tasks") or payload.get(
                "awaiting_completion_tasks"
            ) or []
            if awaiting_completion_tasks:
                task = awaiting_completion_tasks[0]
                summary = str(task.get("summary") or task.get("task_key") or "scheduled task").strip()
                if task.get("auto_run"):
                    return (
                        f'Scheduled task "{summary}" has run and is still waiting for completion confirmation. '
                        "Keep the follow-up brief and practical."
                    )
                return (
                    f'Scheduled follow-up "{summary}" is still waiting for completion confirmation. '
                    "Keep the follow-up brief and practical."
                )
            nearest_due_task = payload.get("nearest_due_task") if isinstance(payload.get("nearest_due_task"), dict) else {}
            if nearest_due_task and nearest_due_task.get("overdue"):
                summary = str(nearest_due_task.get("summary") or nearest_due_task.get("task_key") or "scheduled follow-up").strip()
                return (
                    f'Scheduled follow-up "{summary}" is overdue. '
                    "Keep the follow-up brief and practical."
                )
            return (
                "There is a time-sensitive scheduled follow-up that may need attention. "
                "Keep the follow-up brief and practical."
            )
        if signal_kind == "idle_poke":
            return "There is no critical system issue. A single short casual check-in is enough."
        return self._fallback_signal_message(signal_kind, payload)

    def _signal_cooldown_seconds(self, signal_kind: str) -> int:
        if signal_kind == "idle_poke":
            return self._idle_poke_cooldown_seconds
        return _DEFAULT_SIGNAL_COOLDOWN_SECONDS

    def get_idle_poke_settings_snapshot(self) -> dict[str, Any]:
        return {
            "heartbeat_idle_poke_enabled": self._idle_poke_enabled,
            "heartbeat_idle_poke_after_seconds": self._idle_poke_after_seconds,
            "heartbeat_idle_poke_cooldown_seconds": self._idle_poke_cooldown_seconds,
            "heartbeat_idle_context_compaction_enabled": self._idle_context_compaction_enabled,
            "last_idle_poke_at": self._last_idle_poke_at,
            "last_idle_poke_session_id": self._last_idle_poke_session_id,
            "last_idle_poke_message": self._last_idle_poke_message,
            "last_proactive_delivery_at": self._last_proactive_delivery_at,
            "last_proactive_delivery_status": self._last_proactive_delivery_status,
        }

    def record_idle_poke_delivery(self, *, session_id: str, message: str, delivered: bool) -> None:
        self._last_idle_poke_session_id = str(session_id or "").strip()
        self._last_idle_poke_message = str(message or "").strip()
        self._last_proactive_delivery_at = _utcnow_iso()
        self._last_proactive_delivery_status = "delivered" if delivered else "persisted_or_skipped"

    def _signal_fingerprint(self, signal_kind: str, payload: dict[str, Any]) -> str:
        if signal_kind == "system_issue":
            issues: list[str] = []
            repeated_failure_tasks = payload.get("repeated_failure_tasks") or []
            repeated_task_keys = [
                str(task.get("task_key") or task.get("summary") or "").strip()
                for task in repeated_failure_tasks
                if str(task.get("task_key") or task.get("summary") or "").strip()
            ]
            if repeated_task_keys:
                issues.append("repeated:" + ",".join(sorted(dict.fromkeys(repeated_task_keys))[:3]))
            if payload.get("scheduler_stalled"):
                issues.append("scheduler_stalled")
            if payload.get("housekeeping_stalled"):
                issues.append("housekeeping_stalled")
            if payload.get("pending_consolidation_stale"):
                issues.append("pending_consolidation_stale")
            if str(payload.get("last_housekeeping_error") or "").strip():
                issues.append("housekeeping_error")
            if issues:
                return "system_issue:" + "|".join(issues)
        if signal_kind == "temporal_attention":
            issues: list[str] = []
            if int(payload.get("pending_delivery_count") or 0) > 0:
                issues.append(f"pending_delivery:{int(payload.get('pending_delivery_count') or 0)}")
            if int(payload.get("awaiting_completion_count") or 0) > 0:
                issues.append(f"awaiting_completion:{int(payload.get('awaiting_completion_count') or 0)}")
            if int(payload.get("run_succeeded_pending_completion_count") or 0) > 0:
                issues.append(
                    "completion_confirmation_pending:"
                    + str(int(payload.get("run_succeeded_pending_completion_count") or 0))
                )
            if int(payload.get("overdue_task_count") or 0) > 0:
                issues.append(f"overdue:{int(payload.get('overdue_task_count') or 0)}")
            if issues:
                return "temporal_attention:" + "|".join(issues)
        if signal_kind == "idle_poke":
            session_id = str(payload.get("recent_user_session_id") or "").strip()
            last_user_activity_at = str(payload.get("last_user_activity_at") or "").strip()
            if session_id or last_user_activity_at:
                return f"idle_poke:{session_id}|{last_user_activity_at}"
        single_sentence = signal_kind == "idle_poke"
        message = self._sanitize_message(
            self._canonical_signal_message(signal_kind, payload),
            single_sentence=single_sentence,
        )
        return f"{signal_kind}:{message}"

    def _signal_in_cooldown(self, signal_kind: str, signal_fingerprint: str, message: str) -> bool:
        last_sent_at = _iso_to_dt(self._last_heartbeat_signal_at)
        if last_sent_at is None:
            return False
        if self._last_heartbeat_signal_kind != signal_kind:
            return False
        if self._last_heartbeat_signal_fingerprint:
            if self._last_heartbeat_signal_fingerprint != signal_fingerprint:
                return False
        elif self._last_heartbeat_signal_message != message:
            return False
        cooldown = timedelta(seconds=self._signal_cooldown_seconds(signal_kind))
        return last_sent_at > datetime.now(timezone.utc) - cooldown

    def _normalize_heartbeat_result(self, payload: dict[str, Any], background_status: dict[str, Any]) -> dict[str, Any]:
        decision = str(payload.get("decision") or "ok").strip().lower() or "ok"
        if decision not in {"ok", "notify", "escalate"}:
            decision = "ok"

        signal_kind = self._normalize_signal_kind(payload.get("signal_kind"))
        if decision == "ok":
            signal_kind = "none"

        system_issue_candidates = self._build_system_issue_candidates(background_status)
        temporal_attention_candidates = self._build_temporal_attention_candidates(background_status)
        has_recent_user_session = bool(str(background_status.get("last_user_activity_at") or "").strip())
        idle_poke_eligible = bool(background_status.get("idle_poke_eligible"))

        if signal_kind == "system_issue" and not system_issue_candidates:
            decision = "ok"
            signal_kind = "none"
        elif signal_kind == "temporal_attention" and not temporal_attention_candidates:
            decision = "ok"
            signal_kind = "none"
        elif signal_kind == "idle_poke" and not idle_poke_eligible:
            decision = "ok"
            signal_kind = "none"
        elif signal_kind != "none" and not has_recent_user_session:
            decision = "ok"
            signal_kind = "none"

        single_sentence = signal_kind == "idle_poke"
        message = ""
        signal_fingerprint = ""
        if decision != "ok" and signal_kind != "none":
            message = self._sanitize_message(
                self._canonical_signal_message(signal_kind, background_status),
                single_sentence=single_sentence,
            )
            signal_fingerprint = self._signal_fingerprint(signal_kind, background_status)

        if decision == "ok" or signal_kind == "none":
            message = ""
            signal_kind = "none"
            signal_fingerprint = ""
            decision = "ok"

        if message and signal_fingerprint and self._signal_in_cooldown(signal_kind, signal_fingerprint, message):
            message = ""
            signal_kind = "none"
            signal_fingerprint = ""
            decision = "ok"

        return {
            "decision": decision,
            "signal_kind": signal_kind,
            "message": message,
            "signal_fingerprint": signal_fingerprint,
            "reasons": list(payload.get("reasons") or []),
            "confidence": str(payload.get("confidence") or "medium").strip().lower() or "medium",
        }

    async def get_background_status(self) -> dict[str, Any]:
        payload = self._task_manager.build_background_status()
        pending_snapshot = self._pending_consolidation_snapshot()
        payload.update(pending_snapshot)
        payload.update(self._latest_user_activity())
        job_snapshots = {name: self._job_record(name) for name in self._job_specs}
        job_status_counts: dict[str, int] = {}
        job_failures: list[dict[str, Any]] = []
        for name, snapshot in job_snapshots.items():
            status = str(snapshot.get("status") or "idle").strip().lower() or "idle"
            job_status_counts[status] = int(job_status_counts.get(status, 0) or 0) + 1
            last_failure = normalize_failure(snapshot.get("last_failure"))
            if last_failure:
                job_failures.append(
                    {
                        "job_name": name,
                        "job_kind": snapshot.get("kind"),
                        "status": status,
                        "failure": last_failure,
                    }
                )
        scheduler_stalled = self._loop_stalled(self._last_scheduler_tick_at, self._scheduler_interval)
        housekeeping_stalled = self._loop_stalled(self._last_housekeeping_at, self._housekeeping_interval)
        pending_consolidation_stale = self._pending_consolidation_stale(pending_snapshot)
        last_user_activity_at = _iso_to_dt(payload.get("last_user_activity_at"))
        now = datetime.now(timezone.utc)
        last_idle_poke_at = _iso_to_dt(self._last_idle_poke_at)
        has_recent_user_session = bool(payload.get("last_user_activity_at"))
        idle_window = timedelta(seconds=self._idle_poke_after_seconds)
        idle_window_ready = bool(last_user_activity_at and last_user_activity_at <= now - idle_window)
        idle_cooldown_ready = bool(
            last_idle_poke_at is None or last_idle_poke_at <= now - timedelta(seconds=self._idle_poke_cooldown_seconds)
        )
        payload["scheduler_stalled"] = scheduler_stalled
        payload["housekeeping_stalled"] = housekeeping_stalled
        payload["pending_consolidation_stale"] = pending_consolidation_stale
        payload["last_housekeeping_error"] = self._last_housekeeping_error
        payload["jobs"] = job_snapshots
        payload["job_status_counts"] = job_status_counts
        payload["job_failures"] = job_failures
        issue_payload = {
            **payload,
            "scheduler_stalled": scheduler_stalled,
            "housekeeping_stalled": housekeeping_stalled,
            "pending_consolidation_stale": pending_consolidation_stale,
            "last_housekeeping_error": self._last_housekeeping_error,
        }
        payload["system_issue_candidates"] = self._build_system_issue_candidates(issue_payload)
        payload["temporal_attention_candidates"] = self._build_temporal_attention_candidates(issue_payload)
        payload["system"] = {
            **build_system_issue_snapshot(issue_payload),
            "jobs": job_snapshots,
            "job_status_counts": job_status_counts,
            "job_failures": job_failures,
        }
        payload["temporal"] = build_temporal_attention_snapshot(issue_payload)
        payload["last_idle_poke_at"] = self._last_idle_poke_at
        payload["last_idle_poke_session_id"] = self._last_idle_poke_session_id
        payload["last_idle_poke_message"] = self._last_idle_poke_message
        payload["last_proactive_delivery_at"] = self._last_proactive_delivery_at
        payload["last_proactive_delivery_status"] = self._last_proactive_delivery_status
        payload["heartbeat_idle_poke_enabled"] = self._idle_poke_enabled
        payload["heartbeat_idle_poke_after_seconds"] = self._idle_poke_after_seconds
        payload["heartbeat_idle_poke_cooldown_seconds"] = self._idle_poke_cooldown_seconds
        payload["heartbeat_idle_context_compaction_enabled"] = self._idle_context_compaction_enabled
        payload["idle_poke_after_seconds"] = self._idle_poke_after_seconds
        payload["idle_poke_cooldown_seconds"] = self._idle_poke_cooldown_seconds
        payload["idle_poke_window_ready"] = idle_window_ready
        payload["idle_poke_cooldown_ready"] = idle_cooldown_ready
        payload["idle_poke_eligible"] = bool(
            self._idle_poke_enabled
            and has_recent_user_session
            and idle_window_ready
            and idle_cooldown_ready
            and not payload["system_issue_candidates"]
        )
        payload["background_status_sources"] = list(
            dict.fromkeys(
                list(payload.get("background_status_sources") or [])
                + [
                    "task_manager.user_todo",
                    "heart.job_runtime",
                    "memory.pending_consolidation",
                    "session.latest_user_activity",
                ]
            )
        )
        payload.update(
            {
                "heartbeat_interval": self._heartbeat_interval,
                "housekeeping_interval": self._housekeeping_interval,
                "scheduler_interval": self._scheduler_interval,
                "last_scheduler_tick_at": self._last_scheduler_tick_at,
                "last_scheduler_claim_count": self._last_scheduler_claim_count,
                "last_housekeeping_at": self._last_housekeeping_at,
                "last_heartbeat_at": self._last_heartbeat_at,
                "last_heartbeat_decision": self._last_heartbeat_decision,
                "last_heartbeat_summary": self._last_heartbeat_summary,
                "last_heartbeat_error": self._last_heartbeat_error,
                "last_heartbeat_signal_kind": self._last_heartbeat_signal_kind,
                "last_heartbeat_signal_at": self._last_heartbeat_signal_at,
                "inbound_queue_size": self._event_bus.inbound_queue.qsize(),
            }
        )
        return payload

    async def housekeeping_processor(self):
        shutdown = self._event_bus.shutdown_event
        while True:
            if shutdown.is_set() or self._http_session is None:
                break
            started_at = _utcnow_iso()
            token = self._bind_job_context("housekeeping")
            try:
                try:
                    self._update_job(
                        "housekeeping",
                        status="running",
                        runtime_source="heart.housekeeping",
                        started_at=started_at,
                        increment_attempt=True,
                    )
                    await self._memory.run_housekeeping(
                        self._http_session,
                        self._api_url,
                        self._api_key,
                        self._model,
                    )
                    attachment_cleanup_result = {
                        "expired_download_tickets": 0,
                        "expired_upload_tickets": 0,
                        "expired_attachments": 0,
                        "deleted_objects": 0,
                    }
                    attachment_service = getattr(self._core_services, "attachment", None) if self._core_services is not None else None
                    if attachment_service is not None:
                        cleanup_expired_resources = getattr(attachment_service, "cleanup_expired_resources", None)
                        if callable(cleanup_expired_resources):
                            attachment_cleanup_result = dict(cleanup_expired_resources() or attachment_cleanup_result)
                    self._last_housekeeping_at = _utcnow_iso()
                    self._last_housekeeping_error = ""
                    self._update_job(
                        "housekeeping",
                        status="succeeded",
                        runtime_source="heart.housekeeping",
                        finished_at=self._last_housekeeping_at,
                        success_at=self._last_housekeeping_at,
                        next_retry_at=None,
                        retry_count=0,
                        last_failure=None,
                        last_result={
                            "status": "ok",
                            "at": self._last_housekeeping_at,
                            "attachments": attachment_cleanup_result,
                        },
                        last_delivery=delivery_payload(state="not_applicable"),
                    )
                except Exception as exc:
                    self._last_housekeeping_error = str(exc)
                    logger.error("Memory housekeeping failed: %s", exc)
                    failed_at = _utcnow_iso()
                    self._update_job(
                        "housekeeping",
                        status="failed",
                        runtime_source="heart.housekeeping",
                        finished_at=failed_at,
                        next_retry_at=None,
                        retry_count=int(self._job_record("housekeeping").get("retry_count", 0) or 0) + 1,
                        last_failure=failure_payload(
                            category="retryable",
                            code="housekeeping_failed",
                            message=str(exc),
                            at=failed_at,
                        ),
                        last_result={"status": "error", "message": str(exc), "at": failed_at},
                        last_delivery=delivery_payload(state="not_applicable"),
                    )
            finally:
                reset_event_context(token)

            try:
                await asyncio.wait_for(shutdown.wait(), timeout=max(self._housekeeping_interval, 1))
                break
            except asyncio.TimeoutError:
                pass

    def _heartbeat_route_context(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "tool_bundle": [
                str(tool.get("function", {}).get("name", "")).strip()
                for tool in tools
                if str(tool.get("function", {}).get("name", "")).strip()
            ],
            "mcp_servers": [],
        }

    @staticmethod
    def _extract_json_payload(text: str) -> dict[str, Any] | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start:end + 1]
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    async def heartbeat_processor(self, *, once: bool = True):
        if not once:
            logger.warning("Heartbeat processor is one-shot in V4; Scheduler owns the heartbeat clock.")
            once = True
        shutdown = self._event_bus.shutdown_event

        while True:
            if shutdown.is_set() or self._http_session is None:
                break

            if not self._tools_manager.tools_schema_dict:
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=1.0)
                    break
                except asyncio.TimeoutError:
                    continue

            if self._api_url and self._model:
                started_at = _utcnow_iso()
                token = self._bind_job_context("heartbeat")
                try:
                    try:
                        await self._set_status("heartbeat", "Running heartbeat")
                        self._update_job(
                            "heartbeat",
                            status="running",
                            runtime_source="heart.heartbeat",
                            started_at=started_at,
                            increment_attempt=True,
                        )
                        tools = self._tools_manager.get_heartbeat_tools()
                        background_status = await self.get_background_status()
                        self._update_job(
                            "background_agent",
                            status="running",
                            runtime_source="heart.background_agent",
                            started_at=started_at,
                            increment_attempt=True,
                        )
                        agent_token = bind_event_context(job_id="background_agent")
                        try:
                            result = await self._agent_runner.run(
                                session=self._http_session,
                                api_url=self._api_url,
                                api_key=self._api_key,
                                model=self._model,
                                messages=[
                                    {"role": "system", "content": self._prompt},
                                    {"role": "user", "content": json.dumps(background_status, ensure_ascii=False)},
                                ],
                                tools=tools,
                                session_id=self._session_id,
                                source=self._source,
                                route_context=self._heartbeat_route_context(tools),
                                max_rounds=6,
                            )
                        finally:
                            reset_event_context(agent_token)
                        agent_finished_at = _utcnow_iso()
                        agent_error = result.get("error") if isinstance(result.get("error"), dict) else None
                        if agent_error:
                            self._update_job(
                                "background_agent",
                                status="failed",
                                runtime_source="heart.background_agent",
                                finished_at=agent_finished_at,
                                next_retry_at=None,
                                retry_count=int(self._job_record("background_agent").get("retry_count", 0) or 0) + 1,
                                last_failure=agent_error,
                                last_result={"status": result.get("status"), "content": result.get("content"), "at": agent_finished_at},
                                last_delivery=delivery_payload(state="not_applicable"),
                            )
                        else:
                            self._update_job(
                                "background_agent",
                                status="succeeded",
                                runtime_source="heart.background_agent",
                                finished_at=agent_finished_at,
                                success_at=agent_finished_at,
                                next_retry_at=None,
                                retry_count=0,
                                last_failure=None,
                                last_result={"status": result.get("status"), "content": result.get("content"), "at": agent_finished_at},
                                last_delivery=delivery_payload(state="not_applicable"),
                            )

                        payload = self._extract_json_payload(result.get("content") or "")
                        if payload is None:
                            raise ValueError(f"Heartbeat returned non-JSON content: {result.get('content')}")

                        normalized = self._normalize_heartbeat_result(payload, background_status)
                        decision = normalized["decision"]
                        signal_kind = normalized["signal_kind"]
                        message = normalized["message"]
                        signal_fingerprint = normalized["signal_fingerprint"]
                        self._last_heartbeat_at = _utcnow_iso()
                        self._last_heartbeat_decision = decision
                        self._last_heartbeat_summary = message
                        self._last_heartbeat_error = ""
                        heartbeat_delivery = delivery_payload(state="not_applicable")

                        if decision in {"notify", "escalate"} and message:
                            emitted_at = _utcnow_iso()
                            self._last_heartbeat_signal_kind = signal_kind
                            self._last_heartbeat_signal_message = message
                            self._last_heartbeat_signal_fingerprint = signal_fingerprint
                            self._last_heartbeat_signal_at = emitted_at
                            if signal_kind == "idle_poke":
                                self._last_idle_poke_at = emitted_at
                            signal_metadata = {
                                "heartbeat_decision": decision,
                                "heartbeat_signal_kind": signal_kind,
                                "transient": True,
                                "disable_tools": True,
                            }
                            if signal_kind == "idle_poke":
                                signal_metadata.update(
                                    {
                                        "heartbeat_direct_delivery": True,
                                        "heartbeat_context_compaction_enabled": self._idle_context_compaction_enabled,
                                        "recent_user_session_id": str(background_status.get("recent_user_session_id") or ""),
                                        "last_user_activity_at": str(background_status.get("last_user_activity_at") or ""),
                                    }
                                )
                            await self._event_bus.inbound_queue.put(
                                InboundEvent(
                                    session_id=self._session_id,
                                    type=EventType.SIGNAL.value,
                                    role="system",
                                    content=message,
                                    source=self._source,
                                    target=EventTarget(kind=TargetKind.INTERNAL.value),
                                    metadata=signal_metadata,
                                )
                            )
                            heartbeat_delivery = delivery_payload(
                                state="delivered",
                                delivered=True,
                                channel="internal_signal",
                                message=message,
                                at=emitted_at,
                                details={"signal_kind": signal_kind, "decision": decision},
                            )
                        self._update_job(
                            "heartbeat",
                            status="succeeded",
                            runtime_source="heart.heartbeat",
                            finished_at=self._last_heartbeat_at,
                            success_at=self._last_heartbeat_at,
                            next_retry_at=None,
                            retry_count=0,
                            last_failure=None,
                            last_result={
                                "status": decision,
                                "signal_kind": signal_kind,
                                "message": message,
                                "at": self._last_heartbeat_at,
                            },
                            last_delivery=heartbeat_delivery,
                        )
                    except Exception as exc:
                        logger.error("Heartbeat request failed: %s", exc)
                        self._last_heartbeat_at = _utcnow_iso()
                        self._last_heartbeat_error = str(exc)
                        self._update_job(
                            "heartbeat",
                            status="failed",
                            runtime_source="heart.heartbeat",
                            finished_at=self._last_heartbeat_at,
                            next_retry_at=None,
                            retry_count=int(self._job_record("heartbeat").get("retry_count", 0) or 0) + 1,
                            last_failure=failure_payload(
                                category="retryable",
                                code="heartbeat_failed",
                                message=str(exc),
                                at=self._last_heartbeat_at,
                            ),
                            last_result={"status": "error", "message": str(exc), "at": self._last_heartbeat_at},
                            last_delivery=delivery_payload(state="not_applicable"),
                        )
                        await self._set_status("error", str(exc))
                    finally:
                        await self._set_status("idle", "")
                finally:
                    reset_event_context(token)
            else:
                logger.warning("Heartbeat config incomplete (api_url or model missing), skipping heartbeat model call")

            if once:
                break
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=max(self._heartbeat_interval, 1))
                break
            except asyncio.TimeoutError:
                pass
