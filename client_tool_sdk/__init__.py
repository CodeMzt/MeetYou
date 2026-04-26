from client_tool_sdk.protocol import (
    CLIENT_TOOL_ARGUMENTS_PURPOSE,
    CLIENT_TOOL_FEATURE_CONNECTION_PROMPT,
    CLIENT_TOOL_FEATURE_FEATURE_NEGOTIATION,
    CLIENT_TOOL_FEATURE_HEARTBEAT_INTERVAL_NEGOTIATION,
    CLIENT_TOOL_FEATURE_HELLO_REJECT_REASON,
    CLIENT_TOOL_FEATURE_TOOL_SNAPSHOT_OPTIONAL,
    CLIENT_TOOL_PROTOCOL_SCHEMA,
    CLIENT_TOOL_PROTOCOL_VERSION,
    CLIENT_TOOL_SCHEMA,
    CLIENT_TOOL_WS_SCHEMA,
    DEFAULT_CLIENT_TOOL_PROTOCOL_FEATURES,
    LEGACY_CLIENT_TOOL_PROTOCOL_FEATURES,
    build_client_envelope,
    build_client_heartbeat,
    build_client_hello,
    build_client_message,
    build_client_reject_reason,
    build_client_tool_protocol_offer,
    build_client_tool_protocol_selection,
    build_client_tools_snapshot,
    build_tool_call_accepted_message,
    build_tool_call_error_message,
    build_tool_call_progress_message,
    build_tool_call_request,
    build_tool_call_result_message,
    infer_client_tool_protocol_offer,
)
from client_tool_sdk.risk import ToolRiskClassifier


def __getattr__(name: str):
    if name in {"ClientToolRuntimeBase", "ToolExecutionError", "ToolExecutionOutcome"}:
        from client_tool_sdk.runtime import ClientToolRuntimeBase, ToolExecutionError, ToolExecutionOutcome

        values = {
            "ClientToolRuntimeBase": ClientToolRuntimeBase,
            "ToolExecutionError": ToolExecutionError,
            "ToolExecutionOutcome": ToolExecutionOutcome,
        }
        return values[name]
    if name in {
        "CredentialTransportError",
        "ProtectedArguments",
        "contains_sensitive_fields",
        "decrypt_json_payload",
        "encrypt_json_payload",
        "protect_sensitive_arguments",
        "redact_sensitive_fields",
        "resolve_credential_secret",
    }:
        from client_tool_sdk.security import (
            CredentialTransportError,
            ProtectedArguments,
            contains_sensitive_fields,
            decrypt_json_payload,
            encrypt_json_payload,
            protect_sensitive_arguments,
            redact_sensitive_fields,
            resolve_credential_secret,
        )

        values = {
            "CredentialTransportError": CredentialTransportError,
            "ProtectedArguments": ProtectedArguments,
            "contains_sensitive_fields": contains_sensitive_fields,
            "decrypt_json_payload": decrypt_json_payload,
            "encrypt_json_payload": encrypt_json_payload,
            "protect_sensitive_arguments": protect_sensitive_arguments,
            "redact_sensitive_fields": redact_sensitive_fields,
            "resolve_credential_secret": resolve_credential_secret,
        }
        return values[name]
    raise AttributeError(name)


from client_tool_sdk.tool_ids import (
    build_client_tool_id,
    build_client_tool_prefix,
    build_mcp_tool_id,
    slug_tool_segment,
)

__all__ = [
    "CLIENT_TOOL_ARGUMENTS_PURPOSE",
    "CLIENT_TOOL_FEATURE_CONNECTION_PROMPT",
    "CLIENT_TOOL_FEATURE_FEATURE_NEGOTIATION",
    "CLIENT_TOOL_FEATURE_HEARTBEAT_INTERVAL_NEGOTIATION",
    "CLIENT_TOOL_FEATURE_HELLO_REJECT_REASON",
    "CLIENT_TOOL_FEATURE_TOOL_SNAPSHOT_OPTIONAL",
    "CLIENT_TOOL_PROTOCOL_SCHEMA",
    "CLIENT_TOOL_PROTOCOL_VERSION",
    "CLIENT_TOOL_SCHEMA",
    "CLIENT_TOOL_WS_SCHEMA",
    "DEFAULT_CLIENT_TOOL_PROTOCOL_FEATURES",
    "LEGACY_CLIENT_TOOL_PROTOCOL_FEATURES",
    "ClientToolRuntimeBase",
    "CredentialTransportError",
    "ProtectedArguments",
    "ToolExecutionError",
    "ToolExecutionOutcome",
    "ToolRiskClassifier",
    "build_client_envelope",
    "build_client_heartbeat",
    "build_client_hello",
    "build_client_message",
    "build_client_reject_reason",
    "build_client_tool_id",
    "build_client_tool_prefix",
    "build_client_tool_protocol_offer",
    "build_client_tool_protocol_selection",
    "build_client_tools_snapshot",
    "build_mcp_tool_id",
    "build_tool_call_accepted_message",
    "build_tool_call_error_message",
    "build_tool_call_progress_message",
    "build_tool_call_request",
    "build_tool_call_result_message",
    "contains_sensitive_fields",
    "decrypt_json_payload",
    "encrypt_json_payload",
    "infer_client_tool_protocol_offer",
    "protect_sensitive_arguments",
    "redact_sensitive_fields",
    "resolve_credential_secret",
    "slug_tool_segment",
]
