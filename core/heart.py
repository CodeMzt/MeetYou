"""
Background scheduling, housekeeping, and heartbeat loops.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

try:
    import aiohttp
except ImportError:  # pragma: no cover - optional dependency
    aiohttp = None

from core.background_agent import BackgroundAgentRunner
from core.io_protocol import EventTarget, EventType, InboundEvent, SourceKind, TargetKind, make_source

logger = logging.getLogger("meetyou.heart")


class _FallbackClientSession:
    async def close(self):
        return None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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

    async def get_background_status(self) -> dict[str, Any]:
        payload = self._task_manager.build_background_status()
        payload.update(self._pending_consolidation_snapshot())
        payload.update(
            {
                "heartbeat_interval": self._heartbeat_interval,
                "housekeeping_interval": self._housekeeping_interval,
                "scheduler_interval": self._scheduler_interval,
                "last_scheduler_tick_at": self._last_scheduler_tick_at,
                "last_scheduler_claim_count": self._last_scheduler_claim_count,
                "last_housekeeping_at": self._last_housekeeping_at,
                "last_housekeeping_error": self._last_housekeeping_error,
                "last_heartbeat_at": self._last_heartbeat_at,
                "last_heartbeat_decision": self._last_heartbeat_decision,
                "last_heartbeat_summary": self._last_heartbeat_summary,
                "last_heartbeat_error": self._last_heartbeat_error,
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

                    decision = str(payload.get("decision") or "ok").strip().lower() or "ok"
                    message = str(payload.get("message") or "").strip()
                    self._last_heartbeat_at = _utcnow_iso()
                    self._last_heartbeat_decision = decision
                    self._last_heartbeat_summary = message
                    self._last_heartbeat_error = ""

                    if decision in {"notify", "escalate"} and message:
                        await self._event_bus.inbound_queue.put(
                            InboundEvent(
                                session_id=self._session_id,
                                type=EventType.SIGNAL.value,
                                role="system",
                                content=message,
                                source=self._source,
                                target=EventTarget(kind=TargetKind.INTERNAL.value),
                                metadata={"heartbeat_decision": decision},
                            )
                        )
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
