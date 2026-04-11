from __future__ import annotations

import platform
import socket
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from desktop_agent.config import DesktopAgentConfig


AGENT_SCHEMA = "meetyou.agent.v1"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_envelope(*, envelope_type: str, agent_id: str, payload: dict[str, Any], correlation_id: str = "") -> dict[str, Any]:
    return {
        "schema": AGENT_SCHEMA,
        "type": envelope_type,
        "message_id": f"msg_{uuid4().hex}",
        "sent_at": utcnow_iso(),
        "agent_id": agent_id,
        "correlation_id": correlation_id,
        "payload": payload,
    }


def build_static_capabilities(config: DesktopAgentConfig, *, extra_capabilities: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    workspace_ids = list(config.workspace_ids)
    agent_id = config.agent_id
    base = [
        {
            "capability_id": f"agent.{agent_id}.utility.echo",
            "kind": "tool",
            "title": "Echo Payload",
            "tags": ["desktop", "utility", "debug"],
            "risk_level": "read",
            "requires_confirmation": False,
            "workspace_ids": workspace_ids,
        },
        {
            "capability_id": f"agent.{agent_id}.workspace.analyze",
            "kind": "tool",
            "title": "Analyze Workspace",
            "tags": ["desktop", "workspace", "read"],
            "risk_level": "read",
            "requires_confirmation": False,
            "workspace_ids": workspace_ids,
        },
        {
            "capability_id": f"agent.{agent_id}.file.read",
            "kind": "tool",
            "title": "Read Local File",
            "tags": ["desktop", "documents", "read"],
            "risk_level": "read",
            "requires_confirmation": False,
            "workspace_ids": workspace_ids,
        },
        {
            "capability_id": f"agent.{agent_id}.file.write",
            "kind": "tool",
            "title": "Write Local File",
            "tags": ["desktop", "documents", "write"],
            "risk_level": "write",
            "requires_confirmation": True,
            "workspace_ids": workspace_ids,
        },
        {
            "capability_id": f"agent.{agent_id}.shell.exec",
            "kind": "tool",
            "title": "Execute Local Command",
            "tags": ["desktop", "system", "shell"],
            "risk_level": "system",
            "requires_confirmation": True,
            "workspace_ids": workspace_ids,
        },
    ]
    if extra_capabilities:
        base.extend(dict(item) for item in extra_capabilities)
    return base


def build_hello(config: DesktopAgentConfig) -> dict[str, Any]:
    return make_envelope(
        envelope_type="agent.hello",
        agent_id=config.agent_id,
        payload={
            "agent_type": "desktop",
            "display_name": config.display_name,
            "transport_profile": config.transport_profile,
            "owner_client_id": config.owner_client_id,
            "owner_client_type": config.owner_client_type,
            "owner_client_display_name": config.owner_client_display_name,
            "workspace_ids": config.workspace_ids,
            "supports_offline_cache": config.supports_offline_cache,
            "host": {
                "hostname": socket.gethostname(),
                "os": platform.system().lower(),
                "arch": platform.machine().lower(),
            },
        },
    )


def build_capabilities_snapshot(
    config: DesktopAgentConfig,
    *,
    revision: int = 1,
    extra_capabilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return make_envelope(
        envelope_type="agent.capabilities.snapshot",
        agent_id=config.agent_id,
        payload={
            "revision": revision,
            "capabilities": build_static_capabilities(config, extra_capabilities=extra_capabilities),
        },
    )


def build_heartbeat(config: DesktopAgentConfig, *, status: str = "ready", metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    return make_envelope(
        envelope_type="agent.heartbeat",
        agent_id=config.agent_id,
        payload={
            "status": status,
            "metrics": dict(metrics or {}),
        },
    )


def build_call_accepted(config: DesktopAgentConfig, *, call_id: str, correlation_id: str) -> dict[str, Any]:
    return make_envelope(
        envelope_type="capability.call.accepted",
        agent_id=config.agent_id,
        correlation_id=correlation_id,
        payload={
            "call_id": call_id,
            "accepted": True,
            "started_at": utcnow_iso(),
        },
    )


def build_call_progress(config: DesktopAgentConfig, *, call_id: str, correlation_id: str, phase: str, detail: str) -> dict[str, Any]:
    return make_envelope(
        envelope_type="capability.call.progress",
        agent_id=config.agent_id,
        correlation_id=correlation_id,
        payload={
            "call_id": call_id,
            "phase": phase,
            "detail": detail,
        },
    )


def build_call_result(
    config: DesktopAgentConfig,
    *,
    call_id: str,
    correlation_id: str,
    result: dict[str, Any],
    attachment_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return make_envelope(
        envelope_type="capability.call.result",
        agent_id=config.agent_id,
        correlation_id=correlation_id,
        payload={
            "call_id": call_id,
            "status": "succeeded",
            "result": dict(result or {}),
            "attachment_outputs": list(attachment_outputs or []),
            "finished_at": utcnow_iso(),
        },
    )


def build_call_error(config: DesktopAgentConfig, *, call_id: str, correlation_id: str, code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return make_envelope(
        envelope_type="capability.call.error",
        agent_id=config.agent_id,
        correlation_id=correlation_id,
        payload={
            "call_id": call_id,
            "status": "failed",
            "error": {
                "code": code,
                "category": "runtime",
                "message": message,
                "retryable": retryable,
            },
            "finished_at": utcnow_iso(),
        },
    )
