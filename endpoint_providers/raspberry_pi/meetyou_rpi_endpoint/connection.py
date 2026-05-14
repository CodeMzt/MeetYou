from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from endpoint_tool_sdk.protocol import ENDPOINT_TOOL_SCHEMA
from endpoint_tool_sdk.runtime import (
    EndpointHandshakeRejected,
    EndpointToolRuntimeBase,
    ToolExecutionError,
    ToolExecutionOutcome,
)

from .config import RpiEndpointConfig
from .protocol import (
    build_call_accepted,
    build_call_error,
    build_call_progress,
    build_call_result,
    build_goodbye,
    build_heartbeat,
    build_hello,
    build_tools_snapshot,
)
from .registry import build_default_registry
from .runtime.heartbeat import build_heartbeat_metrics
from .runtime.operation_runner import OperationRunner
from .runtime.reconnect import ReconnectBackoff
from .runtime.result_models import OperationRequest


logger = logging.getLogger("meetyou.rpi_endpoint")


class RpiEndpointRuntime(EndpointToolRuntimeBase):
    def __init__(self, config: RpiEndpointConfig, *, gpio_backend=None, force_fake_gpio: bool = False):
        self.registry = build_default_registry(
            config,
            gpio_backend=gpio_backend,
            force_fake_gpio=force_fake_gpio,
        )
        self.operation_runner = OperationRunner(
            self.registry,
            default_timeout_seconds=config.operation.default_timeout_seconds,
            max_timeout_seconds=config.operation.max_timeout_seconds,
        )
        super().__init__(config, handlers={}, logger=logger)

    @property
    def protocol_schema(self) -> str:
        return ENDPOINT_TOOL_SCHEMA

    @property
    def runtime_label(self) -> str:
        return "Raspberry Pi Endpoint Provider"

    def core_access_token_source_hints(self) -> tuple[str, ...]:
        return (
            f"env `{self.config.endpoint_token_env}`",
            "env `MEETYOU_RPI_ENDPOINT_TOKEN`",
            "env `MEETYOU_CLIENT_ACCESS_TOKEN`",
            "env `MEETYOU_GATEWAY_ACCESS_TOKEN`",
        )

    async def run(self) -> None:
        backoff = ReconnectBackoff(
            initial_delay_seconds=self.config.reconnect.initial_delay_seconds,
            max_delay_seconds=self.config.reconnect.max_delay_seconds,
            jitter_seconds=self.config.reconnect.jitter_seconds,
        )
        try:
            await self.startup()
            if not str(getattr(self.config, "core_access_token", "")).strip():
                self._logger.error("%s runtime disabled: %s", self.runtime_label, self.missing_core_access_token_message())
                await self._stop_event.wait()
                return
            while not self._stop_event.is_set():
                try:
                    await self._run_connection()
                    backoff.reset()
                except asyncio.CancelledError:
                    raise
                except EndpointHandshakeRejected as exc:
                    self._logger.error("%s connection rejected: [%s] %s", self.runtime_label, exc.code, exc.message)
                    if exc.details:
                        self._logger.info("%s rejection details: %s", self.runtime_label, exc.details)
                    await self._stop_event.wait()
                    break
                except Exception as exc:
                    self._logger.exception("%s connection failed: %s", self.runtime_label, exc)
                if not self._stop_event.is_set():
                    delay = backoff.next_delay()
                    self._logger.info("%s reconnecting in %.1fs", self.runtime_label, delay)
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        ws = self._active_ws
        if ws is not None:
            with contextlib.suppress(Exception):
                await self._send_ws_json(ws, build_goodbye(self.config, reason="shutdown"))
            with contextlib.suppress(Exception):
                await ws.close()

    def build_hello_message(self) -> dict[str, Any]:
        return build_hello(self.config)

    def build_tools_snapshot_message(self, *, revision: int) -> dict[str, Any]:
        return build_tools_snapshot(
            self.config,
            revision=revision,
            capabilities=self.registry.tool_definitions(),
        )

    def build_heartbeat_message(self, *, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        return build_heartbeat(self.config, metrics=metrics)

    def build_call_accepted_message(self, *, call_id: str, correlation_id: str) -> dict[str, Any]:
        return build_call_accepted(self.config, call_id=call_id, correlation_id=correlation_id)

    def build_call_progress_message(self, *, call_id: str, correlation_id: str, phase: str, detail: str) -> dict[str, Any]:
        return build_call_progress(
            self.config,
            call_id=call_id,
            correlation_id=correlation_id,
            phase=phase,
            detail=detail,
        )

    def build_call_result_message(self, *, call_id: str, correlation_id: str, outcome: ToolExecutionOutcome) -> dict[str, Any]:
        return build_call_result(
            self.config,
            call_id=call_id,
            correlation_id=correlation_id,
            result=outcome.result,
        )

    def build_call_error_message(
        self,
        *,
        call_id: str,
        correlation_id: str,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> dict[str, Any]:
        return build_call_error(
            self.config,
            call_id=call_id,
            correlation_id=correlation_id,
            code=code,
            message=message,
            retryable=retryable,
        )

    def collect_metrics(self) -> dict[str, Any]:
        return build_heartbeat_metrics(
            active_calls=self._active_call_count,
            capability_count=len(self.registry.names()),
        )

    def call_progress_detail(self, tool_key: str) -> str:
        return f"Dispatching Raspberry Pi capability {tool_key}"

    def allows_parallel_tool(self, tool_key: str) -> bool:
        definition = self.registry.get(tool_key)
        return bool(definition and definition.safe_parallel)

    async def execute_tool(
        self,
        *,
        tool_key: str,
        tool_id: str = "",
        arguments: dict[str, Any],
        envelope_payload: dict[str, Any],
        session,
    ) -> ToolExecutionOutcome:
        del tool_id, session
        call_id = str(envelope_payload.get("call_id") or "").strip()
        operation_id = str(envelope_payload.get("operation_id") or call_id).strip()
        timeout_seconds = envelope_payload.get("timeout_seconds")
        try:
            normalized_timeout = float(timeout_seconds) if timeout_seconds is not None else None
        except (TypeError, ValueError):
            normalized_timeout = None
        request = OperationRequest(
            operation_id=operation_id,
            call_id=call_id,
            capability_name=tool_key,
            arguments=dict(arguments or {}),
            timeout_seconds=normalized_timeout,
        )
        final = await self.operation_runner.run(request)
        if final.succeeded:
            return ToolExecutionOutcome(result=final.payload)
        error = dict(final.error or {})
        raise ToolExecutionError(
            str(error.get("code") or "operation_failed"),
            str(error.get("message") or "Operation failed"),
            retryable=bool(error.get("retryable", False)),
        )
