from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiohttp

from desktop_agent.config import DesktopAgentConfig
from desktop_agent.mcp_runtime import DesktopAgentMCPRuntime
from desktop_agent.policy import DesktopAgentPolicyError
from desktop_agent.execution import build_capability_handlers
from desktop_agent.protocol import (
    AGENT_SCHEMA,
    build_call_accepted,
    build_call_error,
    build_call_progress,
    build_call_result,
    build_capabilities_snapshot,
    build_heartbeat,
    build_hello,
)

logger = logging.getLogger("meetyou.desktop_agent")

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None


class DesktopAgentRuntime:
    def __init__(self, config: DesktopAgentConfig):
        self.config = config
        self._stop_event = asyncio.Event()
        self._capability_revision = 1
        self._handlers = build_capability_handlers(config)
        self._mcp_runtime = DesktopAgentMCPRuntime(config)
        self._mcp_init_task: asyncio.Task | None = None
        self._mcp_ready = False
        self._active_ws = None

    async def run(self) -> None:
        try:
            if self._mcp_init_task is None:
                self._mcp_init_task = asyncio.create_task(self._initialize_mcp_runtime())
            while not self._stop_event.is_set():
                try:
                    await self._run_connection()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Desktop Agent connection failed: %s", exc)
                if not self._stop_event.is_set():
                    await asyncio.sleep(self.config.reconnect_delay_seconds)
        finally:
            if self._mcp_init_task is not None:
                self._mcp_init_task.cancel()
                with __import__("contextlib").suppress(asyncio.CancelledError):
                    await self._mcp_init_task
            await self._mcp_runtime.close()

    def stop(self) -> None:
        self._stop_event.set()

    async def _initialize_mcp_runtime(self) -> None:
        try:
            await self._mcp_runtime.initialize()
            self._mcp_ready = True
            self._capability_revision += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Desktop Agent MCP initialization failed: %s", exc)

    async def _run_connection(self) -> None:
        headers = {}
        if self.config.agent_access_token:
            headers["Authorization"] = f"Bearer {self.config.agent_access_token}"
        timeout = aiohttp.ClientTimeout(total=None, connect=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.ws_connect(self.config.websocket_url) as ws:
                self._active_ws = ws
                heartbeat_interval = self.config.heartbeat_interval_seconds
                ready_received = False
                await ws.send_json(build_hello(self.config))
                await self._send_capability_snapshot(ws)
                heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws, heartbeat_interval))
                try:
                    async for message in ws:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            payload = message.json(loads=__import__("json").loads)
                            heartbeat_interval, ready_received = await self._handle_server_message(
                                payload,
                                heartbeat_interval,
                                ready_received,
                                ws,
                                session,
                            )
                        elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            break
                finally:
                    heartbeat_task.cancel()
                    with __import__("contextlib").suppress(asyncio.CancelledError):
                        await heartbeat_task
                    if self._active_ws is ws:
                        self._active_ws = None

    async def _send_capability_snapshot(self, ws) -> None:
        await ws.send_json(
            build_capabilities_snapshot(
                self.config,
                revision=self._capability_revision,
                extra_capabilities=self._mcp_runtime.capability_definitions() if self._mcp_ready else [],
            )
        )

    async def _heartbeat_loop(self, ws, interval: int) -> None:
        while True:
            await asyncio.sleep(max(3, interval))
            await ws.send_json(build_heartbeat(self.config, metrics=self._collect_metrics()))

    async def _handle_server_message(self, payload: dict, heartbeat_interval: int, ready_received: bool, ws, session) -> tuple[int, bool]:
        schema = str(payload.get("schema") or "")
        if schema != AGENT_SCHEMA:
            return heartbeat_interval, ready_received
        message_type = str(payload.get("type") or "")
        if message_type == "agent.hello.ack":
            next_interval = int(payload.get("payload", {}).get("heartbeat_interval_seconds") or heartbeat_interval)
            logger.info("Desktop Agent hello acknowledged: %s", payload.get("payload", {}))
            return next_interval, ready_received
        if message_type == "agent.ready":
            logger.info("Desktop Agent ready: %s", payload.get("payload", {}))
            return heartbeat_interval, True
        if message_type == "capability.call.request":
            await self._handle_call_request(ws, payload, session)
            return heartbeat_interval, ready_received
        return heartbeat_interval, ready_received

    @staticmethod
    def _split_result_payload(result: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        payload = dict(result or {})
        attachment_outputs = payload.pop("attachment_outputs", [])
        if not isinstance(attachment_outputs, list):
            attachment_outputs = []
        return payload, [dict(item) for item in attachment_outputs if isinstance(item, dict)]

    async def _request_json(self, session: aiohttp.ClientSession, method: str, url: str, **kwargs) -> dict[str, Any]:
        async with session.request(method, url, **kwargs) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(str(payload))
            if not isinstance(payload, dict):
                raise RuntimeError(f"unexpected response payload: {payload!r}")
            return payload

    async def _upload_attachment_outputs(
        self,
        session: aiohttp.ClientSession,
        *,
        operation_id: str,
        attachment_outputs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        uploaded: list[dict[str, Any]] = []
        base_url = self.config.core_base_url.rstrip("/")
        for item in attachment_outputs:
            local_path = Path(str(item.get("local_path") or "")).expanduser().resolve()
            if not local_path.exists() or not local_path.is_file():
                raise RuntimeError(f"attachment local_path not found: {local_path}")
            content = await asyncio.to_thread(local_path.read_bytes)
            ticket = await self._request_json(
                session,
                "POST",
                f"{base_url}/agent/attachments/upload-ticket",
                json={
                    "agent_id": self.config.agent_id,
                    "owner_type": str(item.get("owner_type") or "operation").strip() or "operation",
                    "owner_id": str(item.get("owner_id") or operation_id).strip() or operation_id,
                    "kind": str(item.get("kind") or "file").strip() or "file",
                    "mime_type": str(item.get("mime_type") or "application/octet-stream").strip() or "application/octet-stream",
                    "file_name": str(item.get("file_name") or local_path.name).strip() or local_path.name,
                    "size_bytes": len(content),
                    "lifecycle_policy": str(item.get("lifecycle_policy") or "normal").strip() or "normal",
                },
            )
            await self._request_json(session, "PUT", str(ticket.get("upload_url") or ""), data=content)
            complete = await self._request_json(
                session,
                "POST",
                f"{base_url}/agent/attachments/{ticket['attachment_id']}/complete",
                json={
                    "ticket_id": ticket["ticket_id"],
                },
            )
            uploaded.append(
                {
                    "attachment_id": complete.get("attachment_id"),
                    "kind": item.get("kind") or "file",
                    "mime_type": complete.get("mime_type"),
                    "file_name": complete.get("file_name"),
                    "size_bytes": complete.get("size_bytes"),
                    "sha256": complete.get("sha256"),
                    "status": complete.get("status"),
                }
            )
        return uploaded

    async def _handle_call_request(self, ws, payload: dict, session) -> None:
        envelope_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        call_id = str(envelope_payload.get("call_id") or "")
        capability_id = str(envelope_payload.get("capability_id") or "")
        operation_id = str(envelope_payload.get("operation_id") or "")
        correlation_id = str(payload.get("message_id") or "")
        arguments = envelope_payload.get("arguments") if isinstance(envelope_payload.get("arguments"), dict) else {}
        if not call_id or not capability_id:
            return
        handler = self._handlers.get(capability_id)
        await ws.send_json(build_call_accepted(self.config, call_id=call_id, correlation_id=correlation_id))
        await ws.send_json(build_call_progress(self.config, call_id=call_id, correlation_id=correlation_id, phase="running", detail="Dispatching capability handler"))
        if handler is None and self._mcp_runtime.can_handle(capability_id):
            try:
                result = await self._mcp_runtime.call_capability(capability_id, arguments)
            except Exception as exc:
                await ws.send_json(
                    build_call_error(
                        self.config,
                        call_id=call_id,
                        correlation_id=correlation_id,
                        code="mcp_call_failed",
                        message=str(exc),
                    )
                )
                return
            result_payload, attachment_outputs = self._split_result_payload(result)
            uploaded = await self._upload_attachment_outputs(session, operation_id=operation_id, attachment_outputs=attachment_outputs)
            await ws.send_json(
                build_call_result(
                    self.config,
                    call_id=call_id,
                    correlation_id=correlation_id,
                    result=result_payload,
                    attachment_outputs=uploaded,
                )
            )
            return
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
        except DesktopAgentPolicyError as exc:
            await ws.send_json(
                build_call_error(
                    self.config,
                    call_id=call_id,
                    correlation_id=correlation_id,
                    code=exc.code,
                    message=exc.message,
                )
            )
            return
        except Exception as exc:
            await ws.send_json(
                build_call_error(
                    self.config,
                    call_id=call_id,
                    correlation_id=correlation_id,
                    code="capability_execution_failed",
                    message=str(exc),
                )
            )
            return
        result_payload, attachment_outputs = self._split_result_payload(result)
        uploaded = await self._upload_attachment_outputs(session, operation_id=operation_id, attachment_outputs=attachment_outputs)
        await ws.send_json(
            build_call_result(
                self.config,
                call_id=call_id,
                correlation_id=correlation_id,
                result=result_payload,
                attachment_outputs=uploaded,
            )
        )

    @staticmethod
    def _collect_metrics() -> dict[str, float | int]:
        if psutil is None:
            return {"active_calls": 0}
        return {
            "cpu_percent": float(psutil.cpu_percent(interval=None)),
            "memory_percent": float(psutil.virtual_memory().percent),
            "active_calls": 0,
            "offline_queue_size": 0,
        }
