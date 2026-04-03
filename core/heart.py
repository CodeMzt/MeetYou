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

try:
    import aiohttp
except ImportError:  # pragma: no cover - optional dependency
    aiohttp = None

from core.background_agent import BackgroundAgentRunner
from core.io_protocol import EventTarget, EventType, InboundEvent, SourceKind, TargetKind, make_source

logger = logging.getLogger("meetyou.heart")

_URGENT_DUE_WINDOW = timedelta(hours=6)
_IDLE_POKE_WINDOW = timedelta(hours=1)
_IDLE_POKE_COOLDOWN_SECONDS = 3600
_DEFAULT_SIGNAL_COOLDOWN_SECONDS = 1800
_STALL_MIN_WINDOW = 300
_PENDING_CONSOLIDATION_STALE_WINDOW = timedelta(hours=4)


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
        self._last_idle_poke_at = ""

    async def init_heart(self):
        await self.refresh_config()
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession() if aiohttp is not None else _FallbackClientSession()
        self._memory.set_housekeeping_adapter(self._adapter)
        try:
            changed = await self._task_manager.backfill_scheduled_tasks()
            if changed:
                logger.info("Backfilled schedule metadata for %s task(s)", changed)
        except Exception as exc:
            logger.warning("Task schedule backfill failed: %s", exc)
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
        self._api_url = self._config.get("heartbeat_api_url") or ""
        self._api_key = self._config.get("heartbeat_api_key") or ""
        self._model = self._config.get("heart_model") or ""
        logger.info(
            "Heart config refreshed: heartbeat=%ss housekeeping=%ss scheduler=%ss model=%s",
            self._heartbeat_interval,
            self._housekeeping_interval,
            self._scheduler_interval,
            self._model,
        )

    def set_adapter(self, adapter):
        self._adapter = adapter
        self._memory.set_housekeeping_adapter(adapter)
        self._agent_runner = BackgroundAgentRunner(adapter, self._tools_manager)

    def set_session_manager(self, session_manager):
        self._session_manager = session_manager

    async def close_heart(self):
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
        logger.info("Heart closed")

    async def _set_status(self, status: str, detail: str = ""):
        if self._status_callback:
            await self._status_callback(status, detail)

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
            if source_kind not in {SourceKind.WEB.value, SourceKind.FEISHU.value, SourceKind.CLI.value}:
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
        issues: list[str] = []
        if payload.get("scheduler_stalled"):
            issues.append("scheduler_stalled")
        if payload.get("housekeeping_stalled"):
            issues.append("housekeeping_stalled")
        if str(payload.get("last_housekeeping_error") or "").strip():
            issues.append("housekeeping_error")
        if payload.get("repeated_failure_tasks"):
            issues.append("repeated_task_failures")
        return issues

    @staticmethod
    def _normalize_signal_kind(value: Any) -> str:
        normalized = str(value or "none").strip().lower() or "none"
        if normalized not in {"none", "urgent_deadline", "system_issue", "idle_poke"}:
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
        if signal_kind == "urgent_deadline":
            task = payload.get("nearest_due_task") or {}
            summary = str(task.get("summary") or task.get("task_key") or "近期任务").strip()
            minutes = task.get("minutes_until_due")
            if task.get("overdue"):
                return f"任务“{summary}”已经过期，建议尽快处理。"
            if isinstance(minutes, int):
                return f"任务“{summary}”将在约{max(minutes, 0)}分钟后到期，建议尽快确认下一步。"
            return f"任务“{summary}”即将到期，建议尽快确认下一步。"
        if signal_kind == "system_issue":
            if payload.get("repeated_failure_tasks"):
                task = payload["repeated_failure_tasks"][0]
                summary = str(task.get("summary") or task.get("task_key") or "后台任务").strip()
                return f"任务“{summary}”已连续失败，可能需要检查。"
            if payload.get("scheduler_stalled"):
                return "调度器长时间没有活动，可能影响定时任务触发。"
            if payload.get("housekeeping_stalled"):
                return "Housekeeping 长时间没有活动，可能影响后台整理。"
            return "后台出现了可能影响任务执行的异常，建议检查。"
        if signal_kind == "idle_poke":
            return "当前没有紧急事项，用户已沉默较久，可用一句自然短句确认是否需要帮助。"
        return ""

    def _canonical_signal_message(self, signal_kind: str, payload: dict[str, Any]) -> str:
        if signal_kind == "urgent_deadline":
            task = payload.get("nearest_due_task") or {}
            summary = str(task.get("summary") or task.get("task_key") or "scheduled task").strip()
            minutes = task.get("minutes_until_due")
            if task.get("overdue"):
                return f'Nearest urgent task "{summary}" is overdue. Focus only on that task and the next step.'
            if isinstance(minutes, int):
                return (
                    f'Nearest urgent task "{summary}" is due in about {max(minutes, 0)} minutes. '
                    "Focus only on that task and the next step."
                )
            return f'Nearest urgent task "{summary}" is due soon. Focus only on that task and the next step.'
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
            if str(payload.get("last_housekeeping_error") or "").strip():
                return "Background housekeeping is erroring. Keep the follow-up short and action-oriented."
            return (
                "There is a concrete background issue that may affect task execution or reminders. "
                "Keep the follow-up short."
            )
        if signal_kind == "idle_poke":
            return "There is no urgent deadline or critical issue. A single short casual check-in is enough."
        return self._fallback_signal_message(signal_kind, payload)

    def _signal_cooldown_seconds(self, signal_kind: str) -> int:
        if signal_kind == "idle_poke":
            return _IDLE_POKE_COOLDOWN_SECONDS
        return _DEFAULT_SIGNAL_COOLDOWN_SECONDS

    def _signal_in_cooldown(self, signal_kind: str, message: str) -> bool:
        last_sent_at = _iso_to_dt(self._last_heartbeat_signal_at)
        if last_sent_at is None:
            return False
        if self._last_heartbeat_signal_kind != signal_kind or self._last_heartbeat_signal_message != message:
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
        urgent_due_task_count = int(background_status.get("urgent_due_task_count") or 0)
        has_recent_user_session = bool(str(background_status.get("last_user_activity_at") or "").strip())
        idle_poke_eligible = bool(background_status.get("idle_poke_eligible"))

        if signal_kind == "urgent_deadline" and urgent_due_task_count <= 0:
            decision = "ok"
            signal_kind = "none"
        elif signal_kind == "system_issue" and not system_issue_candidates:
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
        if decision != "ok" and signal_kind != "none":
            message = self._sanitize_message(
                self._canonical_signal_message(signal_kind, background_status),
                single_sentence=single_sentence,
            )

        if decision == "ok" or signal_kind == "none":
            message = ""
            signal_kind = "none"
            decision = "ok"

        if message and self._signal_in_cooldown(signal_kind, message):
            message = ""
            signal_kind = "none"
            decision = "ok"

        return {
            "decision": decision,
            "signal_kind": signal_kind,
            "message": message,
            "reasons": list(payload.get("reasons") or []),
            "confidence": str(payload.get("confidence") or "medium").strip().lower() or "medium",
        }

    async def get_background_status(self) -> dict[str, Any]:
        payload = self._task_manager.build_background_status()
        pending_snapshot = self._pending_consolidation_snapshot()
        payload.update(pending_snapshot)
        payload.update(self._latest_user_activity())
        scheduler_stalled = self._loop_stalled(self._last_scheduler_tick_at, self._scheduler_interval)
        housekeeping_stalled = self._loop_stalled(self._last_housekeeping_at, self._housekeeping_interval)
        pending_consolidation_stale = self._pending_consolidation_stale(pending_snapshot)
        last_user_activity_at = _iso_to_dt(payload.get("last_user_activity_at"))
        now = datetime.now(timezone.utc)
        last_idle_poke_at = _iso_to_dt(self._last_idle_poke_at)
        has_recent_user_session = bool(payload.get("last_user_activity_at"))
        idle_window_ready = bool(last_user_activity_at and last_user_activity_at <= now - _IDLE_POKE_WINDOW)
        idle_cooldown_ready = bool(
            last_idle_poke_at is None or last_idle_poke_at <= now - timedelta(seconds=_IDLE_POKE_COOLDOWN_SECONDS)
        )
        payload["scheduler_stalled"] = scheduler_stalled
        payload["housekeeping_stalled"] = housekeeping_stalled
        payload["pending_consolidation_stale"] = pending_consolidation_stale
        payload["last_housekeeping_error"] = self._last_housekeeping_error
        payload["system_issue_candidates"] = self._build_system_issue_candidates(
            {
                **payload,
                "scheduler_stalled": scheduler_stalled,
                "housekeeping_stalled": housekeeping_stalled,
                "pending_consolidation_stale": pending_consolidation_stale,
                "last_housekeeping_error": self._last_housekeeping_error,
            }
        )
        payload["last_idle_poke_at"] = self._last_idle_poke_at
        payload["idle_poke_eligible"] = bool(
            has_recent_user_session
            and idle_window_ready
            and idle_cooldown_ready
            and int(payload.get("urgent_due_task_count") or 0) == 0
            and not payload["system_issue_candidates"]
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
            try:
                await self._memory.run_housekeeping(
                    self._http_session,
                    self._api_url,
                    self._api_key,
                    self._model,
                )
                self._last_housekeeping_at = _utcnow_iso()
                self._last_housekeeping_error = ""
            except Exception as exc:
                self._last_housekeeping_error = str(exc)
                logger.error("Memory housekeeping failed: %s", exc)

            try:
                await asyncio.wait_for(shutdown.wait(), timeout=max(self._housekeeping_interval, 1))
                break
            except asyncio.TimeoutError:
                pass

    async def scheduler_processor(self):
        shutdown = self._event_bus.shutdown_event
        while True:
            if shutdown.is_set() or self._http_session is None:
                break
            try:
                claimed = await self._task_manager.claim_due_tasks(limit=8, lease_seconds=120)
                self._last_scheduler_tick_at = _utcnow_iso()
                self._last_scheduler_claim_count = len(claimed)
                for record in claimed:
                    control_kind = "scheduled_task" if record.get("auto_run") else "scheduled_reminder"
                    await self._event_bus.inbound_queue.put(
                        InboundEvent(
                            session_id=f"system:task:{record.get('task_key', '')}",
                            type=EventType.CONTROL.value,
                            role="system",
                            content={"task_key": record.get("task_key", "")},
                            source=self._source,
                            target=EventTarget(kind=TargetKind.INTERNAL.value),
                            metadata={"control_kind": control_kind},
                        )
                    )
            except Exception as exc:
                logger.error("Scheduler tick failed: %s", exc)

            try:
                await asyncio.wait_for(shutdown.wait(), timeout=max(self._scheduler_interval, 1))
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

    async def heartbeat_processor(self):
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
                try:
                    await self._set_status("heartbeat", "Running heartbeat")
                    tools = self._tools_manager.get_heartbeat_tools()
                    background_status = await self.get_background_status()
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
                    )

                    payload = self._extract_json_payload(result.get("content") or "")
                    if payload is None:
                        raise ValueError(f"Heartbeat returned non-JSON content: {result.get('content')}")

                    normalized = self._normalize_heartbeat_result(payload, background_status)
                    decision = normalized["decision"]
                    signal_kind = normalized["signal_kind"]
                    message = normalized["message"]
                    self._last_heartbeat_at = _utcnow_iso()
                    self._last_heartbeat_decision = decision
                    self._last_heartbeat_summary = message
                    self._last_heartbeat_error = ""

                    if decision in {"notify", "escalate"} and message:
                        emitted_at = _utcnow_iso()
                        self._last_heartbeat_signal_kind = signal_kind
                        self._last_heartbeat_signal_message = message
                        self._last_heartbeat_signal_at = emitted_at
                        if signal_kind == "idle_poke":
                            self._last_idle_poke_at = emitted_at
                        await self._event_bus.inbound_queue.put(
                            InboundEvent(
                                session_id=self._session_id,
                                type=EventType.SIGNAL.value,
                                role="system",
                                content=message,
                                source=self._source,
                                target=EventTarget(kind=TargetKind.INTERNAL.value),
                                metadata={
                                    "heartbeat_decision": decision,
                                    "heartbeat_signal_kind": signal_kind,
                                    "transient": True,
                                    "disable_tools": True,
                                },
                            )
                        )
                    else:
                        self._last_heartbeat_signal_kind = "none"
                except Exception as exc:
                    logger.error("Heartbeat request failed: %s", exc)
                    self._last_heartbeat_at = _utcnow_iso()
                    self._last_heartbeat_error = str(exc)
                    await self._set_status("error", str(exc))
                finally:
                    await self._set_status("idle", "")
            else:
                logger.warning("Heartbeat config incomplete (api_url or model missing), skipping heartbeat model call")

            try:
                await asyncio.wait_for(shutdown.wait(), timeout=max(self._heartbeat_interval, 1))
                break
            except asyncio.TimeoutError:
                pass
