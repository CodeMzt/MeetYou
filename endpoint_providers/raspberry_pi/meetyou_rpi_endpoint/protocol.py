from __future__ import annotations

import platform
import socket
from typing import Any
from uuid import uuid4

from endpoint_tool_sdk.protocol import (
    DEFAULT_ENDPOINT_TOOL_PROTOCOL_FEATURES,
    ENDPOINT_TOOL_PROTOCOL_SCHEMA,
    ENDPOINT_TOOL_PROTOCOL_VERSION,
    build_endpoint_capabilities_snapshot,
    build_endpoint_envelope,
    build_endpoint_heartbeat,
    build_endpoint_protocol_offer,
    build_tool_call_accepted_message,
    build_tool_call_error_message,
    build_tool_call_progress_message,
    build_tool_call_result_message,
)


def build_hello(config) -> dict[str, Any]:
    endpoint_id = config.executor_endpoint_id
    return build_endpoint_envelope(
        envelope_type="endpoint.hello",
        endpoint_id=endpoint_id,
        message_id=f"msg_{uuid4().hex}",
        payload={
            "provider": {
                "provider_type": config.provider_type,
                "provider_id": config.provider_id,
                "display_name": config.display_name,
                "transport_profile": config.transport_profile,
                "supports_offline_cache": config.supports_offline_cache,
                "supports_markdown": config.supports_markdown,
                "host": _host_payload(),
            },
            "endpoints": [
                {
                    "endpoint_id": endpoint_id,
                    "endpoint_type": "rpi_executor",
                    "provider_type": config.provider_type,
                    "roles": ["execution"],
                    "workspace_ids": list(config.workspace_ids or []),
                    "supports_markdown": config.supports_markdown,
                }
            ],
            "supports_offline_cache": config.supports_offline_cache,
            "supports_markdown": config.supports_markdown,
            "host": _host_payload(),
            "protocol": build_endpoint_protocol_offer(
                schema_name=ENDPOINT_TOOL_PROTOCOL_SCHEMA,
                version=ENDPOINT_TOOL_PROTOCOL_VERSION,
                features=DEFAULT_ENDPOINT_TOOL_PROTOCOL_FEATURES,
            ),
        },
    )


def build_tools_snapshot(config, *, revision: int, capabilities: list[dict[str, Any]]) -> dict[str, Any]:
    return build_endpoint_capabilities_snapshot(
        provider_id=config.provider_id,
        revision=revision,
        capabilities=capabilities,
        provider_type=config.provider_type,
    )


def build_heartbeat(config, *, status: str = "ready", metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_endpoint_heartbeat(
        provider_id=config.provider_id,
        status=status,
        metrics=metrics,
        provider_type=config.provider_type,
    )


def build_goodbye(config, *, reason: str = "shutdown") -> dict[str, Any]:
    return build_endpoint_envelope(
        envelope_type="endpoint.goodbye",
        endpoint_id=config.executor_endpoint_id,
        message_id=f"msg_{uuid4().hex}",
        payload={"endpoint_id": config.executor_endpoint_id, "reason": reason},
    )


def build_call_accepted(config, *, call_id: str, correlation_id: str) -> dict[str, Any]:
    return build_tool_call_accepted_message(
        provider_id=config.provider_id,
        call_id=call_id,
        correlation_id=correlation_id,
        provider_type=config.provider_type,
    )


def build_call_progress(config, *, call_id: str, correlation_id: str, phase: str, detail: str) -> dict[str, Any]:
    return build_tool_call_progress_message(
        provider_id=config.provider_id,
        call_id=call_id,
        correlation_id=correlation_id,
        phase=phase,
        detail=detail,
        provider_type=config.provider_type,
    )


def build_call_result(config, *, call_id: str, correlation_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return build_tool_call_result_message(
        provider_id=config.provider_id,
        call_id=call_id,
        correlation_id=correlation_id,
        result=result,
        provider_type=config.provider_type,
    )


def build_call_error(
    config,
    *,
    call_id: str,
    correlation_id: str,
    code: str,
    message: str,
    retryable: bool = False,
) -> dict[str, Any]:
    return build_tool_call_error_message(
        provider_id=config.provider_id,
        call_id=call_id,
        correlation_id=correlation_id,
        code=code,
        message=message,
        retryable=retryable,
        provider_type=config.provider_type,
    )


def _host_payload() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "os": platform.system().lower(),
        "arch": platform.machine().lower(),
        "python": platform.python_version(),
    }

