from __future__ import annotations

import platform
import socket
from typing import Any

from agent_sdk.capability_ids import build_agent_capability_id
from agent_sdk.protocol import (
    AGENT_SCHEMA,
    build_agent_capabilities_snapshot,
    build_agent_heartbeat,
    build_agent_hello,
    build_call_accepted_message,
    build_call_error_message,
    build_call_progress_message,
    build_call_result_message,
)
from desktop_agent.config import DesktopAgentConfig
from platform_layer.detector import normalize_platform_system


def build_static_capabilities(config: DesktopAgentConfig, *, extra_capabilities: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    workspace_ids = list(config.workspace_ids)
    agent_id = config.agent_id
    base = [
        {
            "capability_id": build_agent_capability_id(agent_id, "utility.echo"),
            "kind": "tool",
            "title": "Echo Payload",
            "tags": ["desktop", "utility", "debug"],
            "risk_level": "read",
            "requires_confirmation": False,
            "workspace_ids": workspace_ids,
        },
        {
            "capability_id": build_agent_capability_id(agent_id, "workspace.analyze"),
            "kind": "tool",
            "title": "Analyze Workspace",
            "tags": ["desktop", "workspace", "read"],
            "risk_level": "read",
            "requires_confirmation": False,
            "workspace_ids": workspace_ids,
        },
        {
            "capability_id": build_agent_capability_id(agent_id, "file.read"),
            "kind": "tool",
            "title": "Read Local File",
            "tags": ["desktop", "documents", "read"],
            "risk_level": "read",
            "requires_confirmation": False,
            "workspace_ids": workspace_ids,
        },
        {
            "capability_id": build_agent_capability_id(agent_id, "file.write"),
            "kind": "tool",
            "title": "Write Local File",
            "tags": ["desktop", "documents", "write"],
            "risk_level": "write",
            "requires_confirmation": True,
            "workspace_ids": workspace_ids,
        },
        {
            "capability_id": build_agent_capability_id(agent_id, "shell.exec"),
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
    host_os = normalize_platform_system(platform.system())
    return build_agent_hello(
        agent_id=config.agent_id,
        agent_type="desktop",
        display_name=config.display_name,
        transport_profile=config.transport_profile,
        owner_client_id=config.owner_client_id,
        owner_client_type=config.owner_client_type,
        owner_client_display_name=config.owner_client_display_name,
        workspace_ids=config.workspace_ids,
        supports_offline_cache=config.supports_offline_cache,
        host={
            "hostname": socket.gethostname(),
            "os": host_os,
            "arch": platform.machine().lower(),
        },
    )


def build_capabilities_snapshot(
    config: DesktopAgentConfig,
    *,
    revision: int = 1,
    extra_capabilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return build_agent_capabilities_snapshot(
        agent_id=config.agent_id,
        revision=revision,
        capabilities=build_static_capabilities(config, extra_capabilities=extra_capabilities),
    )


def build_heartbeat(config: DesktopAgentConfig, *, status: str = "ready", metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_agent_heartbeat(
        agent_id=config.agent_id,
        status=status,
        metrics=metrics,
    )


def build_call_accepted(config: DesktopAgentConfig, *, call_id: str, correlation_id: str) -> dict[str, Any]:
    return build_call_accepted_message(
        agent_id=config.agent_id,
        call_id=call_id,
        correlation_id=correlation_id,
    )


def build_call_progress(config: DesktopAgentConfig, *, call_id: str, correlation_id: str, phase: str, detail: str) -> dict[str, Any]:
    return build_call_progress_message(
        agent_id=config.agent_id,
        call_id=call_id,
        correlation_id=correlation_id,
        phase=phase,
        detail=detail,
    )


def build_call_result(
    config: DesktopAgentConfig,
    *,
    call_id: str,
    correlation_id: str,
    result: dict[str, Any],
    attachment_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return build_call_result_message(
        agent_id=config.agent_id,
        call_id=call_id,
        correlation_id=correlation_id,
        result=result,
        attachment_outputs=attachment_outputs,
    )


def build_call_error(config: DesktopAgentConfig, *, call_id: str, correlation_id: str, code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return build_call_error_message(
        agent_id=config.agent_id,
        call_id=call_id,
        correlation_id=correlation_id,
        code=code,
        message=message,
        retryable=retryable,
    )
