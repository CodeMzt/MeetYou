from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


ENDPOINT_TOOL_PROTOCOL_SCHEMA = "meetyou.endpoint.ws.v4"
ENDPOINT_TOOL_SCHEMA = ENDPOINT_TOOL_PROTOCOL_SCHEMA
ENDPOINT_TOOL_WS_SCHEMA = ENDPOINT_TOOL_PROTOCOL_SCHEMA
ENDPOINT_TOOL_ARGUMENTS_PURPOSE = "endpoint.tool.arguments.v4"
ENDPOINT_TOOL_PROTOCOL_VERSION = 4
ENDPOINT_TOOL_FEATURE_TOOL_SNAPSHOT_OPTIONAL = "tool_snapshot_optional"
ENDPOINT_TOOL_FEATURE_CONNECTION_PROMPT = "connection_prompt"
ENDPOINT_TOOL_FEATURE_FEATURE_NEGOTIATION = "feature_negotiation"
ENDPOINT_TOOL_FEATURE_HEARTBEAT_INTERVAL_NEGOTIATION = "heartbeat_interval_negotiation"
ENDPOINT_TOOL_FEATURE_HELLO_REJECT_REASON = "hello_reject_reason"
DEFAULT_ENDPOINT_TOOL_PROTOCOL_FEATURES = (
    ENDPOINT_TOOL_FEATURE_TOOL_SNAPSHOT_OPTIONAL,
    ENDPOINT_TOOL_FEATURE_CONNECTION_PROMPT,
    ENDPOINT_TOOL_FEATURE_FEATURE_NEGOTIATION,
    ENDPOINT_TOOL_FEATURE_HEARTBEAT_INTERVAL_NEGOTIATION,
    ENDPOINT_TOOL_FEATURE_HELLO_REJECT_REASON,
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _unique_str_list(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _unique_int_list(values: Iterable[Any]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def build_endpoint_protocol_offer(
    *,
    schema_name: str = ENDPOINT_TOOL_PROTOCOL_SCHEMA,
    version: int = ENDPOINT_TOOL_PROTOCOL_VERSION,
    supported_schemas: Iterable[Any] | None = None,
    supported_versions: Iterable[Any] | None = None,
    features: Iterable[Any] | None = None,
    required_features: Iterable[Any] | None = None,
) -> dict[str, Any]:
    selected_schema = str(schema_name or ENDPOINT_TOOL_PROTOCOL_SCHEMA).strip() or ENDPOINT_TOOL_PROTOCOL_SCHEMA
    selected_version = int(version or ENDPOINT_TOOL_PROTOCOL_VERSION)
    normalized_schemas = _unique_str_list(supported_schemas or [selected_schema])
    if selected_schema not in normalized_schemas:
        normalized_schemas.insert(0, selected_schema)
    normalized_versions = _unique_int_list(supported_versions or [selected_version])
    if selected_version not in normalized_versions:
        normalized_versions.insert(0, selected_version)
    return {
        "schema": selected_schema,
        "version": selected_version,
        "supported_schemas": normalized_schemas,
        "supported_versions": normalized_versions,
        "features": _unique_str_list(features or []),
        "required_features": _unique_str_list(required_features or []),
    }


def infer_endpoint_protocol_offer(
    protocol: Any,
    *,
    envelope_schema: str = ENDPOINT_TOOL_PROTOCOL_SCHEMA,
    default_features: Iterable[Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(protocol, dict) or not protocol:
        return build_endpoint_protocol_offer(
            schema_name=envelope_schema,
            version=ENDPOINT_TOOL_PROTOCOL_VERSION,
            features=default_features or [],
        )
    return build_endpoint_protocol_offer(
        schema_name=protocol.get("schema") or envelope_schema,
        version=protocol.get("version") or ENDPOINT_TOOL_PROTOCOL_VERSION,
        supported_schemas=protocol.get("supported_schemas") or [protocol.get("schema") or envelope_schema],
        supported_versions=protocol.get("supported_versions") or [protocol.get("version") or ENDPOINT_TOOL_PROTOCOL_VERSION],
        features=protocol.get("features") or [],
        required_features=protocol.get("required_features") or [],
    )


def build_endpoint_protocol_selection(
    *,
    selected_schema: str = ENDPOINT_TOOL_PROTOCOL_SCHEMA,
    selected_version: int = ENDPOINT_TOOL_PROTOCOL_VERSION,
    enabled_features: Iterable[Any] | None = None,
    disabled_features: Iterable[Any] | None = None,
    compatibility_mode: str = "negotiated",
) -> dict[str, Any]:
    return {
        "selected_schema": str(selected_schema or "").strip(),
        "selected_version": int(selected_version or 0),
        "enabled_features": _unique_str_list(enabled_features or []),
        "disabled_features": _unique_str_list(disabled_features or []),
        "compatibility_mode": str(compatibility_mode or "negotiated").strip() or "negotiated",
    }


def build_endpoint_reject_reason(code: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "code": str(code or "endpoint_handshake_rejected").strip() or "endpoint_handshake_rejected",
        "message": str(message or "endpoint handshake rejected").strip() or "endpoint handshake rejected",
        "details": dict(details or {}),
    }


class EndpointEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: str = Field(default=ENDPOINT_TOOL_PROTOCOL_SCHEMA, alias="schema")
    type: str
    message_id: str
    sent_at: str
    endpoint_id: str
    correlation_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class EndpointHelloPayload(BaseModel):
    provider_type: str = "desktop"
    provider_id: str
    display_name: str
    transport_profile: str
    workspace_ids: list[str] = Field(default_factory=list)
    endpoints: list[dict[str, Any]] = Field(default_factory=list)
    supports_offline_cache: bool = False
    supports_markdown: bool = True
    host: dict[str, Any] = Field(default_factory=dict)
    protocol: dict[str, Any] = Field(default_factory=dict)


class EndpointCapabilitiesSnapshotPayload(BaseModel):
    revision: int
    capabilities: list[dict[str, Any]] = Field(default_factory=list)


class EndpointHeartbeatPayload(BaseModel):
    status: str = "ready"
    metrics: dict[str, Any] = Field(default_factory=dict)


class ToolCallAcceptedPayload(BaseModel):
    call_id: str
    accepted: bool = True
    started_at: str = ""


class ToolCallProgressPayload(BaseModel):
    call_id: str
    phase: str = "running"
    detail: str = ""


class ToolCallResultPayload(BaseModel):
    call_id: str
    status: str = "succeeded"
    result: dict[str, Any] = Field(default_factory=dict)
    finished_at: str = ""


class ToolCallErrorPayload(BaseModel):
    call_id: str
    status: str = "failed"
    error: dict[str, Any] = Field(default_factory=dict)
    finished_at: str = ""


class ToolCallCancelPayload(BaseModel):
    call_id: str
    reason: str = ""
    cancelled_at: str = ""


def build_endpoint_envelope(
    *,
    envelope_type: str,
    endpoint_id: str,
    payload: dict[str, Any],
    message_id: str,
    correlation_id: str = "",
) -> dict[str, Any]:
    return EndpointEnvelope(
        type=envelope_type,
        message_id=message_id,
        sent_at=utcnow_iso(),
        endpoint_id=str(endpoint_id or "").strip(),
        correlation_id=correlation_id,
        payload=payload,
    ).model_dump(by_alias=True)


def _endpoint_rows(provider_id: str, provider_type: str, workspace_ids: list[str], *, supports_markdown: bool = True) -> list[dict[str, Any]]:
    if provider_type == "edge":
        return [
            {
                "endpoint_id": f"edge.{provider_id}.executor",
                "endpoint_type": "edge_executor",
                "roles": ["execution"],
                "workspace_ids": list(workspace_ids or []),
                "supports_markdown": bool(supports_markdown),
            }
        ]
    return [
        {
            "endpoint_id": f"{provider_type}.{provider_id}.ui",
            "endpoint_type": f"{provider_type}_ui",
            "roles": ["input", "output"],
            "workspace_ids": list(workspace_ids or []),
            "supports_markdown": bool(supports_markdown),
        },
        {
            "endpoint_id": f"{provider_type}.{provider_id}.executor",
            "endpoint_type": f"{provider_type}_executor",
            "roles": ["execution"],
            "workspace_ids": list(workspace_ids or []),
            "supports_markdown": bool(supports_markdown),
        },
    ]


def _executor_endpoint_id(provider_id: str, provider_type: str = "desktop") -> str:
    normalized_provider_id = str(provider_id or "").strip()
    normalized_provider_type = str(provider_type or "desktop").strip() or "desktop"
    return f"{normalized_provider_type}.{normalized_provider_id}.executor"


def build_endpoint_hello(
    *,
    provider_id: str,
    provider_type: str,
    display_name: str,
    transport_profile: str,
    workspace_ids: list[str],
    supports_offline_cache: bool = False,
    supports_markdown: bool = True,
    host: dict[str, Any] | None = None,
    protocol_features: Iterable[Any] | None = DEFAULT_ENDPOINT_TOOL_PROTOCOL_FEATURES,
    required_protocol_features: Iterable[Any] | None = None,
    supported_schemas: Iterable[Any] | None = None,
    supported_versions: Iterable[Any] | None = None,
) -> dict[str, Any]:
    normalized_provider_id = str(provider_id or "").strip()
    normalized_provider_type = str(provider_type or "desktop").strip() or "desktop"
    endpoints = _endpoint_rows(
        normalized_provider_id,
        normalized_provider_type,
        workspace_ids,
        supports_markdown=bool(supports_markdown),
    )
    executor_endpoint_id = str(endpoints[-1]["endpoint_id"])
    return build_endpoint_envelope(
        envelope_type="endpoint.hello",
        endpoint_id=executor_endpoint_id,
        message_id=f"msg_{uuid4().hex}",
        payload={
            "provider": {
                "provider_type": normalized_provider_type,
                "provider_id": normalized_provider_id,
                "display_name": display_name,
                "transport_profile": transport_profile,
                "supports_offline_cache": bool(supports_offline_cache),
                "supports_markdown": bool(supports_markdown),
                "host": dict(host or {}),
            },
            "endpoints": endpoints,
            "supports_offline_cache": bool(supports_offline_cache),
            "supports_markdown": bool(supports_markdown),
            "host": dict(host or {}),
            "protocol": build_endpoint_protocol_offer(
                schema_name=ENDPOINT_TOOL_PROTOCOL_SCHEMA,
                version=ENDPOINT_TOOL_PROTOCOL_VERSION,
                supported_schemas=supported_schemas,
                supported_versions=supported_versions,
                features=protocol_features,
                required_features=required_protocol_features,
            ),
        },
    )


def build_endpoint_capabilities_snapshot(
    *,
    provider_id: str,
    revision: int,
    capabilities: list[dict[str, Any]],
    provider_type: str = "desktop",
) -> dict[str, Any]:
    endpoint_id = _executor_endpoint_id(provider_id, provider_type)
    return build_endpoint_envelope(
        envelope_type="endpoint.capabilities.snapshot",
        endpoint_id=endpoint_id,
        message_id=f"msg_{uuid4().hex}",
        payload={
            "endpoint_id": endpoint_id,
            "revision": revision,
            "capabilities": list(capabilities or []),
        },
    )


def build_endpoint_heartbeat(
    *,
    provider_id: str,
    status: str = "ready",
    metrics: dict[str, Any] | None = None,
    provider_type: str = "desktop",
) -> dict[str, Any]:
    endpoint_id = _executor_endpoint_id(provider_id, provider_type)
    return build_endpoint_envelope(
        envelope_type="endpoint.heartbeat",
        endpoint_id=endpoint_id,
        message_id=f"msg_{uuid4().hex}",
        payload={
            "endpoint_id": endpoint_id,
            "status": status,
            "metrics": dict(metrics or {}),
        },
    )


def build_tool_call_accepted_message(*, provider_id: str, call_id: str, correlation_id: str, provider_type: str = "desktop") -> dict[str, Any]:
    return build_endpoint_envelope(
        envelope_type="tool.call.accepted",
        endpoint_id=_executor_endpoint_id(provider_id, provider_type),
        message_id=f"msg_{uuid4().hex}",
        correlation_id=correlation_id,
        payload={
            "call_id": call_id,
            "accepted": True,
            "started_at": utcnow_iso(),
        },
    )


def build_tool_call_progress_message(
    *,
    provider_id: str,
    call_id: str,
    correlation_id: str,
    phase: str,
    detail: str,
    provider_type: str = "desktop",
) -> dict[str, Any]:
    return build_endpoint_envelope(
        envelope_type="tool.call.progress",
        endpoint_id=_executor_endpoint_id(provider_id, provider_type),
        message_id=f"msg_{uuid4().hex}",
        correlation_id=correlation_id,
        payload={
            "call_id": call_id,
            "phase": phase,
            "detail": detail,
        },
    )


def build_tool_call_result_message(
    *,
    provider_id: str,
    call_id: str,
    correlation_id: str,
    result: dict[str, Any],
    provider_type: str = "desktop",
) -> dict[str, Any]:
    return build_endpoint_envelope(
        envelope_type="tool.call.result",
        endpoint_id=_executor_endpoint_id(provider_id, provider_type),
        message_id=f"msg_{uuid4().hex}",
        correlation_id=correlation_id,
        payload={
            "call_id": call_id,
            "status": "succeeded",
            "result": dict(result or {}),
            "finished_at": utcnow_iso(),
        },
    )


def build_tool_call_error_message(
    *,
    provider_id: str,
    call_id: str,
    correlation_id: str,
    code: str,
    message: str,
    retryable: bool = False,
    category: str = "runtime",
    provider_type: str = "desktop",
) -> dict[str, Any]:
    return build_endpoint_envelope(
        envelope_type="tool.call.error",
        endpoint_id=_executor_endpoint_id(provider_id, provider_type),
        message_id=f"msg_{uuid4().hex}",
        correlation_id=correlation_id,
        payload={
            "call_id": call_id,
            "status": "failed",
            "error": {
                "code": code,
                "category": category,
                "message": message,
                "retryable": retryable,
            },
            "finished_at": utcnow_iso(),
        },
    )


def build_tool_call_cancel_message(
    *,
    endpoint_id: str,
    call_id: str,
    message_id: str = "",
    correlation_id: str = "",
    reason: str = "",
) -> dict[str, Any]:
    return build_endpoint_envelope(
        envelope_type="tool.call.cancel",
        endpoint_id=str(endpoint_id or "").strip(),
        message_id=message_id or f"msg_{uuid4().hex}",
        correlation_id=correlation_id,
        payload={
            "call_id": str(call_id or "").strip(),
            "reason": str(reason or "").strip(),
            "cancelled_at": utcnow_iso(),
        },
    )


def build_tool_call_request(
    *,
    endpoint_id: str,
    message_id: str,
    operation_id: str,
    call_id: str,
    workspace_id: str,
    tool_id: str,
    tool_key: str,
    arguments: dict[str, Any],
    encrypted_arguments: dict[str, Any] | None = None,
    approval: dict[str, Any] | None = None,
    timeout_seconds: int = 60,
    audit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_endpoint_envelope(
        envelope_type="tool.call.request",
        endpoint_id=str(endpoint_id or "").strip(),
        message_id=message_id,
        payload={
            "operation_id": operation_id,
            "call_id": call_id,
            "workspace_id": workspace_id,
            "tool_id": tool_id,
            "tool_key": tool_key,
            "arguments": dict(arguments or {}),
            "encrypted_arguments": dict(encrypted_arguments or {}) if encrypted_arguments else {},
            "approval": dict(approval or {}),
            "timeout_seconds": timeout_seconds,
            "audit_context": dict(audit_context or {}),
        },
    )


def build_endpoint_message(
    *,
    endpoint_id: str,
    session_id: str,
    content: Any,
    role: str = "assistant",
    event_type: str = "message",
    stream_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_endpoint_envelope(
        envelope_type="delivery.message",
        endpoint_id=endpoint_id,
        message_id=f"msg_{uuid4().hex}",
        payload={
            "session_id": str(session_id or "").strip(),
            "event_type": str(event_type or "message").strip() or "message",
            "role": str(role or "assistant").strip() or "assistant",
            "content": content,
            "stream_id": str(stream_id or "").strip(),
            "metadata": dict(metadata or {}),
        },
    )
