from __future__ import annotations

import platform
import socket
from typing import Any

from endpoint_tool_sdk.protocol import (
    build_endpoint_capabilities_snapshot,
    build_endpoint_heartbeat,
    build_endpoint_hello,
    build_tool_call_accepted_message,
    build_tool_call_error_message,
    build_tool_call_progress_message,
    build_tool_call_result_message,
)
from endpoint_tool_sdk.tool_ids import build_endpoint_tool_id
from edge_client.config import EdgeClientConfig
from platform_layer.detector import normalize_platform_system


EDGE_EXECUTABLE_TOOL_KEYS = ["utility.echo", "math.add", "math.divide"]


def _configured_tool_keys(values: list[str], defaults: list[str]) -> list[str]:
    keys = [str(item).strip() for item in values if str(item).strip()]
    return keys or list(defaults)


def _tool_definition(
    config: EdgeClientConfig,
    tool_key: str,
    *,
    title: str,
    tags: list[str],
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
) -> dict[str, Any]:
    endpoint_id = f"edge.{config.provider_id}.executor"
    return {
        "tool_id": build_endpoint_tool_id(endpoint_id, tool_key),
        "tool_key": tool_key,
        "kind": "tool",
        "title": title,
        "tags": tags,
        "risk_level": "read",
        "requires_confirmation": False,
        "safe_parallel": True,
        "max_concurrency": min(int(getattr(config, "max_parallel_calls", 2) or 2), 4),
        "workspace_ids": list(config.workspace_ids),
        "input_schema": input_schema,
        "output_schema": output_schema,
    }


def build_static_tools(config: EdgeClientConfig, *, extra_tools: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    base = [
        _tool_definition(
            config,
            "utility.echo",
            title="Echo Payload",
            tags=["edge", "utility", "debug"],
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}, "message": {"type": "string"}},
            },
            output_schema={
                "type": "object",
                "properties": {"summary": {"type": "string"}, "echo": {"type": "string"}, "arguments": {"type": "object"}},
                "required": ["summary", "echo"],
            },
        ),
        _tool_definition(
            config,
            "math.add",
            title="Add Two Numbers",
            tags=["edge", "math", "deterministic"],
            input_schema={
                "type": "object",
                "properties": {"left": {"type": "number"}, "right": {"type": "number"}},
                "required": ["left", "right"],
            },
            output_schema={
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
        ),
        _tool_definition(
            config,
            "math.divide",
            title="Divide Two Numbers",
            tags=["edge", "math", "deterministic"],
            input_schema={
                "type": "object",
                "properties": {"left": {"type": "number"}, "right": {"type": "number"}},
                "required": ["left", "right"],
            },
            output_schema={
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
        ),
    ]
    if extra_tools:
        base.extend(dict(item) for item in extra_tools)
    configured_tools = [str(item).strip() for item in getattr(config, "enabled_endpoint_tools", []) if str(item).strip()]
    if not configured_tools:
        return base
    enabled = set(configured_tools)
    return [item for item in base if str(item.get("tool_key") or "").strip() in enabled]


def build_hello(config: EdgeClientConfig) -> dict[str, Any]:
    host_os = normalize_platform_system(platform.system())
    return build_endpoint_hello(
        provider_id=config.provider_id,
        provider_type=config.provider_type,
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


def build_tools_snapshot(config: EdgeClientConfig, *, revision: int = 1, extra_tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return build_endpoint_capabilities_snapshot(
        provider_id=config.provider_id,
        revision=revision,
        capabilities=build_static_tools(config, extra_tools=extra_tools),
        provider_type=config.provider_type,
    )


def build_heartbeat(config: EdgeClientConfig, *, status: str = "ready", metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_endpoint_heartbeat(provider_id=config.provider_id, status=status, metrics=metrics, provider_type=config.provider_type)


def build_call_accepted(config: EdgeClientConfig, *, call_id: str, correlation_id: str) -> dict[str, Any]:
    return build_tool_call_accepted_message(provider_id=config.provider_id, call_id=call_id, correlation_id=correlation_id, provider_type=config.provider_type)


def build_call_progress(config: EdgeClientConfig, *, call_id: str, correlation_id: str, phase: str, detail: str) -> dict[str, Any]:
    return build_tool_call_progress_message(
        provider_id=config.provider_id,
        call_id=call_id,
        correlation_id=correlation_id,
        phase=phase,
        detail=detail,
        provider_type=config.provider_type,
    )


def build_call_result(config: EdgeClientConfig, *, call_id: str, correlation_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return build_tool_call_result_message(provider_id=config.provider_id, call_id=call_id, correlation_id=correlation_id, result=result, provider_type=config.provider_type)


def build_call_error(config: EdgeClientConfig, *, call_id: str, correlation_id: str, code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return build_tool_call_error_message(
        provider_id=config.provider_id,
        call_id=call_id,
        correlation_id=correlation_id,
        code=code,
        message=message,
        retryable=retryable,
        provider_type=config.provider_type,
    )
