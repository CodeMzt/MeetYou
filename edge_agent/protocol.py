from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


EDGE_AGENT_SCHEMA = "meetyou.edge.v1"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def topic_up(agent_id: str) -> str:
    return f"meetyou/agents/{str(agent_id).strip()}/up"


def topic_down(agent_id: str) -> str:
    return f"meetyou/agents/{str(agent_id).strip()}/down"


def topic_pull(agent_id: str) -> str:
    return f"meetyou/agents/{str(agent_id).strip()}/pull"


def make_envelope(*, message_type: str, agent_id: str, payload: dict[str, Any], correlation_id: str = "") -> dict[str, Any]:
    return {
        "schema": EDGE_AGENT_SCHEMA,
        "type": message_type,
        "message_id": f"msg_{uuid4().hex}",
        "sent_at": utcnow_iso(),
        "agent_id": agent_id,
        "correlation_id": correlation_id,
        "payload": dict(payload or {}),
    }


def build_pull_next(agent_id: str, *, workspace_ids: list[str], capabilities: list[str] | None = None) -> dict[str, Any]:
    return make_envelope(
        message_type="agent.pull.next",
        agent_id=agent_id,
        payload={
            "workspace_ids": list(workspace_ids or []),
            "capabilities": list(capabilities or []),
        },
    )


def build_pull_empty(agent_id: str, *, correlation_id: str, retry_after_seconds: int = 10) -> dict[str, Any]:
    return make_envelope(
        message_type="agent.pull.empty",
        agent_id=agent_id,
        correlation_id=correlation_id,
        payload={
            "retry_after_seconds": max(int(retry_after_seconds), 1),
        },
    )


def build_capability_call_lease(
    agent_id: str,
    *,
    correlation_id: str,
    operation_id: str,
    call_id: str,
    workspace_id: str,
    capability_id: str,
    lease_seconds: int = 60,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return make_envelope(
        message_type="capability.call.lease",
        agent_id=agent_id,
        correlation_id=correlation_id,
        payload={
            "operation_id": operation_id,
            "call_id": call_id,
            "workspace_id": workspace_id,
            "capability_id": capability_id,
            "lease_seconds": max(int(lease_seconds), 1),
            "arguments": dict(arguments or {}),
        },
    )
