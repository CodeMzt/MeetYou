from __future__ import annotations

import asyncio
import logging
from typing import Any

from endpoint_tool_sdk.protocol import ENDPOINT_TOOL_SCHEMA
from endpoint_tool_sdk.runtime import EndpointToolRuntimeBase, ToolExecutionError, ToolExecutionOutcome
from desktop_client.config import DesktopClientConfig
from desktop_client.execution import build_tool_handlers
from desktop_client.mcp_runtime import DesktopClientMCPRuntime
from desktop_client.policy import DesktopClientPolicyError
from desktop_client.protocol import (
    build_call_accepted,
    build_call_error,
    build_call_progress,
    build_call_result,
    build_tools_snapshot,
    build_heartbeat,
    build_hello,
)

logger = logging.getLogger("meetyou.desktop_client")

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None


class DesktopClientRuntime(EndpointToolRuntimeBase):
    def __init__(self, config: DesktopClientConfig):
        self._mcp_runtime = DesktopClientMCPRuntime(config)
        self._mcp_init_task: asyncio.Task | None = None
        self._mcp_ready = False
        super().__init__(config, handlers=build_tool_handlers(config), logger=logger)

    @property
    def protocol_schema(self) -> str:
        return ENDPOINT_TOOL_SCHEMA

    @property
    def runtime_label(self) -> str:
        return "Desktop Endpoint Provider"

    def core_access_token_source_hints(self) -> tuple[str, ...]:
        config_path = str(getattr(self.config, "config_file_path", "")).strip()
        hints = [
            "env `MEETYOU_CLIENT_ACCESS_TOKEN`",
            "env `MEETYOU_GATEWAY_ACCESS_TOKEN`",
        ]
        if config_path:
            hints.append(f"config `{config_path}` -> `core_access_token`")
        return tuple(hints)

    async def startup(self) -> None:
        if self._mcp_init_task is None:
            self._mcp_init_task = asyncio.create_task(self._initialize_mcp_runtime())

    async def shutdown(self) -> None:
        if self._mcp_init_task is not None:
            self._mcp_init_task.cancel()
            with __import__("contextlib").suppress(asyncio.CancelledError):
                await self._mcp_init_task
        await self._mcp_runtime.close()

    async def _initialize_mcp_runtime(self) -> None:
        try:
            await self._mcp_runtime.initialize()
            self._mcp_ready = True
            self._tool_revision += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Desktop Endpoint Provider MCP initialization failed: %s", exc)

    def build_hello_message(self) -> dict[str, Any]:
        return build_hello(self.config)

    def build_tools_snapshot_message(self, *, revision: int) -> dict[str, Any]:
        return build_tools_snapshot(
            self.config,
            revision=revision,
            extra_tools=self._mcp_runtime.tool_definitions() if self._mcp_ready else [],
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

    def call_progress_detail(self, tool_key: str) -> str:
        del tool_key
        return "Dispatching tool handler"

    def allows_parallel_tool(self, tool_key: str) -> bool:
        normalized = str(tool_key or "").strip()
        return normalized in {"utility.echo", "workspace.analyze", "file.read"} or any(
            normalized.endswith(suffix)
            for suffix in (".utility.echo", ".workspace.analyze", ".file.read")
        )

    async def execute_tool(
        self,
        *,
        tool_key: str,
        tool_id: str = "",
        arguments: dict[str, Any],
        envelope_payload: dict[str, Any],
        session,
    ) -> ToolExecutionOutcome:
        del envelope_payload, session
        handler = self._handlers.get(tool_key)
        if handler is None and self._mcp_runtime.can_handle(tool_key):
            try:
                result = await self._mcp_runtime.call_tool(tool_key, arguments)
            except Exception as exc:
                raise ToolExecutionError("mcp_call_failed", str(exc)) from exc
            return ToolExecutionOutcome(result=dict(result or {}))
        if handler is None:
            raise ToolExecutionError("tool_not_implemented", f"Tool not implemented: {tool_key or tool_id}")
        try:
            result = await handler(arguments)
        except DesktopClientPolicyError as exc:
            raise ToolExecutionError(exc.code, exc.message) from exc
        except Exception as exc:
            raise ToolExecutionError("tool_execution_failed", str(exc)) from exc
        return ToolExecutionOutcome(result=dict(result or {}))

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

    def collect_metrics(self) -> dict[str, float | int]:
        metrics = self._collect_metrics()
        metrics["active_calls"] = self._active_call_count
        return metrics
