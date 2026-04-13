from __future__ import annotations

import asyncio
import logging

import aiohttp

from edge_agent.config import EdgeAgentConfig
from edge_agent.execution import build_capability_handlers
from edge_agent.protocol import (
    AGENT_SCHEMA,
    build_call_accepted,
    build_call_error,
    build_call_progress,
    build_call_result,
    build_capabilities_snapshot,
    build_heartbeat,
    build_hello,
)

logger = logging.getLogger("meetyou.edge_agent")


class EdgeAgentRuntime:
    def __init__(self, config: EdgeAgentConfig):
        self.config = config
        self._stop_event = asyncio.Event()
        self._capability_revision = 1
        self._handlers = build_capability_handlers(config.agent_id)
        self._active_ws = None
        self._heartbeat_interval_seconds = max(1, int(config.heartbeat_interval_seconds))
        self._heartbeat_interval_updated = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._run_connection()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Edge Agent connection failed: %s", exc)
            if not self._stop_event.is_set():
                await asyncio.sleep(self.config.reconnect_delay_seconds)

    async def _run_connection(self) -> None:
        headers = {}
        if self.config.agent_access_token:
            headers["Authorization"] = f"Bearer {self.config.agent_access_token}"
        timeout = aiohttp.ClientTimeout(total=None, connect=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.ws_connect(self.config.websocket_url) as ws:
                self._active_ws = ws
                self._set_heartbeat_interval(self.config.heartbeat_interval_seconds, notify=False)
                ready_received = False
                await ws.send_json(build_hello(self.config))
                await ws.send_json(build_capabilities_snapshot(self.config, revision=self._capability_revision))
                heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))
                try:
                    async for message in ws:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            payload = message.json(loads=__import__("json").loads)
                            ready_received = await self._handle_server_message(
                                payload,
                                ready_received,
                                ws,
                            )
                        elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            break
                finally:
                    heartbeat_task.cancel()
                    with __import__("contextlib").suppress(asyncio.CancelledError):
                        await heartbeat_task
                    if self._active_ws is ws:
                        self._active_ws = None

    def _set_heartbeat_interval(self, interval: int, *, notify: bool = True) -> int:
        normalized = max(1, int(interval))
        changed = normalized != self._heartbeat_interval_seconds
        self._heartbeat_interval_seconds = normalized
        if notify and changed:
            self._heartbeat_interval_updated.set()
        return normalized

    async def _heartbeat_loop(self, ws) -> None:
        while True:
            interval = max(3, self._heartbeat_interval_seconds)
            try:
                await asyncio.wait_for(self._heartbeat_interval_updated.wait(), timeout=interval)
                self._heartbeat_interval_updated.clear()
                continue
            except asyncio.TimeoutError:
                pass
            await ws.send_json(build_heartbeat(self.config, metrics={"workspace_count": len(self.config.workspace_ids)}))

    async def _handle_server_message(self, payload: dict, ready_received: bool, ws) -> bool:
        schema = str(payload.get("schema") or "")
        if schema != AGENT_SCHEMA:
            return ready_received
        message_type = str(payload.get("type") or "")
        if message_type == "agent.hello.ack":
            next_interval = int(payload.get("payload", {}).get("heartbeat_interval_seconds") or self._heartbeat_interval_seconds)
            self._set_heartbeat_interval(next_interval)
            logger.info("Edge Agent hello acknowledged: %s", payload.get("payload", {}))
            return ready_received
        if message_type == "agent.ready":
            logger.info("Edge Agent ready: %s", payload.get("payload", {}))
            return True
        if message_type == "capability.call.request":
            await self._handle_call_request(ws, payload)
            return ready_received
        return ready_received

    async def _handle_call_request(self, ws, payload: dict) -> None:
        envelope_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        call_id = str(envelope_payload.get("call_id") or "")
        capability_id = str(envelope_payload.get("capability_id") or "")
        correlation_id = str(payload.get("message_id") or "")
        arguments = envelope_payload.get("arguments") if isinstance(envelope_payload.get("arguments"), dict) else {}
        if not call_id or not capability_id:
            return
        handler = self._handlers.get(capability_id)
        await ws.send_json(build_call_accepted(self.config, call_id=call_id, correlation_id=correlation_id))
        await ws.send_json(
            build_call_progress(
                self.config,
                call_id=call_id,
                correlation_id=correlation_id,
                phase="running",
                detail="Dispatching edge capability handler",
            )
        )
        if handler is None:
            await ws.send_json(
                build_call_error(
                    self.config,
                    call_id=call_id,
                    correlation_id=correlation_id,
                    code="capability_not_implemented",
                    message=f"Capability not implemented: {capability_id}",
                )
            )
            return
        try:
            result = await handler(arguments)
        except Exception as exc:
            await ws.send_json(
                build_call_error(
                    self.config,
                    call_id=call_id,
                    correlation_id=correlation_id,
                    code="edge_call_failed",
                    message=str(exc),
                )
            )
            return
        await ws.send_json(
            build_call_result(
                self.config,
                call_id=call_id,
                correlation_id=correlation_id,
                result=result,
            )
        )
