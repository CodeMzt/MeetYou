"""
Background heartbeat loop.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from core.io_protocol import EventTarget, EventType, InboundEvent, SourceKind, TargetKind, make_source

logger = logging.getLogger("meetyou.heart")


class Heart:
    def __init__(
        self,
        adapter,
        config,
        tools_manager,
        memory,
        event_bus,
        exception_router,
        status_callback=None,
    ):
        self._adapter = adapter
        self._config = config
        self._tools_manager = tools_manager
        self._memory = memory
        self._event_bus = event_bus
        self._exception_router = exception_router
        self._status_callback = status_callback

        self._prompt = ""
        self._interval = 60
        self._api_key = ""
        self._api_url = ""
        self._model = ""
        self._http_session: aiohttp.ClientSession | None = None
        self._source = make_source(SourceKind.HEART.value, "system")
        self._session_id = "system:heart"
        self._memory.set_housekeeping_adapter(adapter)

    async def init_heart(self):
        await self.refresh_config()
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()
        self._memory.set_housekeeping_adapter(self._adapter)
        logger.info("Heart initialized: interval=%ss model=%s", self._interval, self._model)

    async def refresh_config(self):
        try:
            self._prompt = self._config.get_prompt("heartbeat")
        except Exception as exc:
            logger.error("Failed to load heartbeat prompt: %s", exc)

        self._interval = int(self._config.get("heartbeat_interval") or 60)
        self._api_url = self._config.get("heartbeat_api_url") or ""
        self._api_key = self._config.get("heartbeat_api_key") or ""
        self._model = self._config.get("heart_model") or ""
        logger.info("Heart config refreshed: interval=%ss model=%s", self._interval, self._model)

    def set_adapter(self, adapter):
        self._adapter = adapter
        self._memory.set_housekeeping_adapter(adapter)

    async def close_heart(self):
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
        logger.info("Heart closed")

    async def _set_status(self, status: str, detail: str = ""):
        if self._status_callback:
            await self._status_callback(status, detail)

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
                    result = await self._adapter.chat(
                        self._http_session,
                        self._api_url,
                        self._api_key,
                        self._model,
                        [{"role": "user", "content": self._prompt}],
                        tools=tools,
                    )

                    output = (result.get("content") or "").strip()
                    if output and output not in ("[HEARTBEAT_OK]", "HEARTBEAT_OK"):
                        await self._event_bus.inbound_queue.put(
                            InboundEvent(
                                session_id=self._session_id,
                                type=EventType.SIGNAL.value,
                                role="system",
                                content=output,
                                source=self._source,
                                target=EventTarget(kind=TargetKind.INTERNAL.value),
                            )
                        )
                except Exception as exc:
                    logger.error("Heartbeat request failed: %s", exc)
                    await self._set_status("error", str(exc))
                finally:
                    await self._set_status("idle", "")
            else:
                logger.warning("Heartbeat config incomplete (api_url or model missing), running housekeeping only")

            try:
                await self._memory.run_housekeeping(
                    self._http_session,
                    self._api_url,
                    self._api_key,
                    self._model,
                )
            except Exception as exc:
                logger.error("Memory housekeeping failed: %s", exc)

            try:
                await asyncio.wait_for(shutdown.wait(), timeout=self._interval)
                break
            except asyncio.TimeoutError:
                pass
