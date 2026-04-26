from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


CLIENT_TOOL_PROTOCOL_SCHEMA = "meetyou.client.ws.v1"
CLIENT_TOOL_SCHEMA = CLIENT_TOOL_PROTOCOL_SCHEMA
CLIENT_TOOL_WS_SCHEMA = CLIENT_TOOL_PROTOCOL_SCHEMA
CLIENT_TOOL_ARGUMENTS_PURPOSE = "client.tool.arguments.v1"
CLIENT_TOOL_PROTOCOL_VERSION = 1
CLIENT_TOOL_FEATURE_TOOL_SNAPSHOT_OPTIONAL = "tool_snapshot_optional"
CLIENT_TOOL_FEATURE_CONNECTION_PROMPT = "connection_prompt"
CLIENT_TOOL_FEATURE_FEATURE_NEGOTIATION = "feature_negotiation"
CLIENT_TOOL_FEATURE_HEARTBEAT_INTERVAL_NEGOTIATION = "heartbeat_interval_negotiation"
CLIENT_TOOL_FEATURE_HELLO_REJECT_REASON = "hello_reject_reason"
DEFAULT_CLIENT_TOOL_PROTOCOL_FEATURES = (
    CLIENT_TOOL_FEATURE_TOOL_SNAPSHOT_OPTIONAL,
    CLIENT_TOOL_FEATURE_CONNECTION_PROMPT,
    CLIENT_TOOL_FEATURE_FEATURE_NEGOTIATION,
    CLIENT_TOOL_FEATURE_HEARTBEAT_INTERVAL_NEGOTIATION,
    CLIENT_TOOL_FEATURE_HELLO_REJECT_REASON,
)
LEGACY_CLIENT_TOOL_PROTOCOL_FEATURES = (
    CLIENT_TOOL_FEATURE_CONNECTION_PROMPT,
    CLIENT_TOOL_FEATURE_HEARTBEAT_INTERVAL_NEGOTIATION,
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


def build_client_tool_protocol_offer(
    *,
    schema_name: str = CLIENT_TOOL_PROTOCOL_SCHEMA,
    version: int = CLIENT_TOOL_PROTOCOL_VERSION,
    supported_schemas: Iterable[Any] | None = None,
    supported_versions: Iterable[Any] | None = None,
    features: Iterable[Any] | None = None,
    required_features: Iterable[Any] | None = None,
) -> dict[str, Any]:
    selected_schema = str(schema_name or CLIENT_TOOL_PROTOCOL_SCHEMA).strip() or CLIENT_TOOL_PROTOCOL_SCHEMA
    selected_version = int(version or CLIENT_TOOL_PROTOCOL_VERSION)
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


def infer_client_tool_protocol_offer(
    protocol: Any,
    *,
    envelope_schema: str = CLIENT_TOOL_PROTOCOL_SCHEMA,
    default_features: Iterable[Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(protocol, dict) or not protocol:
        return build_client_tool_protocol_offer(
            schema_name=envelope_schema,
            version=CLIENT_TOOL_PROTOCOL_VERSION,
            features=default_features or [],
        )
    return build_client_tool_protocol_offer(
        schema_name=protocol.get("schema") or envelope_schema,
        version=protocol.get("version") or CLIENT_TOOL_PROTOCOL_VERSION,
        supported_schemas=protocol.get("supported_schemas") or [protocol.get("schema") or envelope_schema],
        supported_versions=protocol.get("supported_versions") or [protocol.get("version") or CLIENT_TOOL_PROTOCOL_VERSION],
        features=protocol.get("features") or [],
        required_features=protocol.get("required_features") or [],
    )


def build_client_tool_protocol_selection(
    *,
    selected_schema: str = CLIENT_TOOL_PROTOCOL_SCHEMA,
    selected_version: int = CLIENT_TOOL_PROTOCOL_VERSION,
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


def build_client_reject_reason(code: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "code": str(code or "client_handshake_rejected").strip() or "client_handshake_rejected",
        "message": str(message or "client handshake rejected").strip() or "client handshake rejected",
        "details": dict(details or {}),
    }


class ClientEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: str = Field(default=CLIENT_TOOL_PROTOCOL_SCHEMA, alias="schema")
    type: str
    message_id: str
    sent_at: str
    client_id: str
    correlation_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class ClientHelloPayload(BaseModel):
    client_type: str
    display_name: str
    transport_profile: str
    workspace_ids: list[str] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    executable_tools: list[str] = Field(default_factory=list)
    supports_offline_cache: bool = False
    host: dict[str, Any] = Field(default_factory=dict)
    protocol: dict[str, Any] = Field(default_factory=dict)


class ClientToolsSnapshotPayload(BaseModel):
    revision: int
    tools: list[dict[str, Any]] = Field(default_factory=list)


class ClientHeartbeatPayload(BaseModel):
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
    attachment_outputs: list[dict[str, Any]] = Field(default_factory=list)
    finished_at: str = ""


class ToolCallErrorPayload(BaseModel):
    call_id: str
    status: str = "failed"
    error: dict[str, Any] = Field(default_factory=dict)
    finished_at: str = ""


def build_client_envelope(
    *,
    envelope_type: str,
    client_id: str,
    payload: dict[str, Any],
    message_id: str,
    correlation_id: str = "",
) -> dict[str, Any]:
    return ClientEnvelope(
        type=envelope_type,
        message_id=message_id,
        sent_at=utcnow_iso(),
        client_id=client_id,
        correlation_id=correlation_id,
        payload=payload,
    ).model_dump(by_alias=True)


def build_client_hello(
    *,
    client_id: str,
    client_type: str,
    display_name: str,
    transport_profile: str,
    workspace_ids: list[str],
    available_tools: list[str] | None = None,
    executable_tools: list[str] | None = None,
    supports_offline_cache: bool = False,
    host: dict[str, Any] | None = None,
    protocol_features: Iterable[Any] | None = DEFAULT_CLIENT_TOOL_PROTOCOL_FEATURES,
    required_protocol_features: Iterable[Any] | None = None,
    supported_schemas: Iterable[Any] | None = None,
    supported_versions: Iterable[Any] | None = None,
) -> dict[str, Any]:
    return build_client_envelope(
        envelope_type="client.hello",
        client_id=client_id,
        message_id=f"msg_{uuid4().hex}",
        payload={
            "client_type": client_type,
            "display_name": display_name,
            "transport_profile": transport_profile,
            "workspace_ids": list(workspace_ids or []),
            "available_tools": list(available_tools or []),
            "executable_tools": list(executable_tools or []),
            "supports_offline_cache": bool(supports_offline_cache),
            "host": dict(host or {}),
            "protocol": build_client_tool_protocol_offer(
                schema_name=CLIENT_TOOL_PROTOCOL_SCHEMA,
                version=CLIENT_TOOL_PROTOCOL_VERSION,
                supported_schemas=supported_schemas,
                supported_versions=supported_versions,
                features=protocol_features,
                required_features=required_protocol_features,
            ),
        },
    )


def build_client_tools_snapshot(*, client_id: str, revision: int, tools: list[dict[str, Any]]) -> dict[str, Any]:
    return build_client_envelope(
        envelope_type="client.tools.snapshot",
        client_id=client_id,
        message_id=f"msg_{uuid4().hex}",
        payload={
            "revision": revision,
            "tools": list(tools or []),
        },
    )


def build_client_heartbeat(*, client_id: str, status: str = "ready", metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_client_envelope(
        envelope_type="client.heartbeat",
        client_id=client_id,
        message_id=f"msg_{uuid4().hex}",
        payload={
            "status": status,
            "metrics": dict(metrics or {}),
        },
    )


def build_tool_call_accepted_message(*, client_id: str, call_id: str, correlation_id: str) -> dict[str, Any]:
    return build_client_envelope(
        envelope_type="tool.call.accepted",
        client_id=client_id,
        message_id=f"msg_{uuid4().hex}",
        correlation_id=correlation_id,
        payload={
            "call_id": call_id,
            "accepted": True,
            "started_at": utcnow_iso(),
        },
    )


def build_tool_call_progress_message(*, client_id: str, call_id: str, correlation_id: str, phase: str, detail: str) -> dict[str, Any]:
    return build_client_envelope(
        envelope_type="tool.call.progress",
        client_id=client_id,
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
    client_id: str,
    call_id: str,
    correlation_id: str,
    result: dict[str, Any],
    attachment_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return build_client_envelope(
        envelope_type="tool.call.result",
        client_id=client_id,
        message_id=f"msg_{uuid4().hex}",
        correlation_id=correlation_id,
        payload={
            "call_id": call_id,
            "status": "succeeded",
            "result": dict(result or {}),
            "attachment_outputs": list(attachment_outputs or []),
            "finished_at": utcnow_iso(),
        },
    )


def build_tool_call_error_message(
    *,
    client_id: str,
    call_id: str,
    correlation_id: str,
    code: str,
    message: str,
    retryable: bool = False,
    category: str = "runtime",
) -> dict[str, Any]:
    return build_client_envelope(
        envelope_type="tool.call.error",
        client_id=client_id,
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


def build_tool_call_request(
    *,
    client_id: str,
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
    return build_client_envelope(
        envelope_type="tool.call.request",
        client_id=client_id,
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


def build_client_message(
    *,
    client_id: str,
    session_id: str,
    content: Any,
    role: str = "assistant",
    event_type: str = "message",
    stream_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_client_envelope(
        envelope_type="client.message",
        client_id=client_id,
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
