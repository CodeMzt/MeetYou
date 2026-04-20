from __future__ import annotations

import logging

from agent_sdk.protocol import AGENT_SCHEMA
from agent_sdk.runtime import AgentRuntimeBase, CapabilityExecutionError, CapabilityExecutionOutcome
from edge_agent.config import EdgeAgentConfig
from edge_agent.execution import build_capability_handlers
from edge_agent.protocol import (
    build_call_accepted,
    build_call_error,
    build_call_progress,
    build_call_result,
    build_capabilities_snapshot,
    build_heartbeat,
    build_hello,
)

logger = logging.getLogger("meetyou.edge_agent")


class EdgeAgentRuntime(AgentRuntimeBase):
    def __init__(self, config: EdgeAgentConfig):
        super().__init__(config, handlers=build_capability_handlers(config.agent_id), logger=logger)

    @property
    def protocol_schema(self) -> str:
        return AGENT_SCHEMA

    @property
    def runtime_label(self) -> str:
        return "Edge Agent"

    def build_hello_message(self) -> dict:
        return build_hello(self.config)

    def build_capabilities_snapshot_message(self, *, revision: int) -> dict:
        return build_capabilities_snapshot(self.config, revision=revision)

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

    def build_call_result_message(self, *, call_id: str, correlation_id: str, outcome: CapabilityExecutionOutcome) -> dict:
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
        return {"workspace_count": len(self.config.workspace_ids)}

    def call_progress_detail(self, capability_id: str) -> str:
        del capability_id
        return "Dispatching edge capability handler"

    async def execute_capability(
        self,
        *,
        capability_id: str,
        arguments: dict,
        envelope_payload: dict,
        session,
    ) -> CapabilityExecutionOutcome:
        del envelope_payload, session
        handler = self._handlers.get(capability_id)
        if handler is None:
            raise CapabilityExecutionError("capability_not_implemented", f"Capability not implemented: {capability_id}")
        try:
            result = await handler(arguments)
        except Exception as exc:
            raise CapabilityExecutionError("edge_call_failed", str(exc)) from exc
        return CapabilityExecutionOutcome(result=result)
