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
from desktop_client.config import DesktopClientConfig
from platform_layer.detector import normalize_platform_system


DESKTOP_EXECUTABLE_TOOL_KEYS = [
    "utility.echo",
    "workspace.analyze",
    "file.read",
    "file.write",
    "shell.exec",
]


def _configured_tool_keys(values: list[str], defaults: list[str]) -> list[str]:
    keys = [str(item).strip() for item in values if str(item).strip()]
    return keys or list(defaults)


def build_static_tools(config: DesktopClientConfig, *, extra_tools: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    workspace_ids = list(config.workspace_ids)
    provider_id = config.provider_id
    executor_endpoint_id = f"desktop.{provider_id}.executor"
    base = [
        {
            "tool_id": build_endpoint_tool_id(executor_endpoint_id, "utility.echo"),
            "tool_key": "utility.echo",
            "kind": "tool",
            "title": "Echo Payload",
            "tags": ["desktop", "utility", "debug"],
            "risk_level": "read",
            "requires_confirmation": False,
            "safe_parallel": True,
            "max_concurrency": min(int(getattr(config, "max_parallel_calls", 2) or 2), 4),
            "workspace_ids": workspace_ids,
        },
        {
            "tool_id": build_endpoint_tool_id(executor_endpoint_id, "workspace.analyze"),
            "tool_key": "workspace.analyze",
            "kind": "tool",
            "title": "Analyze Workspace",
            "description": "Runs on the Desktop Endpoint Provider machine and analyzes directories from that local filesystem.",
            "tags": ["desktop", "workspace", "read"],
            "risk_level": "read",
            "requires_confirmation": False,
            "safe_parallel": True,
            "max_concurrency": min(int(getattr(config, "max_parallel_calls", 2) or 2), 4),
            "workspace_ids": workspace_ids,
        },
        {
            "tool_id": build_endpoint_tool_id(executor_endpoint_id, "file.read"),
            "tool_key": "file.read",
            "kind": "tool",
            "title": "Read Local File",
            "description": "Runs on the Desktop Endpoint Provider machine and reads files from that local filesystem.",
            "tags": ["desktop", "documents", "read"],
            "risk_level": "read",
            "requires_confirmation": False,
            "safe_parallel": True,
            "max_concurrency": min(int(getattr(config, "max_parallel_calls", 2) or 2), 4),
            "workspace_ids": workspace_ids,
        },
        {
            "tool_id": build_endpoint_tool_id(executor_endpoint_id, "file.write"),
            "tool_key": "file.write",
            "kind": "tool",
            "title": "Write Local File",
            "description": "Runs on the Desktop Endpoint Provider machine and writes only within trusted write roots.",
            "tags": ["desktop", "documents", "write"],
            "risk_level": "write",
            "requires_confirmation": True,
            "workspace_ids": workspace_ids,
        },
        {
            "tool_id": build_endpoint_tool_id(executor_endpoint_id, "shell.exec"),
            "tool_key": "shell.exec",
            "kind": "tool",
            "title": "Execute Local Command",
            "description": "Runs on the Desktop Endpoint Provider machine using the configured command policy.",
            "tags": ["desktop", "system", "shell"],
            "risk_level": "system",
            "requires_confirmation": True,
            "workspace_ids": workspace_ids,
        },
    ]
    if extra_tools:
        for item in extra_tools:
            normalized = dict(item)
            tool_key = str(normalized.get("tool_key") or "").strip()
            if tool_key and not normalized.get("tool_id"):
                normalized["tool_id"] = build_endpoint_tool_id(executor_endpoint_id, tool_key)
            base.append(normalized)
    configured_tools = [str(item).strip() for item in getattr(config, "enabled_endpoint_tools", []) if str(item).strip()]
    if not configured_tools:
        return base
    enabled = set(configured_tools)
    return [item for item in base if str(item.get("tool_key") or "").strip() in enabled]


def build_hello(config: DesktopClientConfig, *, extra_tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    del extra_tools
    host_os = normalize_platform_system(platform.system())
    return build_endpoint_hello(
        provider_id=config.provider_id,
        provider_type="desktop",
        display_name=config.display_name,
        transport_profile=config.transport_profile,
        workspace_ids=config.workspace_ids,
        supports_offline_cache=config.supports_offline_cache,
        supports_markdown=config.supports_markdown,
        host={
            "hostname": socket.gethostname(),
            "os": host_os,
            "arch": platform.machine().lower(),
        },
    )


def build_tools_snapshot(
    config: DesktopClientConfig,
    *,
    revision: int = 1,
    extra_tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return build_endpoint_capabilities_snapshot(
        provider_id=config.provider_id,
        revision=revision,
        capabilities=build_static_tools(config, extra_tools=extra_tools),
    )


def build_heartbeat(config: DesktopClientConfig, *, status: str = "ready", metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_endpoint_heartbeat(
        provider_id=config.provider_id,
        status=status,
        metrics=metrics,
    )


def build_call_accepted(config: DesktopClientConfig, *, call_id: str, correlation_id: str) -> dict[str, Any]:
    return build_tool_call_accepted_message(
        provider_id=config.provider_id,
        call_id=call_id,
        correlation_id=correlation_id,
    )


def build_call_progress(config: DesktopClientConfig, *, call_id: str, correlation_id: str, phase: str, detail: str) -> dict[str, Any]:
    return build_tool_call_progress_message(
        provider_id=config.provider_id,
        call_id=call_id,
        correlation_id=correlation_id,
        phase=phase,
        detail=detail,
    )


def build_call_result(
    config: DesktopClientConfig,
    *,
    call_id: str,
    correlation_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    return build_tool_call_result_message(
        provider_id=config.provider_id,
        call_id=call_id,
        correlation_id=correlation_id,
        result=result,
    )


def build_call_error(config: DesktopClientConfig, *, call_id: str, correlation_id: str, code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return build_tool_call_error_message(
        provider_id=config.provider_id,
        call_id=call_id,
        correlation_id=correlation_id,
        code=code,
        message=message,
        retryable=retryable,
    )
