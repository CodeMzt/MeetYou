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
from edge_agent.config import EdgeAgentConfig
from platform_layer.detector import normalize_platform_system


def build_static_capabilities(config: EdgeAgentConfig, *, extra_capabilities: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    workspace_ids = list(config.workspace_ids)
    agent_id = config.agent_id
    base = [
        {
            "capability_id": build_agent_capability_id(agent_id, "utility.echo"),
            "kind": "tool",
            "title": "Echo Payload",
            "tags": ["edge", "utility", "debug"],
            "abstract_capability_key": "utility.echo",
            "risk_level": "read",
            "requires_confirmation": False,
            "workspace_ids": workspace_ids,
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "echo": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["summary", "echo"],
            },
        },
        {
            "capability_id": build_agent_capability_id(agent_id, "math.add"),
            "kind": "tool",
            "title": "Add Two Numbers",
            "tags": ["edge", "math", "deterministic"],
            "abstract_capability_key": "math.add",
            "risk_level": "read",
            "requires_confirmation": False,
            "workspace_ids": workspace_ids,
            "input_schema": {
                "type": "object",
                "properties": {
                    "left": {"type": "number"},
                    "right": {"type": "number"},
                },
                "required": ["left", "right"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "left": {"type": "number"},
                    "right": {"type": "number"},
                    "result": {"type": "number"},
                    "operation": {"type": "string"},
                },
                "required": ["summary", "result", "operation"],
            },
        },
        {
            "capability_id": build_agent_capability_id(agent_id, "math.divide"),
            "kind": "tool",
            "title": "Divide Two Numbers",
            "tags": ["edge", "math", "deterministic"],
            "abstract_capability_key": "math.divide",
            "risk_level": "read",
            "requires_confirmation": False,
            "workspace_ids": workspace_ids,
            "input_schema": {
                "type": "object",
                "properties": {
                    "left": {"type": "number"},
                    "right": {"type": "number"},
                },
                "required": ["left", "right"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "left": {"type": "number"},
                    "right": {"type": "number"},
                    "result": {"type": "number"},
                    "operation": {"type": "string"},
                },
                "required": ["summary", "result", "operation"],
            },
        }
    ]
    if extra_capabilities:
        base.extend(dict(item) for item in extra_capabilities)
    return base


def build_hello(config: EdgeAgentConfig) -> dict[str, Any]:
    host_os = normalize_platform_system(platform.system())
    return build_agent_hello(
        agent_id=config.agent_id,
        agent_type=config.agent_type,
        display_name=config.display_name,
        transport_profile=config.transport_profile,
        workspace_ids=config.workspace_ids,
        supports_offline_cache=config.supports_offline_cache,
        host={
            "hostname": socket.gethostname(),
            "os": host_os,
            "arch": platform.machine().lower(),
        },
    )


def build_capabilities_snapshot(
    config: EdgeAgentConfig,
    *,
    revision: int = 1,
    extra_capabilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return build_agent_capabilities_snapshot(
        agent_id=config.agent_id,
        revision=revision,
        capabilities=build_static_capabilities(config, extra_capabilities=extra_capabilities),
    )


def build_heartbeat(config: EdgeAgentConfig, *, status: str = "ready", metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_agent_heartbeat(
        agent_id=config.agent_id,
        status=status,
        metrics=metrics,
    )


def build_call_accepted(config: EdgeAgentConfig, *, call_id: str, correlation_id: str) -> dict[str, Any]:
    return build_call_accepted_message(
        agent_id=config.agent_id,
        call_id=call_id,
        correlation_id=correlation_id,
    )


def build_call_progress(config: EdgeAgentConfig, *, call_id: str, correlation_id: str, phase: str, detail: str) -> dict[str, Any]:
    return build_call_progress_message(
        agent_id=config.agent_id,
        call_id=call_id,
        correlation_id=correlation_id,
        phase=phase,
        detail=detail,
    )


def build_call_result(
    config: EdgeAgentConfig,
    *,
    call_id: str,
    correlation_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    return build_call_result_message(
        agent_id=config.agent_id,
        call_id=call_id,
        correlation_id=correlation_id,
        result=result,
    )


def build_call_error(config: EdgeAgentConfig, *, call_id: str, correlation_id: str, code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return build_call_error_message(
        agent_id=config.agent_id,
        call_id=call_id,
        correlation_id=correlation_id,
        code=code,
        message=message,
        retryable=retryable,
    )
