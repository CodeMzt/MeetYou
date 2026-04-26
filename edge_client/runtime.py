from __future__ import annotations

import logging

from client_tool_sdk.protocol import CLIENT_TOOL_SCHEMA
from client_tool_sdk.runtime import ClientToolRuntimeBase, ToolExecutionError, ToolExecutionOutcome
from edge_client.config import EdgeClientConfig
from edge_client.execution import build_tool_handlers
from edge_client.protocol import (
    build_call_accepted,
    build_call_error,
    build_call_progress,
    build_call_result,
    build_heartbeat,
    build_hello,
    build_tools_snapshot,
)

logger = logging.getLogger("meetyou.edge_client")


class EdgeClientRuntime(ClientToolRuntimeBase):
    def __init__(self, config: EdgeClientConfig):
        super().__init__(config, handlers=build_tool_handlers(), logger=logger)

    @property
    def protocol_schema(self) -> str:
        return CLIENT_TOOL_SCHEMA

    @property
    def runtime_label(self) -> str:
        return "Edge Client"

    def core_access_token_source_hints(self) -> tuple[str, ...]:
        config_path = str(getattr(self.config, "config_file_path", "")).strip()
        hints = [
            "env `MEETYOU_EDGE_CLIENT_ACCESS_TOKEN`",
            "env `MEETYOU_CLIENT_ACCESS_TOKEN`",
            "env `MEETYOU_GATEWAY_ACCESS_TOKEN`",
        ]
        if config_path:
            hints.append(f"config `{config_path}` -> `core_access_token`")
        return tuple(hints)

    def build_hello_message(self) -> dict:
        return build_hello(self.config)

    def build_tools_snapshot_message(self, *, revision: int) -> dict:
        return build_tools_snapshot(self.config, revision=revision)

    def build_heartbeat_message(self, *, metrics: dict | None = None) -> dict:
        return build_heartbeat(self.config, metrics=metrics)

    def build_call_accepted_message(self, *, call_id: str, correlation_id: str) -> dict:
        return build_call_accepted(self.config, call_id=call_id, correlation_id=correlation_id)

    def build_call_progress_message(self, *, call_id: str, correlation_id: str, phase: str, detail: str) -> dict:
        return build_call_progress(
            self.config,
            call_id=call_id,
            correlation_id=correlation_id,
            phase=phase,
            detail=detail,
        )

    def build_call_result_message(self, *, call_id: str, correlation_id: str, outcome: ToolExecutionOutcome) -> dict:
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
    ) -> dict:
        return build_call_error(
            self.config,
            call_id=call_id,
            correlation_id=correlation_id,
            code=code,
            message=message,
            retryable=retryable,
        )

    def collect_metrics(self) -> dict:
        return {"workspace_count": len(self.config.workspace_ids), "active_calls": self._active_call_count}

    def call_progress_detail(self, tool_key: str) -> str:
        del tool_key
        return "Dispatching edge tool handler"

    def allows_parallel_tool(self, tool_key: str) -> bool:
        return str(tool_key or "").strip() in {"utility.echo", "math.add", "math.divide"}

    async def execute_tool(
        self,
        *,
        tool_key: str,
        tool_id: str = "",
        arguments: dict,
        envelope_payload: dict,
        session,
    ) -> ToolExecutionOutcome:
        del tool_id, envelope_payload, session
        handler = self._handlers.get(tool_key)
        if handler is None:
            raise ToolExecutionError("tool_not_implemented", f"Tool not implemented: {tool_key}")
        try:
            result = await handler(arguments)
        except Exception as exc:
            raise ToolExecutionError("edge_call_failed", str(exc)) from exc
        return ToolExecutionOutcome(result=result)
