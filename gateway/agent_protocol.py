from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


AGENT_WS_SCHEMA = "meetyou.agent.v1"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class AgentEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: str = Field(default=AGENT_WS_SCHEMA, alias="schema")
    type: str
    message_id: str
    sent_at: str
    agent_id: str
    correlation_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentHelloPayload(BaseModel):
    agent_type: str
    display_name: str
    transport_profile: str
    owner_client_id: str = ""
    owner_client_type: str = ""
    owner_client_display_name: str = ""
    workspace_ids: list[str] = Field(default_factory=list)
    supports_offline_cache: bool = False
    host: dict[str, Any] = Field(default_factory=dict)


class AgentCapabilitiesSnapshotPayload(BaseModel):
    revision: int
    capabilities: list[dict[str, Any]] = Field(default_factory=list)


class AgentHeartbeatPayload(BaseModel):
    status: str = "ready"
    metrics: dict[str, Any] = Field(default_factory=dict)


class CapabilityCallAcceptedPayload(BaseModel):
    call_id: str
    accepted: bool = True
    started_at: str = ""


class CapabilityCallProgressPayload(BaseModel):
    call_id: str
    phase: str = "running"
    detail: str = ""


class CapabilityCallResultPayload(BaseModel):
    call_id: str
    status: str = "succeeded"
    result: dict[str, Any] = Field(default_factory=dict)
    attachment_outputs: list[dict[str, Any]] = Field(default_factory=list)
    finished_at: str = ""


class CapabilityCallErrorPayload(BaseModel):
    call_id: str
    status: str = "failed"
    error: dict[str, Any] = Field(default_factory=dict)
    finished_at: str = ""


def build_agent_envelope(*, envelope_type: str, agent_id: str, payload: dict[str, Any], message_id: str, correlation_id: str = "") -> dict[str, Any]:
    return AgentEnvelope(
        type=envelope_type,
        message_id=message_id,
        sent_at=utcnow_iso(),
        agent_id=agent_id,
        correlation_id=correlation_id,
        payload=payload,
    ).model_dump(by_alias=True)


def build_capability_call_request(
    *,
    agent_id: str,
    message_id: str,
    operation_id: str,
    call_id: str,
    workspace_id: str,
    capability_id: str,
    arguments: dict[str, Any],
    approval: dict[str, Any] | None = None,
    timeout_seconds: int = 60,
    audit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_agent_envelope(
        envelope_type="capability.call.request",
        agent_id=agent_id,
        message_id=message_id,
        payload={
            "operation_id": operation_id,
            "call_id": call_id,
            "workspace_id": workspace_id,
            "capability_id": capability_id,
            "arguments": dict(arguments or {}),
            "approval": dict(approval or {}),
            "timeout_seconds": timeout_seconds,
            "audit_context": dict(audit_context or {}),
        },
    )
