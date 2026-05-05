from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import aiohttp

from endpoint_tool_sdk.protocol import (
    DEFAULT_ENDPOINT_TOOL_PROTOCOL_FEATURES,
    ENDPOINT_TOOL_ARGUMENTS_PURPOSE,
    ENDPOINT_TOOL_PROTOCOL_VERSION,
    ENDPOINT_TOOL_SCHEMA,
    build_endpoint_protocol_selection,
)
from endpoint_tool_sdk.security import CredentialTransportError, decrypt_json_payload
from endpoint_tool_sdk.transport import build_endpoint_auth_headers, build_endpoint_ws_timeout, normalize_heartbeat_interval


Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class ToolExecutionOutcome:
    result: dict[str, Any]


class ToolExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class EndpointHandshakeRejected(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


class EndpointToolRuntimeBase(ABC):
    def __init__(self, config: Any, *, handlers: dict[str, Handler], logger: logging.Logger | None = None):
        self.config = config
        self._logger = logger or logging.getLogger("meetyou.endpoint_tool_runtime")
        self._stop_event = asyncio.Event()
        self._tool_revision = 1
        self._handlers = dict(handlers or {})
        self._active_ws = None
        self._heartbeat_interval_seconds = normalize_heartbeat_interval(getattr(config, "heartbeat_interval_seconds", 20))
        self._heartbeat_interval_updated = asyncio.Event()
        self._last_connection_prompt: dict[str, Any] | None = None
        self._negotiated_protocol: dict[str, Any] = self._default_protocol_selection()
        self._requires_capabilities_snapshot = True
        max_parallel_calls = getattr(config, "max_parallel_calls", 2)
        try:
            max_parallel_calls = int(max_parallel_calls)
        except (TypeError, ValueError):
            max_parallel_calls = 2
        self._call_semaphore = asyncio.Semaphore(max(1, min(max_parallel_calls, 4)))
        self._active_call_tasks: set[asyncio.Task] = set()
        self._active_call_tasks_by_call_id: dict[str, asyncio.Task] = {}
        self._active_call_count = 0
        self._call_locks: dict[str, asyncio.Lock] = {}
        self._send_lock = asyncio.Lock()

    @property
    def protocol_schema(self) -> str:
        return ENDPOINT_TOOL_SCHEMA

    @property
    @abstractmethod
    def runtime_label(self) -> str:
        raise NotImplementedError

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def core_access_token_source_hints(self) -> tuple[str, ...]:
        config_path = str(getattr(self.config, "config_file_path", "")).strip()
        hints = [
            "env `MEETYOU_CLIENT_ACCESS_TOKEN`",
            "env `MEETYOU_GATEWAY_ACCESS_TOKEN`",
        ]
        if config_path:
            hints.append(f"config `{config_path}` -> `core_access_token`")
        return tuple(hints)

    def missing_core_access_token_message(self) -> str:
        hints = ", ".join(self.core_access_token_source_hints())
        websocket_url = str(getattr(self.config, "websocket_url", "")).strip()
        message = "missing required config item `core_access_token`"
        if hints:
            message = f"{message}; expected one of: {hints}"
        if websocket_url:
            message = f"{message}; target={websocket_url}"
        return message

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        try:
            await self.startup()
            resolved_token = str(getattr(self.config, "core_access_token", "")).strip()
            if not resolved_token:
                self._logger.error(
                    "%s runtime disabled: %s",
                    self.runtime_label,
                    self.missing_core_access_token_message(),
                )
                await self._stop_event.wait()
                return
            while not self._stop_event.is_set():
                try:
                    await self._run_connection()
                except asyncio.CancelledError:
                    raise
                except EndpointHandshakeRejected as exc:
                    self._logger.error(
                        "%s connection rejected: [%s] %s",
                        self.runtime_label,
                        exc.code,
                        exc.message,
                    )
                    if exc.details:
                        self._logger.info("%s rejection details: %s", self.runtime_label, exc.details)
                    self._logger.error(
                        "%s runtime paused until restart because the handshake failure is not retryable.",
                        self.runtime_label,
                    )
                    await self._stop_event.wait()
                    break
                except Exception as exc:
                    self._logger.exception("%s connection failed: %s", self.runtime_label, exc)
                if not self._stop_event.is_set():
                    await asyncio.sleep(getattr(self.config, "reconnect_delay_seconds", 3))
        finally:
            await self.shutdown()

    async def _run_connection(self) -> None:
        timeout = build_endpoint_ws_timeout(connect_seconds=15, total=None)
        headers = build_endpoint_auth_headers(getattr(self.config, "core_access_token", ""))
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.ws_connect(getattr(self.config, "websocket_url")) as ws:
                self._active_ws = ws
                self._set_heartbeat_interval(getattr(self.config, "heartbeat_interval_seconds", 20), notify=False)
                self._heartbeat_interval_updated.clear()
                self._last_connection_prompt = None
                self._negotiated_protocol = self._default_protocol_selection()
                self._requires_capabilities_snapshot = True
                ready_received = False
                await ws.send_json(self.build_hello_message())
                ready_received = await self._complete_handshake(ws, session, ready_received)
                if self._requires_capabilities_snapshot:
                    await self._send_tools_snapshot(ws)
                heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))
                try:
                    async for message in ws:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            payload = message.json(loads=json.loads)
                            ready_received = await self._handle_server_message(
                                payload,
                                ready_received,
                                ws,
                                session,
                            )
                        elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            break
                finally:
                    heartbeat_task.cancel()
                    for task in list(self._active_call_tasks):
                        task.cancel()
                    if self._active_call_tasks:
                        await asyncio.gather(*self._active_call_tasks, return_exceptions=True)
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task
                    if self._active_ws is ws:
                        self._active_ws = None

    async def _complete_handshake(self, ws, session, ready_received: bool) -> bool:
        while True:
            message = await ws.receive()
            if message.type == aiohttp.WSMsgType.TEXT:
                payload = message.json(loads=json.loads)
                ready_received = await self._handle_server_message(
                    payload,
                    ready_received,
                    ws,
                    session,
                )
                if str(payload.get("type") or "") == "endpoint.hello.ack":
                    return ready_received
                continue
            if message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                raise RuntimeError(
                    f"{self.runtime_label} websocket closed before endpoint.hello.ack "
                    f"(ws_type={message.type}, close_code={getattr(ws, 'close_code', None)})"
                )

    async def _send_tools_snapshot(self, ws) -> None:
        await self._send_ws_json(ws, self.build_tools_snapshot_message(revision=self._tool_revision))

    async def _send_ws_json(self, ws, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await ws.send_json(payload)

    def _set_heartbeat_interval(self, interval: int, *, notify: bool = True) -> int:
        normalized = normalize_heartbeat_interval(interval)
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
            await self._send_ws_json(ws, self.build_heartbeat_message(metrics=self.collect_metrics()))

    async def _handle_server_message(self, payload: dict[str, Any], ready_received: bool, ws, session=None) -> bool:
        if str(payload.get("kind") or "").strip() == "error":
            error_payload = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            raise EndpointHandshakeRejected(
                str(error_payload.get("code") or "endpoint_runtime_error"),
                str(error_payload.get("message") or f"{self.runtime_label} runtime error"),
                details=error_payload.get("details") if isinstance(error_payload.get("details"), dict) else {},
            )
        schema = str(payload.get("schema") or "")
        if schema != self.protocol_schema:
            return ready_received
        message_type = str(payload.get("type") or "")
        if message_type == "endpoint.hello.ack":
            ack_payload = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
            if ack_payload.get("accepted") is False:
                reject_reason = ack_payload.get("reject_reason") if isinstance(ack_payload.get("reject_reason"), dict) else {}
                raise EndpointHandshakeRejected(
                    str(reject_reason.get("code") or "endpoint_handshake_rejected"),
                    str(reject_reason.get("message") or "endpoint handshake rejected"),
                    details=reject_reason.get("details") if isinstance(reject_reason.get("details"), dict) else {},
                )
            next_interval = int(ack_payload.get("heartbeat_interval_seconds") or self._heartbeat_interval_seconds)
            self._set_heartbeat_interval(next_interval)
            protocol_payload = ack_payload.get("protocol") if isinstance(ack_payload.get("protocol"), dict) else None
            if not protocol_payload:
                raise EndpointHandshakeRejected(
                    "endpoint_protocol_required",
                    "endpoint.hello.ack did not include a negotiated endpoint protocol",
                )
            selected_schema = str(protocol_payload.get("selected_schema") or "").strip()
            try:
                selected_version = int(protocol_payload.get("selected_version") or 0)
            except (TypeError, ValueError):
                selected_version = 0
            if selected_schema != self.protocol_schema or selected_version != ENDPOINT_TOOL_PROTOCOL_VERSION:
                raise EndpointHandshakeRejected(
                    "unsupported_endpoint_protocol",
                    "endpoint.hello.ack selected an unsupported endpoint protocol",
                    details={"selected_schema": selected_schema, "selected_version": selected_version},
                )
            self._requires_capabilities_snapshot = bool(ack_payload.get("requires_capabilities_snapshot", True))
            self._negotiated_protocol = dict(protocol_payload)
            connection_prompt = ack_payload.get("connection_prompt")
            if isinstance(connection_prompt, dict) and connection_prompt:
                self._last_connection_prompt = dict(connection_prompt)
                self._logger.info(
                    "%s received connection prompt %s",
                    self.runtime_label,
                    connection_prompt.get("prompt_name") or "endpoint_connected",
                )
            disabled_features = self._negotiated_protocol.get("disabled_features")
            if isinstance(disabled_features, list) and disabled_features:
                self._logger.info("%s downgraded handshake features: %s", self.runtime_label, disabled_features)
            self._logger.info("%s hello acknowledged: %s", self.runtime_label, ack_payload)
            return ready_received
        if message_type in {"delivery.message", "delivery.run_event", "delivery.notice", "delivery.operation_update"}:
            await self.handle_delivery_message(payload=payload, ws=ws, session=session)
            return ready_received
        if message_type == "endpoint.ready":
            self._logger.info("%s ready: %s", self.runtime_label, payload.get("payload", {}))
            return True
        if message_type == "tool.call.request":
            envelope_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            call_id = str(envelope_payload.get("call_id") or "").strip()
            task = asyncio.create_task(self._handle_call_request(ws, payload, session))
            self._active_call_tasks.add(task)
            if call_id:
                self._active_call_tasks_by_call_id[call_id] = task

            def _discard_call_task(done_task: asyncio.Task, *, active_call_id: str = call_id) -> None:
                self._active_call_tasks.discard(done_task)
                if active_call_id and self._active_call_tasks_by_call_id.get(active_call_id) is done_task:
                    self._active_call_tasks_by_call_id.pop(active_call_id, None)

            task.add_done_callback(_discard_call_task)
            return ready_received
        if message_type == "tool.call.cancel":
            self._handle_call_cancel(payload)
            return ready_received
        return ready_received

    def _handle_call_cancel(self, payload: dict[str, Any]) -> None:
        envelope_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        call_id = str(envelope_payload.get("call_id") or "").strip()
        if not call_id:
            return
        task = self._active_call_tasks_by_call_id.get(call_id)
        if task is None or task.done():
            self._logger.info("%s received cancel for inactive call_id=%s", self.runtime_label, call_id)
            return
        task.cancel()
        self._logger.info("%s cancelled active call_id=%s", self.runtime_label, call_id)

    async def handle_delivery_message(self, *, payload: dict[str, Any], ws, session) -> None:
        del ws, session
        delivery_payload = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
        metadata = delivery_payload.get("metadata") if isinstance(delivery_payload.get("metadata"), dict) else {}
        stream_event = str(metadata.get("stream_event") or "").strip().lower()
        if stream_event in {"start", "chunk", "end"}:
            return
        content = str(delivery_payload.get("content") or "")
        preview = content[:120] + ("..." if len(content) > 120 else "")
        self._logger.info(
            "%s received Core reply event_type=%s role=%s session_id=%s preview=%r",
            self.runtime_label,
            str(delivery_payload.get("event_type") or ""),
            str(delivery_payload.get("role") or ""),
            str(delivery_payload.get("session_id") or ""),
            preview,
        )

    async def _handle_call_request(self, ws, payload: dict[str, Any], session=None) -> None:
        envelope_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        call_id = str(envelope_payload.get("call_id") or "")
        tool_id = str(envelope_payload.get("tool_id") or "")
        tool_key = str(envelope_payload.get("tool_key") or tool_id).strip()
        correlation_id = str(payload.get("message_id") or "")
        arguments = envelope_payload.get("arguments") if isinstance(envelope_payload.get("arguments"), dict) else {}
        encrypted_arguments = envelope_payload.get("encrypted_arguments") if isinstance(envelope_payload.get("encrypted_arguments"), dict) else {}
        if not call_id or not tool_key:
            return
        try:
            resolved_arguments = self._resolve_call_arguments(arguments, encrypted_arguments)
        except CredentialTransportError as exc:
            await self._send_ws_json(
                ws,
                self.build_call_error_message(
                    call_id=call_id,
                    correlation_id=correlation_id,
                    code=exc.code,
                    message=exc.message,
                )
            )
            return

        await self._send_ws_json(ws, self.build_call_accepted_message(call_id=call_id, correlation_id=correlation_id))
        await self._send_ws_json(
            ws,
            self.build_call_progress_message(
                call_id=call_id,
                correlation_id=correlation_id,
                phase="running",
                detail=self.call_progress_detail(tool_key),
            )
        )
        try:
            async with self._call_semaphore:
                self._active_call_count += 1
                try:
                    if self.allows_parallel_tool(tool_key):
                        outcome = await self.execute_tool(
                            tool_key=tool_key,
                            tool_id=tool_id,
                            arguments=resolved_arguments,
                            envelope_payload=envelope_payload,
                            session=session,
                        )
                    else:
                        lock = self._call_locks.setdefault(tool_key, asyncio.Lock())
                        async with lock:
                            outcome = await self.execute_tool(
                                tool_key=tool_key,
                                tool_id=tool_id,
                                arguments=resolved_arguments,
                                envelope_payload=envelope_payload,
                                session=session,
                            )
                finally:
                    self._active_call_count = max(0, self._active_call_count - 1)
        except ToolExecutionError as exc:
            await self._send_ws_json(
                ws,
                self.build_call_error_message(
                    call_id=call_id,
                    correlation_id=correlation_id,
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable,
                )
            )
            return
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await self._send_ws_json(
                    ws,
                    self.build_call_error_message(
                        call_id=call_id,
                        correlation_id=correlation_id,
                        code="tool_call_cancelled",
                        message="Tool call cancelled",
                        retryable=False,
                    )
                )
            raise
        except Exception as exc:
            await self._send_ws_json(
                ws,
                self.build_call_error_message(
                    call_id=call_id,
                    correlation_id=correlation_id,
                    code="tool_execution_failed",
                    message=str(exc),
                    retryable=False,
                )
            )
            return

        await self._send_ws_json(
            ws,
            self.build_call_result_message(
                call_id=call_id,
                correlation_id=correlation_id,
                outcome=outcome,
            )
        )

    @staticmethod
    def _resolve_call_arguments(arguments: dict[str, Any], encrypted_arguments: dict[str, Any]) -> dict[str, Any]:
        if not encrypted_arguments:
            return dict(arguments or {})
        return decrypt_json_payload(
            encrypted_arguments,
            purpose=ENDPOINT_TOOL_ARGUMENTS_PURPOSE,
        )

    def collect_metrics(self) -> dict[str, Any]:
        return {"active_calls": self._active_call_count}

    def allows_parallel_tool(self, tool_id: str) -> bool:
        del tool_id
        return False

    def _default_protocol_selection(self) -> dict[str, Any]:
        return build_endpoint_protocol_selection(
            selected_schema=self.protocol_schema,
            selected_version=ENDPOINT_TOOL_PROTOCOL_VERSION,
            enabled_features=DEFAULT_ENDPOINT_TOOL_PROTOCOL_FEATURES,
        )

    def call_progress_detail(self, tool_id: str) -> str:
        del tool_id
        return "Dispatching tool handler"

    @abstractmethod
    def build_hello_message(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def build_tools_snapshot_message(self, *, revision: int) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def build_heartbeat_message(self, *, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def build_call_accepted_message(self, *, call_id: str, correlation_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def build_call_progress_message(self, *, call_id: str, correlation_id: str, phase: str, detail: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def build_call_result_message(self, *, call_id: str, correlation_id: str, outcome: ToolExecutionOutcome) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def build_call_error_message(
        self,
        *,
        call_id: str,
        correlation_id: str,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def execute_tool(
        self,
        *,
        tool_key: str,
        tool_id: str = "",
        arguments: dict[str, Any],
        envelope_payload: dict[str, Any],
        session,
    ) -> ToolExecutionOutcome:
        raise NotImplementedError

