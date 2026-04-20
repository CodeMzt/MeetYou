from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import aiohttp

from agent_sdk.protocol import (
    AGENT_ARGUMENTS_PURPOSE,
    AGENT_PROTOCOL_VERSION,
    AGENT_SCHEMA,
    LEGACY_AGENT_PROTOCOL_FEATURES,
    build_agent_protocol_selection,
)
from agent_sdk.security import CredentialTransportError, decrypt_json_payload
from agent_sdk.transport import build_agent_auth_headers, build_agent_ws_timeout, normalize_heartbeat_interval


Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class CapabilityExecutionOutcome:
    result: dict[str, Any]
    attachment_outputs: list[dict[str, Any]] = field(default_factory=list)


class CapabilityExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class AgentHandshakeRejected(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


class AgentRuntimeBase(ABC):
    def __init__(self, config: Any, *, handlers: dict[str, Handler], logger: logging.Logger | None = None):
        self.config = config
        self._logger = logger or logging.getLogger("meetyou.agent_runtime")
        self._stop_event = asyncio.Event()
        self._capability_revision = 1
        self._handlers = dict(handlers or {})
        self._active_ws = None
        self._heartbeat_interval_seconds = normalize_heartbeat_interval(getattr(config, "heartbeat_interval_seconds", 20))
        self._heartbeat_interval_updated = asyncio.Event()
        self._last_connection_prompt: dict[str, Any] | None = None
        self._negotiated_protocol: dict[str, Any] = self._legacy_protocol_selection()
        self._requires_capability_snapshot = True

    @property
    def protocol_schema(self) -> str:
        return AGENT_SCHEMA

    @property
    @abstractmethod
    def runtime_label(self) -> str:
        raise NotImplementedError

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        try:
            await self.startup()
            resolved_token = str(getattr(self.config, "agent_access_token", "")).strip()
            if not resolved_token:
                self._logger.error(
                    "%s runtime disabled: missing explicit agent access token for %s",
                    self.runtime_label,
                    getattr(self.config, "websocket_url", ""),
                )
                await self._stop_event.wait()
                return
            while not self._stop_event.is_set():
                try:
                    await self._run_connection()
                except asyncio.CancelledError:
                    raise
                except AgentHandshakeRejected as exc:
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
        timeout = build_agent_ws_timeout(connect_seconds=15, total=None)
        headers = build_agent_auth_headers(getattr(self.config, "agent_access_token", ""))
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.ws_connect(getattr(self.config, "websocket_url")) as ws:
                self._active_ws = ws
                self._set_heartbeat_interval(getattr(self.config, "heartbeat_interval_seconds", 20), notify=False)
                self._heartbeat_interval_updated.clear()
                self._last_connection_prompt = None
                self._negotiated_protocol = self._legacy_protocol_selection()
                self._requires_capability_snapshot = True
                ready_received = False
                await ws.send_json(self.build_hello_message())
                ready_received = await self._complete_handshake(ws, session, ready_received)
                if self._requires_capability_snapshot:
                    await self._send_capability_snapshot(ws)
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
                if str(payload.get("type") or "") == "agent.hello.ack":
                    return ready_received
                continue
            if message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                raise RuntimeError(
                    f"{self.runtime_label} websocket closed before agent.hello.ack "
                    f"(ws_type={message.type}, close_code={getattr(ws, 'close_code', None)})"
                )

    async def _send_capability_snapshot(self, ws) -> None:
        await ws.send_json(self.build_capabilities_snapshot_message(revision=self._capability_revision))

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
            await ws.send_json(self.build_heartbeat_message(metrics=self.collect_metrics()))

    async def _handle_server_message(self, payload: dict[str, Any], ready_received: bool, ws, session=None) -> bool:
        if str(payload.get("kind") or "").strip() == "error":
            error_payload = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            raise AgentHandshakeRejected(
                str(error_payload.get("code") or "agent_runtime_error"),
                str(error_payload.get("message") or f"{self.runtime_label} runtime error"),
                details=error_payload.get("details") if isinstance(error_payload.get("details"), dict) else {},
            )
        schema = str(payload.get("schema") or "")
        if schema != self.protocol_schema:
            return ready_received
        message_type = str(payload.get("type") or "")
        if message_type == "agent.hello.ack":
            ack_payload = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
            if ack_payload.get("accepted") is False:
                reject_reason = ack_payload.get("reject_reason") if isinstance(ack_payload.get("reject_reason"), dict) else {}
                raise AgentHandshakeRejected(
                    str(reject_reason.get("code") or "agent_handshake_rejected"),
                    str(reject_reason.get("message") or "agent handshake rejected"),
                    details=reject_reason.get("details") if isinstance(reject_reason.get("details"), dict) else {},
                )
            next_interval = int(ack_payload.get("heartbeat_interval_seconds") or self._heartbeat_interval_seconds)
            self._set_heartbeat_interval(next_interval)
            self._requires_capability_snapshot = bool(ack_payload.get("requires_capability_snapshot", True))
            protocol_payload = ack_payload.get("protocol") if isinstance(ack_payload.get("protocol"), dict) else None
            self._negotiated_protocol = dict(protocol_payload) if protocol_payload else self._legacy_protocol_selection()
            connection_prompt = ack_payload.get("connection_prompt")
            if isinstance(connection_prompt, dict) and connection_prompt:
                self._last_connection_prompt = dict(connection_prompt)
                self._logger.info(
                    "%s received connection prompt %s",
                    self.runtime_label,
                    connection_prompt.get("prompt_name") or "agent_connected",
                )
            disabled_features = self._negotiated_protocol.get("disabled_features")
            if isinstance(disabled_features, list) and disabled_features:
                self._logger.info("%s downgraded handshake features: %s", self.runtime_label, disabled_features)
            self._logger.info("%s hello acknowledged: %s", self.runtime_label, ack_payload)
            return ready_received
        if message_type == "agent.message":
            await self.handle_agent_message(payload=payload, ws=ws, session=session)
            return ready_received
        if message_type == "agent.ready":
            self._logger.info("%s ready: %s", self.runtime_label, payload.get("payload", {}))
            return True
        if message_type == "capability.call.request":
            await self._handle_call_request(ws, payload, session)
            return ready_received
        return ready_received

    async def handle_agent_message(self, *, payload: dict[str, Any], ws, session) -> None:
        del ws, session
        agent_payload = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
        metadata = agent_payload.get("metadata") if isinstance(agent_payload.get("metadata"), dict) else {}
        stream_event = str(metadata.get("stream_event") or "").strip().lower()
        if stream_event in {"start", "chunk", "end"}:
            return
        content = str(agent_payload.get("content") or "")
        preview = content[:120] + ("..." if len(content) > 120 else "")
        self._logger.info(
            "%s received Core reply event_type=%s role=%s session_id=%s preview=%r",
            self.runtime_label,
            str(agent_payload.get("event_type") or ""),
            str(agent_payload.get("role") or ""),
            str(agent_payload.get("session_id") or ""),
            preview,
        )

    async def _handle_call_request(self, ws, payload: dict[str, Any], session=None) -> None:
        envelope_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        call_id = str(envelope_payload.get("call_id") or "")
        capability_id = str(envelope_payload.get("capability_id") or "")
        correlation_id = str(payload.get("message_id") or "")
        arguments = envelope_payload.get("arguments") if isinstance(envelope_payload.get("arguments"), dict) else {}
        encrypted_arguments = envelope_payload.get("encrypted_arguments") if isinstance(envelope_payload.get("encrypted_arguments"), dict) else {}
        if not call_id or not capability_id:
            return
        try:
            resolved_arguments = self._resolve_call_arguments(arguments, encrypted_arguments)
        except CredentialTransportError as exc:
            await ws.send_json(
                self.build_call_error_message(
                    call_id=call_id,
                    correlation_id=correlation_id,
                    code=exc.code,
                    message=exc.message,
                )
            )
            return

        await ws.send_json(self.build_call_accepted_message(call_id=call_id, correlation_id=correlation_id))
        await ws.send_json(
            self.build_call_progress_message(
                call_id=call_id,
                correlation_id=correlation_id,
                phase="running",
                detail=self.call_progress_detail(capability_id),
            )
        )
        try:
            outcome = await self.execute_capability(
                capability_id=capability_id,
                arguments=resolved_arguments,
                envelope_payload=envelope_payload,
                session=session,
            )
        except CapabilityExecutionError as exc:
            await ws.send_json(
                self.build_call_error_message(
                    call_id=call_id,
                    correlation_id=correlation_id,
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable,
                )
            )
            return

        await ws.send_json(
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
            purpose=AGENT_ARGUMENTS_PURPOSE,
        )

    def collect_metrics(self) -> dict[str, Any]:
        return {}

    def _legacy_protocol_selection(self) -> dict[str, Any]:
        return build_agent_protocol_selection(
            selected_schema=self.protocol_schema,
            selected_version=AGENT_PROTOCOL_VERSION,
            enabled_features=LEGACY_AGENT_PROTOCOL_FEATURES,
            compatibility_mode="legacy_defaults",
        )

    def call_progress_detail(self, capability_id: str) -> str:
        del capability_id
        return "Dispatching capability handler"

    @abstractmethod
    def build_hello_message(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def build_capabilities_snapshot_message(self, *, revision: int) -> dict[str, Any]:
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
    def build_call_result_message(self, *, call_id: str, correlation_id: str, outcome: CapabilityExecutionOutcome) -> dict[str, Any]:
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
    async def execute_capability(
        self,
        *,
        capability_id: str,
        arguments: dict[str, Any],
        envelope_payload: dict[str, Any],
        session,
    ) -> CapabilityExecutionOutcome:
        raise NotImplementedError
