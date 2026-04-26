from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import ValidationError

from client_tool_protocol import CLIENT_TOOL_ARGUMENTS_PURPOSE, build_tool_call_request
from core.client_tool_bundles import ensure_client_always_available_tools
from core.credential_transport import CredentialTransportError, decrypt_json_payload, protect_sensitive_arguments
from core.http_headers import build_attachment_content_disposition
from core.io_protocol import EventTarget, EventType, InboundEvent, SourceKind, TargetKind, make_source
from core.public_contract import (
    EXECUTION_TARGET_PREFER_CLIENT_FALLBACK_CORE,
    EXECUTION_TARGET_SPECIFIC_CLIENT,
    EXECUTION_TARGET_WORKSPACE_ANY_CLIENT,
    normalize_execution_target,
    requires_specific_client,
)

from gateway.models import (
    AckPayload,
    AckResponse,
    ClientApprovalDecisionRequest,
    ClientDanxiActionResponse,
    ClientDanxiListResponse,
    ClientDanxiMessageTargetResponse,
    ClientDanxiPostResponse,
    ClientDanxiProfileResponse,
    ClientDanxiReplyCreateRequest,
    ClientDanxiReplyUpdateRequest,
    ClientDanxiSearchResponse,
    ClientDanxiSessionLoginRequest,
    ClientDanxiSessionResponse,
    ClientDanxiSummaryResponse,
    ClientDanxiWebvpnCookiePatchRequest,
    ClientApprovalResponse,
    ClientAttachmentCompleteRequest,
    ClientAttachmentDownloadTicketResponse,
    ClientAttachmentResponse,
    ClientAttachmentUploadResult,
    ClientAttachmentUploadTicketRequest,
    ClientAttachmentUploadTicketResponse,
    ClientConfirmResponseRequest,
    ClientConfirmResponseResult,
    ClientHumanInputResponseRequest,
    ClientHumanInputResponseResult,
        ClientAvailableClientResponse,
    ClientOperationCreateRequest,
    ClientOperationResponse,
    ClientMessageCreateRequest,
    ClientMessageResponse,
    ClientActiveWorkspacePatchRequest,
    ClientProcedureDetailResponse,
    ClientProcedureResponse,
    ClientSessionCreateRequest,
    ClientSessionResponse,
    ClientThreadPinnedProcedureRequest,
    ClientThreadProcedureContextResponse,
    ClientThreadCreateRequest,
    ClientThreadResponse,
    ClientWsCommand,
    ClientWorkspaceResponse,
    ContextPoolQueryResponse,
)
from service_runtime.models import RuntimeError
from tools.danxi_tools import get_shared_danxi_tools


_APPROVAL_RISK_LEVELS = {"write", "system", "device", "destructive", "local_write", "external_write"}
_DANXI_TOOLS = get_shared_danxi_tools()
_DANXI_LOGIN_PURPOSE = "danxi.client.login.v1"
_DANXI_WEBVPN_PURPOSE = "danxi.client.webvpn_cookie.v1"
logger = logging.getLogger("meetyou.gateway.client")


def _ensure_client_always_available_tools(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return ensure_client_always_available_tools(metadata)


def _is_client_available_status(status: str) -> bool:
    return str(status or "").strip().lower() in {"online", "ready"}


def _danxi_raise_http_error(gateway, exc: Exception) -> None:
    message = str(exc) or "Danxi 请求失败"
    lowered = message.lower()
    status_code = 400
    code = "danxi_request_failed"
    if "找不到 danxi 会话" in message.lower() or "还没有活跃的 danxi 会话" in lowered:
        status_code = 404
        code = "danxi_session_not_found"
    elif "401" in lowered or "未授权" in message or "token" in lowered:
        status_code = 401
        code = "danxi_unauthorized"
    elif "403" in lowered or "无权限" in message or "forbidden" in lowered:
        status_code = 403
        code = "danxi_forbidden"
    elif "409" in lowered or "冲突" in message:
        status_code = 409
        code = "danxi_conflict"
    elif isinstance(exc, CredentialTransportError):
        if exc.code == "credential_key_unavailable":
            status_code = 503
            code = "danxi_credential_key_unavailable"
        elif exc.code == "credential_encrypted_required":
            status_code = 400
            code = "danxi_encrypted_credentials_required"
        else:
            status_code = 400
            code = "danxi_credential_decrypt_failed"
    gateway._raise_http_error(status_code=status_code, code=code, message=message)


def _danxi_session_response(payload: dict[str, Any]) -> ClientDanxiSessionResponse:
    return ClientDanxiSessionResponse(**payload)


def _danxi_profile_response(payload: dict[str, Any]) -> ClientDanxiProfileResponse:
    return ClientDanxiProfileResponse(**payload)


def _danxi_action_response(payload: dict[str, Any], message: str) -> ClientDanxiActionResponse:
    normalized = dict(payload)
    normalized["message"] = message
    return ClientDanxiActionResponse(**normalized)


def _resolve_danxi_login_payload(payload: ClientDanxiSessionLoginRequest) -> dict[str, Any]:
    if payload.encrypted_credentials:
        decrypted = decrypt_json_payload(payload.encrypted_credentials, purpose=_DANXI_LOGIN_PURPOSE)
        return {
            "email": str(decrypted.get("email") or ""),
            "password": str(decrypted.get("password") or ""),
            "session_key": str(decrypted.get("session_key") or payload.session_key or "default"),
            "use_webvpn": decrypted.get("use_webvpn"),
            "webvpn_cookie": str(decrypted.get("webvpn_cookie") or ""),
        }
    if payload.email or payload.password or payload.webvpn_cookie:
        raise CredentialTransportError(
            "credential_encrypted_required",
            "Danxi 登录请求必须提供 encrypted_credentials，已禁用明文跨边界凭证传输。",
        )
    return {
        "email": "",
        "password": "",
        "session_key": str(payload.session_key or "default"),
        "use_webvpn": payload.use_webvpn,
        "webvpn_cookie": "",
    }


def _resolve_danxi_webvpn_cookie_payload(payload: ClientDanxiWebvpnCookiePatchRequest) -> dict[str, Any]:
    if payload.encrypted_credentials:
        decrypted = decrypt_json_payload(payload.encrypted_credentials, purpose=_DANXI_WEBVPN_PURPOSE)
        return {
            "session_key": str(decrypted.get("session_key") or payload.session_key or "default"),
            "cookie_header": str(decrypted.get("cookie_header") or ""),
            "enable_webvpn": bool(decrypted.get("enable_webvpn", True)),
        }
    if payload.cookie_header:
        raise CredentialTransportError(
            "credential_encrypted_required",
            "Danxi WebVPN 登录态更新必须提供 encrypted_credentials，已禁用明文跨边界凭证传输。",
        )
    return {
        "session_key": str(payload.session_key or "default"),
        "cookie_header": "",
        "enable_webvpn": bool(payload.enable_webvpn),
    }


def _thread_response(thread, workspace_id: str) -> ClientThreadResponse:
    return ClientThreadResponse(
        thread_id=thread.thread_id,
        home_workspace_id=workspace_id,
        workspace_id=workspace_id,
        title=thread.title,
        status=thread.status,
        summary=thread.summary,
        pinned_procedure_id=thread.pinned_procedure_id,
    )


def _procedure_response(procedure) -> ClientProcedureResponse:
    routing = domain_procedure_routing_view(procedure)
    return ClientProcedureResponse(
        procedure_id=procedure.procedure_id,
        title=procedure.title,
        description=procedure.description,
        applicable_modes=list(getattr(procedure, "applicable_modes", []) or []),
        recommended_tools=routing["recommended_tools"],
        preferred_tool_key=routing["preferred_tool_key"],
        preferred_target_client_ids=routing["preferred_target_client_ids"],
        preferred_target_client_types=routing["preferred_target_client_types"],
        tool_target_routing_policy=routing["tool_target_routing_policy"],
        default_execution_target=procedure.default_execution_target,
        risk_profile=procedure.risk_profile,
        status=procedure.status,
    )


def _procedure_detail_response(procedure) -> ClientProcedureDetailResponse:
    detail = domain_procedure_detail_view(procedure)
    return ClientProcedureDetailResponse(**detail)


def domain_procedure_routing_view(procedure) -> dict[str, Any]:
    from core.services.procedure_service import ProcedureService

    return ProcedureService.get_routing_view(procedure)


def domain_procedure_detail_view(procedure) -> dict[str, Any]:
    from core.services.procedure_service import ProcedureService

    return ProcedureService.get_detail_view(procedure)


def _procedure_snapshot(procedure) -> dict:
    return domain_procedure_detail_view(procedure)


def _thread_procedure_context_response(domain, thread) -> ClientThreadProcedureContextResponse:
    context = domain.services.procedure.get_thread_context(thread)
    pinned = context.get("pinned_procedure")
    latest_inferred = context.get("latest_inferred_procedure")
    effective = context.get("effective_procedure")
    return ClientThreadProcedureContextResponse(
        source=str(context.get("source") or "none"),
        pinned_procedure=ClientProcedureDetailResponse(**pinned) if isinstance(pinned, dict) else None,
        latest_inferred_procedure=ClientProcedureDetailResponse(**latest_inferred) if isinstance(latest_inferred, dict) else None,
        effective_procedure=ClientProcedureDetailResponse(**effective) if isinstance(effective, dict) else None,
        latest_inferred_reason=str(context.get("latest_inferred_reason") or ""),
        latest_inferred_score=max(int(context.get("latest_inferred_score", 0) or 0), 0),
        latest_inferred_at=str(context.get("latest_inferred_at") or ""),
    )


def _operation_response(operation, *, workspace_id: str, thread_id: str) -> ClientOperationResponse:
    metadata = dict(getattr(operation, "meta", {}) or {})
    return ClientOperationResponse(
        operation_id=operation.operation_id,
        thread_id=thread_id,
        workspace_id=workspace_id,
        title=operation.title,
        operation_type=operation.operation_type,
        execution_target=normalize_execution_target(operation.execution_target),
        target_client_id=str(metadata.get("target_client_id") or ""),
        tool_key=str(metadata.get("tool_key") or ""),
        tool_id=str(metadata.get("tool_id") or ""),
        status=operation.status,
        approval_id=str(metadata.get("approval_id") or ""),
        approval_status=str(metadata.get("approval_status") or ""),
        approval_required=bool(metadata.get("approval_required", False)),
        routing_reason=str(metadata.get("routing_reason") or ""),
    )


def _message_response(message, *, thread_id: str, active_workspace_id: str, session_id: str = "", client_id: str = "") -> ClientMessageResponse:
    return ClientMessageResponse(
        message_id=message.message_id,
        thread_id=thread_id,
        session_id=session_id,
        active_workspace_id=active_workspace_id,
        workspace_id=active_workspace_id,
        client_id=client_id,
        role=message.role,
        content=message.content,
        status=message.status,
        channel=message.channel,
        created_at=message.created_at.isoformat() if getattr(message, "created_at", None) is not None else "",
    )


def _attachment_response(attachment) -> ClientAttachmentResponse:
    metadata = dict(getattr(attachment, "meta", {}) or {})
    return ClientAttachmentResponse(
        attachment_id=attachment.attachment_id,
        owner_type=attachment.owner_type,
        owner_id=attachment.owner_id,
        kind=attachment.kind,
        mime_type=attachment.mime_type,
        file_name=str(metadata.get("file_name") or attachment.attachment_id),
        object_key=attachment.object_key,
        size_bytes=attachment.size_bytes,
        lifecycle_policy=str(getattr(attachment, "lifecycle_policy", "") or "normal"),
        expires_at=str(getattr(attachment, "expires_at", "") or ""),
        sha256=attachment.sha256,
        status=attachment.status,
        created_at=attachment.created_at.isoformat() if getattr(attachment, "created_at", None) is not None else "",
        updated_at=attachment.updated_at.isoformat() if getattr(attachment, "updated_at", None) is not None else "",
        uploaded_at=str(metadata.get("uploaded_at") or ""),
        completed_at=str(metadata.get("completed_at") or ""),
        deleted_at=str(metadata.get("deleted_at") or ""),
    )


def _attachment_response_from_view(view: dict[str, Any] | Any) -> ClientAttachmentResponse:
    if not isinstance(view, dict):
        return _attachment_response(view)
    return ClientAttachmentResponse(
        attachment_id=str(view.get("attachment_id") or ""),
        owner_type=str(view.get("owner_type") or ""),
        owner_id=str(view.get("owner_id") or ""),
        kind=str(view.get("kind") or "file"),
        mime_type=str(view.get("mime_type") or "application/octet-stream"),
        file_name=str(view.get("file_name") or ""),
        object_key=str(view.get("object_key") or ""),
        size_bytes=int(view.get("size_bytes") or 0),
        lifecycle_policy=str(view.get("lifecycle_policy") or "normal"),
        expires_at=str(view.get("expires_at") or ""),
        sha256=str(view.get("sha256") or ""),
        status=str(view.get("status") or ""),
        created_at=str(view.get("created_at") or ""),
        updated_at=str(view.get("updated_at") or ""),
        uploaded_at=str(view.get("uploaded_at") or ""),
        completed_at=str(view.get("completed_at") or ""),
        deleted_at=str(view.get("deleted_at") or ""),
    )


def _get_workspace_by_row_id(domain, row_id):
    if row_id is None:
        return None
    return domain.services.workspace.get_by_id(row_id)


def _require_workspace(gateway, domain, *, workspace_id: str):
    workspace = domain.services.workspace.get_by_workspace_id(workspace_id)
    if workspace is None:
        gateway._raise_http_error(
            status_code=404,
            code="workspace_not_found",
            message=f"未知 workspace: {workspace_id}",
        )
    return workspace


def _resolve_thread_home_workspace(gateway, domain, *, thread):
    workspace = _get_workspace_by_row_id(domain, getattr(thread, "home_workspace_id", None) or getattr(thread, "workspace_id", None))
    if workspace is None:
        gateway._raise_http_error(
            status_code=404,
            code="workspace_not_found",
            message=f"thread {thread.thread_id} 缺少 home workspace",
        )
    return workspace


def _resolve_active_workspace(gateway, domain, *, requested_workspace_id: str = "", session_record=None, thread=None):
    workspace_id = str(requested_workspace_id or "").strip()
    if workspace_id:
        return _require_workspace(gateway, domain, workspace_id=workspace_id)
    if session_record is not None:
        workspace = _get_workspace_by_row_id(domain, getattr(session_record, "active_workspace_id", None) or getattr(session_record, "workspace_id", None))
        if workspace is not None:
            return workspace
    if thread is not None:
        return _resolve_thread_home_workspace(gateway, domain, thread=thread)
    gateway._raise_http_error(status_code=400, code="workspace_required", message="active_workspace_id 为必填字段")


def _bind_client_workspace(domain, *, client, workspace, role: str = "member", metadata: dict | None = None) -> None:
    try:
        domain.services.client.bind_workspace(
            workspace_id=workspace.id,
            client_id=client.id,
            membership_role=role,
            enabled=True,
            metadata=metadata,
        )
    except Exception:
        logger.exception("Failed to bind client workspace membership")


def _record_context_pool_message(domain, *, message, thread, session_record=None, client=None, active_workspace=None, home_workspace=None, metadata: dict | None = None) -> None:
    context_pool = getattr(domain.services, "context_pool", None)
    if context_pool is None:
        return
    try:
        context_pool.record_message(
            principal_id=domain.principal.id,
            message=message,
            thread=thread,
            session=session_record,
            client=client,
            active_workspace=active_workspace,
            home_workspace=home_workspace,
            metadata=metadata,
        )
    except Exception:
        logger.exception("Failed to write context pool item")


def _workspace_governance_view(workspace) -> dict[str, Any]:
    from core.services.workspace_service import WorkspaceService

    return WorkspaceService.get_governance_view(workspace)


def _workspace_response(workspace) -> ClientWorkspaceResponse:
    governance = _workspace_governance_view(workspace)
    return ClientWorkspaceResponse(
        workspace_id=workspace.workspace_id,
        title=workspace.title,
        status=workspace.status,
        base_mode=workspace.base_mode,
        description=governance["description"],
        prompt_overlay=governance["prompt_overlay"],
        default_execution_target=governance["default_execution_target"],
        tool_policy=governance["tool_policy"],
        allowed_tool_ids=governance["allowed_tool_ids"],
        preferred_target_client_ids=governance["preferred_target_client_ids"],
        preferred_target_client_types=governance["preferred_target_client_types"],
        preferred_source_profiles=governance["preferred_source_profiles"],
        tool_target_routing_policy=governance["tool_target_routing_policy"],
        memory_ranking_policy=governance["memory_ranking_policy"],
        tool_routing_overrides=governance["tool_routing_overrides"],
    )


def _resolve_procedure_execution_profile(domain, *, payload) -> tuple[object | None, dict[str, Any]]:
    arguments = dict(payload.arguments or {}) if isinstance(payload.arguments, dict) else {}
    procedure_id = str(arguments.get("procedure_id") or "").strip()
    if not procedure_id and str(payload.operation_type or "") == "procedure_call":
        candidate = str(payload.tool_id or "").strip()
        if candidate:
            procedure = domain.services.procedure.get_by_procedure_id(candidate)
            if procedure is not None:
                procedure_id = candidate
    if not procedure_id:
        return None, {}
    procedure = domain.services.procedure.get_by_procedure_id(procedure_id)
    if procedure is None or getattr(procedure, "status", "") != "active":
        return None, {}
    routing = domain.services.procedure.get_routing_view(procedure)
    return procedure, {
        "procedure_id": procedure.procedure_id,
        "procedure_snapshot": _procedure_snapshot(procedure),
        "preferred_tool_key": routing["preferred_tool_key"],
        "preferred_target_client_ids": routing["preferred_target_client_ids"],
        "preferred_target_client_types": routing["preferred_target_client_types"],
        "tool_target_routing_policy": routing["tool_target_routing_policy"],
    }


def _resolve_workspace_target_client(domain, *, workspace, tool, tool_key: str = "", execution_target: str, requesting_client, explicit_target_client=None, routing_preferences: dict[str, Any] | None = None) -> tuple[object | None, str]:
    if explicit_target_client is not None:
        return explicit_target_client, "Explicit client target provided by client."

    normalized_execution_target = normalize_execution_target(execution_target)
    governance = domain.services.workspace.get_governance_view(workspace)
    abstract_key = domain.services.tool.get_abstract_tool_key(tool) if tool is not None else ""
    concrete_tool_id = str(getattr(tool, "tool_id", "") or "") if tool is not None else ""
    effective_preferences = domain.services.workspace.get_effective_tool_target_preferences(
        workspace,
        tool_key=tool_key,
        abstract_tool_key=abstract_key,
        concrete_tool_id=concrete_tool_id,
    )
    merged_preferences = _merge_routing_preferences(effective_preferences, routing_preferences or {})
    preferred_target_client_ids = list(merged_preferences.get("preferred_target_client_ids") or [])
    preferred_target_client_types = list(merged_preferences.get("preferred_target_client_types") or [])
    tool_target_routing_policy = str(merged_preferences.get("tool_target_routing_policy") or governance.get("tool_target_routing_policy") or "balanced")
    preference_source = str(merged_preferences.get("source") or "workspace_default")
    requesting_client_id = getattr(requesting_client, "id", None)

    if tool is not None and str(getattr(tool, "provider_type", "") or "") == "client":
        is_exact_tool_id = str(getattr(tool, "tool_id", "") or "") == str(tool_key or "").strip()
        provider_client = domain.services.client.get_by_client_id(str(getattr(tool, "provider_ref", "") or ""))
        if is_exact_tool_id and provider_client is not None and domain.services.client.is_bound_to_workspace(client_id=provider_client.client_id, workspace_id=workspace.workspace_id):
            if getattr(provider_client, "status", "") == "online":
                return provider_client, "Resolved from tool provider within workspace scope."
            if normalized_execution_target == EXECUTION_TARGET_SPECIFIC_CLIENT:
                return None, f"Capability provider client is offline: {provider_client.client_id}"
            if normalized_execution_target == EXECUTION_TARGET_WORKSPACE_ANY_CLIENT:
                return None, f"Capability provider client is offline: {provider_client.client_id}"
            if normalized_execution_target == EXECUTION_TARGET_PREFER_CLIENT_FALLBACK_CORE:
                return None, f"Capability provider client is offline and no core fallback is available: {provider_client.client_id}"

    if normalized_execution_target not in {
        EXECUTION_TARGET_SPECIFIC_CLIENT,
        EXECUTION_TARGET_WORKSPACE_ANY_CLIENT,
        EXECUTION_TARGET_PREFER_CLIENT_FALLBACK_CORE,
    }:
        return None, ""

    allowed_client_ids = []
    if tool is not None:
        allowed_client_ids = domain.services.tool.list_clients_for_tool_reference(
            tool_key=abstract_key or tool_key,
            workspace_id=workspace.id,
        )

    selected = domain.services.client.select_workspace_client(
        workspace_id=workspace.id,
        requesting_client_id=requesting_client_id,
        preferred_target_client_ids=preferred_target_client_ids,
        preferred_target_client_types=preferred_target_client_types,
        routing_policy=tool_target_routing_policy,
        allowed_client_ids=allowed_client_ids,
    )
    if selected is not None:
        return selected, f"Resolved by workspace client routing policy ({tool_target_routing_policy}) via {preference_source}."
    if normalized_execution_target == EXECUTION_TARGET_PREFER_CLIENT_FALLBACK_CORE:
        return None, "No workspace client available; fallback to core_only."
    return None, f"No online client is available for workspace: {workspace.workspace_id}"


def _merge_routing_preferences(*preferences: dict[str, Any]) -> dict[str, Any]:
    merged = {
        "preferred_target_client_ids": [],
        "preferred_target_client_types": [],
        "tool_target_routing_policy": "balanced",
        "source": "workspace_default",
    }
    for item in preferences:
        if not isinstance(item, dict):
            continue
        if item.get("preferred_target_client_ids"):
            merged["preferred_target_client_ids"] = list(item.get("preferred_target_client_ids") or [])
        if item.get("preferred_target_client_types"):
            merged["preferred_target_client_types"] = list(item.get("preferred_target_client_types") or [])
        if item.get("tool_target_routing_policy"):
            merged["tool_target_routing_policy"] = str(item.get("tool_target_routing_policy") or "balanced")
        if item.get("source"):
            merged["source"] = str(item.get("source") or merged["source"])
    return merged


def _resolve_requesting_client(domain, *, client_id: str, session_id: str | None):
    resolved_client_id = str(client_id or "").strip()
    if session_id:
        session_row = domain.services.session.get_by_session_id(session_id)
        if session_row is not None:
            session_client = domain.services.client.get_by_id(session_row.client_id)
            if session_client is not None and not resolved_client_id:
                resolved_client_id = session_client.client_id
    if not resolved_client_id:
        resolved_client_id = "desktop-app"
    client_type = "electron"
    display_name = resolved_client_id.replace("-", " ").replace("_", " ").title()
    if resolved_client_id == "desktop-app":
        display_name = "Desktop App"
    return domain.services.client.ensure_client(
        client_id=resolved_client_id,
        principal_id=domain.principal.id,
        client_type=client_type,
        display_name=display_name,
    )


def _resolve_client_session_for_thread(domain, *, session_id: str, thread_id: str):
    session_row = domain.services.session.get_by_session_id(session_id)
    if session_row is None:
        return None, None, None, None, "session_not_found", f"未知 session: {session_id}"
    thread_row = domain.services.thread.get_by_id(session_row.thread_id)
    if thread_row is None or thread_row.thread_id != thread_id:
        return None, None, None, None, "session_thread_mismatch", f"session {session_id} 不属于 thread: {thread_id}"
    workspace_row = _get_workspace_by_row_id(domain, getattr(session_row, "active_workspace_id", None) or getattr(session_row, "workspace_id", None))
    client_row = domain.services.client.get_by_id(session_row.client_id)
    return session_row, thread_row, workspace_row, client_row, "", ""


def _bind_runtime_session(gateway, *, session_id: str, source, metadata: dict | None = None) -> str:
    return gateway._session_manager.bind_runtime_session(
        source,
        session_id=session_id,
        metadata=dict(metadata or {}),
    )


def _tool_requires_approval(tool) -> bool:
    if tool is None:
        return False
    if bool(getattr(tool, "requires_confirmation", False)):
        return True
    return str(getattr(tool, "risk_level", "") or "").strip().lower() in _APPROVAL_RISK_LEVELS


def _operation_event_payload(operation, *, thread_id: str, detail: str = "", phase: str = "", call_id: str = "", result: dict | None = None, error: dict | None = None) -> dict:
    metadata = dict(getattr(operation, "meta", {}) or {})
    payload = {
        "thread_id": thread_id,
        "operation_id": operation.operation_id,
        "title": operation.title,
        "operation_type": operation.operation_type,
        "execution_target": normalize_execution_target(operation.execution_target),
        "target_client_id": str(metadata.get("target_client_id") or ""),
        "tool_id": str(metadata.get("tool_id") or ""),
        "status": operation.status,
        "approval_id": str(metadata.get("approval_id") or ""),
        "approval_status": str(metadata.get("approval_status") or ""),
        "approval_required": bool(metadata.get("approval_required", False)),
        "routing_reason": str(metadata.get("routing_reason") or ""),
    }
    if call_id:
        payload["call_id"] = call_id
    if phase:
        payload["phase"] = phase
    if detail:
        payload["detail"] = detail
    if result is not None:
        payload["result"] = dict(result)
    if error is not None:
        payload["error"] = dict(error)
    return payload


async def _publish_operation_update(gateway, *, operation, thread_id: str, detail: str = "", phase: str = "", call_id: str = "", result: dict | None = None, error: dict | None = None) -> None:
    await gateway.publish_client_thread_event(
        thread_id,
        event_type="operation.updated",
        payload=_operation_event_payload(
            operation,
            thread_id=thread_id,
            detail=detail,
            phase=phase,
            call_id=call_id,
            result=result,
            error=error,
        ),
    )


async def _await_approval_resolution(domain, *, approval_id: str, timeout_seconds: float = 1.0):
    deadline = asyncio.get_running_loop().time() + max(0.1, timeout_seconds)
    approval = domain.services.approval.get_by_approval_id(approval_id)
    while approval is not None and approval.status == "pending" and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
        approval = domain.services.approval.get_by_approval_id(approval_id)
    return approval


async def _resolve_chat_confirmation_from_approval(gateway, domain, *, approval, payload: ClientApprovalDecisionRequest):
    operation = domain.services.operation.get_by_id(approval.operation_id)
    if operation is None:
        gateway._raise_http_error(
            status_code=404,
            code="operation_not_found",
            message=f"approval {approval.approval_id} 对应的 operation 不存在",
        )

    metadata = dict(getattr(operation, "meta", {}) or {})
    request_id = str(metadata.get("confirm_request_id") or "").strip()
    session_id = str(metadata.get("confirm_session_id") or "").strip()
    if not request_id or not session_id:
        gateway._raise_http_error(
            status_code=409,
            code="confirm_context_missing",
            message="聊天确认缺少 request/session 上下文，无法继续决策",
        )

    resolved = gateway._interaction_responses.submit_confirmation_response(
        payload.decision == "approve",
        request_id=request_id,
        session_id=session_id,
        client_id=str(payload.client_id or "").strip(),
        approval_id=approval.approval_id,
        reason=payload.reason,
    )
    if not resolved:
        gateway._raise_http_error(
            status_code=409,
            code="stale_confirm_response",
            message="聊天确认请求已失效、已处理，或与当前会话不匹配。",
        )

    updated_approval = await _await_approval_resolution(domain, approval_id=approval.approval_id)
    if updated_approval is None:
        gateway._raise_http_error(
            status_code=404,
            code="approval_not_found",
            message=f"未知 approval: {approval.approval_id}",
        )
    if updated_approval.status == "pending":
        gateway._raise_http_error(
            status_code=409,
            code="confirm_resolution_timeout",
            message="聊天确认决策尚未完成，请稍后重试。",
        )
    updated_operation = domain.services.operation.get_by_id(updated_approval.operation_id)
    return updated_approval, updated_operation


async def _await_approval_resolution(domain, *, approval_id: str, timeout_seconds: float = 1.0):
    deadline = asyncio.get_running_loop().time() + max(0.1, timeout_seconds)
    approval = domain.services.approval.get_by_approval_id(approval_id)
    while approval is not None and approval.status == "pending" and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
        approval = domain.services.approval.get_by_approval_id(approval_id)
    return approval


async def _resolve_chat_confirmation_from_approval(gateway, domain, *, approval, payload: ClientApprovalDecisionRequest):
    operation = domain.services.operation.get_by_id(approval.operation_id)
    if operation is None:
        gateway._raise_http_error(
            status_code=404,
            code="operation_not_found",
            message=f"approval {approval.approval_id} 对应的 operation 不存在",
        )
    metadata = dict(getattr(operation, "meta", {}) or {})
    request_id = str(metadata.get("confirm_request_id") or "").strip()
    session_id = str(metadata.get("confirm_session_id") or "").strip()
    if not request_id or not session_id:
        gateway._raise_http_error(
            status_code=409,
            code="confirm_context_missing",
            message="聊天确认缺少 request/session 上下文，无法继续决策",
        )
    resolved = gateway._interaction_responses.submit_confirmation_response(
        payload.decision == "approve",
        request_id=request_id,
        session_id=session_id,
        client_id=str(payload.client_id or "").strip(),
        approval_id=approval.approval_id,
        reason=payload.reason,
    )
    if not resolved:
        gateway._raise_http_error(
            status_code=409,
            code="stale_confirm_response",
            message="聊天确认请求已失效、已处理，或与当前会话不匹配。",
        )
    updated_approval = await _await_approval_resolution(domain, approval_id=approval.approval_id)
    if updated_approval is None:
        gateway._raise_http_error(
            status_code=404,
            code="approval_not_found",
            message=f"未知 approval: {approval.approval_id}",
        )
    if updated_approval.status == "pending":
        gateway._raise_http_error(
            status_code=409,
            code="confirm_resolution_timeout",
            message="聊天确认决策尚未完成，请稍后重试。",
        )
    updated_operation = domain.services.operation.get_by_id(updated_approval.operation_id)
    return updated_approval, updated_operation


async def _dispatch_specific_client_operation(gateway, domain, *, operation, thread, workspace, requesting_client) -> tuple[object, str]:
    metadata = dict(getattr(operation, "meta", {}) or {})
    target_client_id = str(metadata.get("target_client_id") or "")
    tool_id = str(metadata.get("tool_id") or "")
    tool_key = str(metadata.get("tool_key") or tool_id)
    if not target_client_id or not tool_id:
        return operation, ""

    target_client = domain.services.client.get_by_client_id(target_client_id)
    if target_client is None:
        error = {"code": "client_not_found", "message": f"未知 client: {target_client_id}"}
        operation = domain.services.operation.update_status(
            operation_id=operation.id,
            status="failed",
            result_summary=error["message"],
            metadata={"error": error},
        ) or operation
        await _publish_operation_update(gateway, operation=operation, thread_id=thread.thread_id, detail=error["message"], error=error)
        return operation, ""

    tool = domain.services.tool.get_by_tool_id(tool_id)
    if tool is None:
        error = {"code": "tool_not_found", "message": f"未知 tool: {tool_key}"}
        operation = domain.services.operation.update_status(
            operation_id=operation.id,
            status="failed",
            result_summary=error["message"],
            metadata={"error": error},
        ) or operation
        await _publish_operation_update(gateway, operation=operation, thread_id=thread.thread_id, detail=error["message"], error=error)
        return operation, ""

    public_arguments = metadata.get("arguments") if isinstance(metadata.get("arguments"), dict) else {}
    encrypted_arguments = metadata.get("encrypted_arguments") if isinstance(metadata.get("encrypted_arguments"), dict) else None

    call = domain.services.operation_call.create_call(
        operation_id=operation.id,
        tool_id=tool.id,
        target_client_id=target_client.id,
        status="queued",
        arguments=public_arguments,
    )
    dispatched = await gateway.dispatch_client_call(
        client_id=target_client.client_id,
        payload=build_tool_call_request(
            client_id=target_client.client_id,
            message_id=f"dispatch-{call.call_id}",
            operation_id=operation.operation_id,
            call_id=call.call_id,
            workspace_id=workspace.workspace_id,
            tool_id=tool_id,
            tool_key=tool_key,
            arguments=dict(public_arguments or {}),
            encrypted_arguments=encrypted_arguments,
            timeout_seconds=60,
            audit_context={
                "principal_id": "self",
                "requested_by_client_id": getattr(requesting_client, "client_id", ""),
                "operation_type": operation.operation_type,
            },
        ),
    )
    if not dispatched:
        error = {"code": "client_offline", "message": f"Client is offline: {target_client.client_id}"}
        domain.services.operation_call.mark_failed(call_id=call.call_id, error=error)
        operation = domain.services.operation.get_by_id(operation.id) or operation
        await _publish_operation_update(gateway, operation=operation, thread_id=thread.thread_id, call_id=call.call_id, detail=error["message"], error=error)
        return operation, call.call_id

    domain.services.operation_call.mark_dispatched(call_id=call.call_id)
    operation = domain.services.operation.update_status(
        operation_id=operation.id,
        status="dispatching",
        metadata={"last_call_id": call.call_id},
    ) or operation
    await _publish_operation_update(
        gateway,
        operation=operation,
        thread_id=thread.thread_id,
        call_id=call.call_id,
        phase="dispatching",
        detail="已通过 Client 下发执行请求",
    )
    return operation, call.call_id


async def _handle_client_tool_frame(gateway, websocket: WebSocket, frame: dict[str, Any], *, thread_id: str) -> bool:
    if str(frame.get("schema") or "") != "meetyou.client.ws.v1":
        return False
    message_type = str(frame.get("type") or "").strip()
    if not message_type:
        return False
    domain = gateway._require_core_domain()
    payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
    client_id = str(frame.get("client_id") or payload.get("client_id") or "").strip()
    if message_type == "client.hello":
        if not client_id:
            await gateway._safe_send_json(
                websocket,
                {
                    "schema": "meetyou.client.ws.v1",
                    "type": "client.hello.ack",
                    "client_id": "",
                    "payload": {"accepted": False, "reject_reason": {"code": "client_id_required", "message": "client_id is required"}},
                },
            )
            return True
        workspace_ids = [str(item).strip() for item in payload.get("workspace_ids", []) if str(item).strip()]
        available_tools = [str(item).strip() for item in payload.get("available_tools", []) if str(item).strip()]
        executable_tools = [str(item).strip() for item in payload.get("executable_tools", []) if str(item).strip()]
        client = domain.services.client.register_client(
            client_id=client_id,
            principal_id=domain.principal.id,
            client_type=str(payload.get("client_type") or "client"),
            display_name=str(payload.get("display_name") or client_id),
            status="online",
            available_tools=available_tools,
            executable_tools=executable_tools,
            transport_profile=str(payload.get("transport_profile") or ""),
            host=payload.get("host") if isinstance(payload.get("host"), dict) else {},
            metadata={"last_hello": payload},
        )
        domain.services.client.replace_workspace_bindings(client_id=client_id, workspace_ids=workspace_ids)
        await gateway.client_ws_manager.bind_connection(
            websocket,
            thread_id=thread_id,
            client_id=client_id,
            workspace_id=workspace_ids[0] if workspace_ids else "",
            client_type=getattr(client, "client_type", ""),
            display_name=getattr(client, "display_name", ""),
            transport_profile=str(payload.get("transport_profile") or ""),
            available_tools=available_tools,
            executable_tools=executable_tools,
            host=payload.get("host") if isinstance(payload.get("host"), dict) else {},
        )
        connection_prompt = await gateway.build_client_connection_prompt(
            client_id=client_id,
            client_type=getattr(client, "client_type", ""),
            display_name=getattr(client, "display_name", ""),
            transport_profile=str(payload.get("transport_profile") or ""),
            workspace_ids=workspace_ids,
        )
        await gateway._safe_send_json(
            websocket,
            {
                "schema": "meetyou.client.ws.v1",
                "type": "client.hello.ack",
                "client_id": client_id,
                "payload": {
                    "accepted": True,
                    "requires_tools_snapshot": True,
                    "heartbeat_interval_seconds": 20,
                    "connection_prompt": dict(connection_prompt or {}),
                },
            },
        )
        await gateway.notify_client_connected(
            client_id=client_id,
            client_type=getattr(client, "client_type", ""),
            display_name=getattr(client, "display_name", ""),
            transport_profile=str(payload.get("transport_profile") or ""),
            workspace_ids=workspace_ids,
            connection_prompt=connection_prompt,
        )
        return True
    if not client_id:
        return False
    if message_type == "client.tools.snapshot":
        client = domain.services.client.get_by_client_id(client_id)
        if client is None:
            return True
        tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []
        workspace_keys = {
            str(workspace_id).strip()
            for item in tools
            if isinstance(item, dict)
            for workspace_id in item.get("workspace_ids", [])
            if str(workspace_id).strip()
        }
        workspace_rows = [domain.services.workspace.get_by_workspace_id(workspace_id) for workspace_id in sorted(workspace_keys)]
        workspace_rows = [workspace for workspace in workspace_rows if workspace is not None]
        count = domain.services.capability.replace_client_tools(
            client=client,
            tools=[dict(item) for item in tools if isinstance(item, dict)],
            workspace_rows=workspace_rows,
            revision=int(payload.get("revision") or 1),
        )
        await gateway._safe_send_json(
            websocket,
            {
                "schema": "meetyou.client.ws.v1",
                "type": "client.ready",
                "client_id": client_id,
                "payload": {"registered_tool_count": count},
            },
        )
        return True
    if message_type == "client.heartbeat":
        domain.services.client.record_heartbeat(client_id=client_id, status=str(payload.get("status") or "online"), metadata={"heartbeat": payload})
        return True
    if message_type == "tool.call.accepted":
        call_id = str(payload.get("call_id") or "")
        if call_id:
            domain.services.operation_call.mark_accepted(call_id=call_id)
        return True
    if message_type == "tool.call.progress":
        call_id = str(payload.get("call_id") or "")
        if call_id:
            domain.services.operation_call.mark_progress(call_id=call_id, detail=str(payload.get("detail") or ""), metadata=payload)
        return True
    if message_type == "tool.call.result":
        call_id = str(payload.get("call_id") or "")
        if call_id:
            await domain.client_tool_dispatch.notify_call_result(call_id, payload.get("result") if isinstance(payload.get("result"), dict) else {})
        return True
    if message_type == "tool.call.error":
        call_id = str(payload.get("call_id") or "")
        if call_id:
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {"code": "client_tool_failed", "message": "Client tool call failed"}
            await domain.client_tool_dispatch.notify_call_error(call_id, error)
        return True
    return False


def build_client_router(gateway) -> APIRouter:
    router = APIRouter(prefix="/client", tags=["client"])

    @router.get("/workspaces", response_model=list[ClientWorkspaceResponse])
    async def list_workspaces(request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        return [_workspace_response(workspace) for workspace in domain.services.workspace.list_workspaces()]

    @router.get("/workspaces/{workspace_id}/clients", response_model=list[ClientAvailableClientResponse])
    async def list_workspace_clients(workspace_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        workspace = domain.services.workspace.get_by_workspace_id(workspace_id)
        if workspace is None:
            gateway._raise_http_error(status_code=404, code="workspace_not_found", message=f"未知 workspace: {workspace_id}")
        live_connections = await gateway.client_ws_manager.snapshot(workspace_id=workspace_id)
        live_client_ids = {
            str(connection.get("client_id") or "").strip()
            for connection in live_connections
            if str(connection.get("client_id") or "").strip()
        }
        rows = []
        for client, binding in domain.services.client.list_clients_for_workspace(workspace.id):
            if not bool(getattr(binding, "enabled", True)):
                continue
            rows.append(
                ClientAvailableClientResponse(
                    client_id=client.client_id,
                    display_name=client.display_name,
                    client_type=client.client_type,
                    status="online" if client.client_id in live_client_ids else client.status,
                    workspace_ids=[workspace_id],
                    transport_profile=str(getattr(client, "transport_profile", "") or ""),
                    available_tools=list(getattr(client, "available_tools", []) or []),
                    executable_tools=list(getattr(client, "executable_tools", []) or []),
                    membership_role=str(getattr(binding, "membership_role", "member") or "member"),
                    enabled=bool(getattr(binding, "enabled", True)),
                )
            )
        return rows

    @router.get("/context-pool/query", response_model=ContextPoolQueryResponse)
    async def query_context_pool(
        request: Request,
        q: str = "",
        thread_id: str = "",
        session_id: str = "",
        active_workspace_id: str = "",
        workspace_id: str = "",
        limit: int = 8,
    ):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread_row = domain.services.thread.get_by_thread_id(thread_id) if thread_id else None
        session_row = domain.services.session.get_by_session_id(session_id) if session_id else None
        workspace_row = None
        resolved_workspace_id = str(active_workspace_id or workspace_id or "").strip()
        if resolved_workspace_id:
            workspace_row = _require_workspace(gateway, domain, workspace_id=resolved_workspace_id)
        elif session_row is not None:
            workspace_row = _get_workspace_by_row_id(domain, session_row.active_workspace_id)
        items = domain.services.context_pool.query(
            principal_id=domain.principal.id,
            query_text=q,
            thread_id=getattr(thread_row, "id", None),
            session_id=getattr(session_row, "id", None),
            active_workspace_id=getattr(workspace_row, "id", None),
            limit=limit,
        )
        return ContextPoolQueryResponse(query=q, count=len(items), items=items)

    @router.post("/danxi/session/login", response_model=ClientDanxiSessionResponse)
    async def danxi_login(payload: ClientDanxiSessionLoginRequest, request: Request):
        gateway._require_http_auth(request)
        try:
            resolved = _resolve_danxi_login_payload(payload)
            result = _DANXI_TOOLS.danxi_login(
                email=resolved["email"],
                password=resolved["password"],
                session_key=resolved["session_key"],
                use_webvpn=resolved["use_webvpn"],
                webvpn_cookie=resolved["webvpn_cookie"],
            )
            return _danxi_session_response(
                {
                    **result,
                    "direct_connect_available": _DANXI_TOOLS._can_connect_directly(),
                    "webvpn_required": bool(result.get("webvpn_enabled") and not _DANXI_TOOLS._can_connect_directly()),
                }
            )
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.get("/danxi/session", response_model=ClientDanxiSessionResponse)
    async def danxi_session(request: Request, session_key: str = ""):
        gateway._require_http_auth(request)
        try:
            return _danxi_session_response(_DANXI_TOOLS.danxi_get_session_status(session_key=session_key))
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.get("/danxi/profile", response_model=ClientDanxiProfileResponse)
    async def danxi_profile(request: Request, session_key: str = "", refresh: bool = False):
        gateway._require_http_auth(request)
        try:
            return _danxi_profile_response(_DANXI_TOOLS.danxi_get_user_profile(session_key=session_key, refresh=refresh))
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.patch("/danxi/session/webvpn-cookie", response_model=ClientDanxiSessionResponse)
    async def danxi_webvpn_cookie(payload: ClientDanxiWebvpnCookiePatchRequest, request: Request):
        gateway._require_http_auth(request)
        try:
            resolved = _resolve_danxi_webvpn_cookie_payload(payload)
            return _danxi_session_response(
                _DANXI_TOOLS.danxi_set_webvpn_cookie(
                    resolved["cookie_header"],
                    session_key=resolved["session_key"],
                    enable_webvpn=resolved["enable_webvpn"],
                )
            )
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.get("/danxi/divisions", response_model=ClientDanxiListResponse)
    async def danxi_divisions(request: Request, session_key: str = ""):
        gateway._require_http_auth(request)
        try:
            return ClientDanxiListResponse(**_DANXI_TOOLS.danxi_list_divisions(session_key=session_key))
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.get("/danxi/posts", response_model=ClientDanxiListResponse)
    async def danxi_posts(
        request: Request,
        session_key: str = "",
        division_id: int | None = None,
        start_time: str = "",
        length: int = 20,
        offset: int = 0,
        tag: str = "",
        order: str = "last_replied",
    ):
        gateway._require_http_auth(request)
        try:
            return ClientDanxiListResponse(
                **_DANXI_TOOLS.danxi_list_posts(
                    session_key=session_key,
                    division_id=division_id,
                    start_time=start_time,
                    length=length,
                    offset=offset,
                    tag=tag,
                    order=order,
                )
            )
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.get("/danxi/posts/{hole_id}", response_model=ClientDanxiPostResponse)
    async def danxi_post(hole_id: int, request: Request, session_key: str = ""):
        gateway._require_http_auth(request)
        try:
            return ClientDanxiPostResponse(**_DANXI_TOOLS.danxi_get_post(hole_id, session_key=session_key))
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.get("/danxi/posts/{hole_id}/floors", response_model=ClientDanxiListResponse)
    async def danxi_post_floors(
        hole_id: int,
        request: Request,
        session_key: str = "",
        offset: int = 0,
        size: int = 20,
        include_all: bool = False,
    ):
        gateway._require_http_auth(request)
        try:
            return ClientDanxiListResponse(
                **_DANXI_TOOLS.danxi_list_floors(
                    hole_id,
                    session_key=session_key,
                    offset=offset,
                    size=size,
                    include_all=include_all,
                )
            )
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.post("/danxi/posts/{hole_id}/replies", response_model=ClientDanxiActionResponse)
    async def danxi_create_reply(hole_id: int, payload: ClientDanxiReplyCreateRequest, request: Request):
        gateway._require_http_auth(request)
        try:
            return _danxi_action_response(
                _DANXI_TOOLS.danxi_reply_post(hole_id, payload.content, session_key=payload.session_key),
                message="回复已发布，帖子详情已可刷新。",
            )
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.patch("/danxi/floors/{floor_id}", response_model=ClientDanxiActionResponse)
    async def danxi_update_reply(floor_id: int, payload: ClientDanxiReplyUpdateRequest, request: Request):
        gateway._require_http_auth(request)
        try:
            return _danxi_action_response(
                _DANXI_TOOLS.danxi_edit_reply(floor_id, payload.content, session_key=payload.session_key),
                message="回复已更新，帖子详情已可刷新。",
            )
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.delete("/danxi/floors/{floor_id}", response_model=ClientDanxiActionResponse)
    async def danxi_remove_reply(floor_id: int, request: Request, confirm: bool = False, session_key: str = ""):
        gateway._require_http_auth(request)
        try:
            return _danxi_action_response(
                _DANXI_TOOLS.danxi_delete_reply(floor_id, confirm=confirm, session_key=session_key),
                message="回复已删除，帖子详情已可刷新。",
            )
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.get("/danxi/posts/{hole_id}/summary", response_model=ClientDanxiSummaryResponse)
    async def danxi_post_summary(hole_id: int, request: Request, session_key: str = "", floor_limit: int = 50):
        gateway._require_http_auth(request)
        try:
            return ClientDanxiSummaryResponse(
                **_DANXI_TOOLS.danxi_summarize_post(
                    hole_id,
                    session_key=session_key,
                    floor_limit=floor_limit,
                )
            )
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.get("/danxi/search", response_model=ClientDanxiSearchResponse)
    async def danxi_search(
        request: Request,
        query: str,
        session_key: str = "",
        accurate: bool = False,
        length: int = 20,
        start_floor: int | None = None,
        start_time: str = "",
        end_time: str = "",
    ):
        gateway._require_http_auth(request)
        try:
            payload = _DANXI_TOOLS.danxi_search_posts(
                query,
                session_key=session_key,
                accurate=accurate,
                length=length,
                start_floor=start_floor,
                start_time=start_time,
                end_time=end_time,
            )
            payload["hits_by_hole"] = {str(key): value for key, value in dict(payload.get("hits_by_hole") or {}).items()}
            return ClientDanxiSearchResponse(**payload)
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.get("/danxi/messages", response_model=ClientDanxiListResponse)
    async def danxi_messages(request: Request, session_key: str = "", unread_only: bool = False, start_time: str = ""):
        gateway._require_http_auth(request)
        try:
            return ClientDanxiListResponse(
                **_DANXI_TOOLS.danxi_list_messages(
                    session_key=session_key,
                    unread_only=unread_only,
                    start_time=start_time,
                )
            )
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.get("/danxi/floors/{floor_id}/target", response_model=ClientDanxiMessageTargetResponse)
    async def danxi_message_target(floor_id: int, request: Request, session_key: str = ""):
        gateway._require_http_auth(request)
        try:
            return ClientDanxiMessageTargetResponse(**_DANXI_TOOLS.danxi_resolve_message_target(floor_id, session_key=session_key))
        except Exception as exc:
            _danxi_raise_http_error(gateway, exc)

    @router.get("/procedures", response_model=list[ClientProcedureResponse])
    async def list_procedures(request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        return [
            _procedure_response(item)
            for item in domain.services.procedure.list_active(principal_id=domain.principal.id)
        ]

    @router.get("/procedures/{procedure_id}", response_model=ClientProcedureDetailResponse)
    async def get_procedure(procedure_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        procedure = domain.services.procedure.get_by_procedure_id(procedure_id)
        if procedure is None:
            gateway._raise_http_error(status_code=404, code="procedure_not_found", message=f"未知 procedure: {procedure_id}")
        return _procedure_detail_response(procedure)

    @router.post("/attachments/upload-ticket", response_model=ClientAttachmentUploadTicketResponse)
    async def create_attachment_upload_ticket(http_request: Request, payload: ClientAttachmentUploadTicketRequest):
        gateway._require_http_auth(http_request)
        domain = gateway._require_core_domain()
        owner_type = str(payload.owner_type or "").strip()
        owner_id = str(payload.owner_id or "").strip()
        if not owner_type or not owner_id:
            gateway._raise_http_error(
                status_code=400,
                code="attachment_owner_required",
                message="owner_type 和 owner_id 为必填字段",
            )
        requesting_client = None
        if payload.client_id:
            requesting_client = domain.services.client.ensure_client(
                client_id=payload.client_id,
                principal_id=domain.principal.id,
                client_type="electron",
                display_name=payload.client_id,
            )
        attachment, ticket = domain.services.attachment.create_upload_ticket(
            owner_type=owner_type,
            owner_id=owner_id,
            issuer_type="client",
            issuer_ref=str(payload.client_id or "client").strip() or "client",
            kind=str(payload.kind or "file").strip() or "file",
            mime_type=str(payload.mime_type or "application/octet-stream").strip() or "application/octet-stream",
            file_name=str(payload.file_name or "").strip(),
            size_bytes=max(int(payload.size_bytes or 0), 0),
            lifecycle_policy=str(payload.lifecycle_policy or "normal").strip() or "normal",
            origin_client_id=getattr(requesting_client, "id", None),
        )
        upload_url = str(http_request.base_url).rstrip("/") + f"/client/attachments/upload/{ticket.ticket_id}"
        return ClientAttachmentUploadTicketResponse(
            attachment_id=attachment.attachment_id,
            ticket_id=ticket.ticket_id,
            upload_url=upload_url,
            expires_at=ticket.expires_at,
            object_key=attachment.object_key,
            status=attachment.status,
            created_at=attachment.created_at.isoformat() if getattr(attachment, "created_at", None) is not None else "",
            updated_at=attachment.updated_at.isoformat() if getattr(attachment, "updated_at", None) is not None else "",
        )

    @router.put("/attachments/upload/{ticket_id}", response_model=ClientAttachmentUploadResult)
    async def upload_attachment_content(ticket_id: str, http_request: Request):
        gateway._require_http_auth(http_request)
        domain = gateway._require_core_domain()
        body = await http_request.body()
        try:
            attachment = domain.services.attachment.store_upload_content(ticket_id, body)
        except ValueError as exc:
            gateway._raise_http_error(status_code=409, code=str(exc), message=str(exc))
        return ClientAttachmentUploadResult(
            attachment_id=attachment.attachment_id,
            ticket_id=ticket_id,
            status=attachment.status,
            size_bytes=attachment.size_bytes,
            sha256=attachment.sha256,
            created_at=attachment.created_at.isoformat() if getattr(attachment, "created_at", None) is not None else "",
            updated_at=attachment.updated_at.isoformat() if getattr(attachment, "updated_at", None) is not None else "",
            uploaded_at=str((getattr(attachment, "meta", {}) or {}).get("uploaded_at") or ""),
        )

    @router.post("/attachments/{attachment_id}/complete", response_model=ClientAttachmentResponse)
    async def complete_attachment(attachment_id: str, http_request: Request, payload: ClientAttachmentCompleteRequest):
        gateway._require_http_auth(http_request)
        domain = gateway._require_core_domain()
        try:
            attachment = domain.services.attachment.complete_attachment(
                attachment_id=attachment_id,
                ticket_id=str(payload.ticket_id or "").strip(),
                sha256=str(payload.sha256 or "").strip(),
                size_bytes=payload.size_bytes,
            )
        except ValueError as exc:
            gateway._raise_http_error(status_code=409, code=str(exc), message=str(exc))
        return _attachment_response(attachment)

    @router.get("/attachments", response_model=list[ClientAttachmentResponse])
    async def list_attachments(request: Request, owner_type: str = "", owner_id: str = "", include_deleted: bool = False, limit: int = 50):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            rows = domain.services.attachment.list_attachments(
                owner_type=owner_type,
                owner_id=owner_id,
                include_deleted=include_deleted,
                limit=limit,
            )
        except ValueError as exc:
            gateway._raise_http_error(status_code=400, code=str(exc), message=str(exc))
        return [_attachment_response_from_view(row) for row in rows]

    @router.get("/attachments/{attachment_id}", response_model=ClientAttachmentResponse)
    async def get_attachment(attachment_id: str, request: Request, include_deleted: bool = False):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            row = domain.services.attachment.get_attachment_record(
                attachment_id=attachment_id,
                include_deleted=include_deleted,
            )
        except ValueError as exc:
            gateway._raise_http_error(status_code=404, code=str(exc), message=str(exc))
        return _attachment_response_from_view(row)

    @router.delete("/attachments/{attachment_id}", response_model=ClientAttachmentResponse)
    async def delete_attachment(attachment_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            row = domain.services.attachment.delete_attachment(attachment_id)
        except ValueError as exc:
            gateway._raise_http_error(status_code=404, code=str(exc), message=str(exc))
        return _attachment_response_from_view(row)

    @router.get("/attachments/{attachment_id}/download-ticket", response_model=ClientAttachmentDownloadTicketResponse)
    async def create_attachment_download_ticket(attachment_id: str, http_request: Request, client_id: str = ""):
        gateway._require_http_auth(http_request)
        domain = gateway._require_core_domain()
        fallback_download_url_base = str(http_request.base_url).rstrip("/") + f"/client/attachments/content/{attachment_id}?ticket_id="
        try:
            payload = domain.services.attachment.create_download_ticket(
                attachment_id=attachment_id,
                issuer_type="client",
                issuer_ref=str(client_id or "client").strip() or "client",
                fallback_download_url=fallback_download_url_base,
            )
        except ValueError as exc:
            gateway._raise_http_error(status_code=409, code=str(exc), message=str(exc))
        attachment = payload["attachment"]
        file_name = str((getattr(attachment, "meta", {}) or {}).get("file_name") or attachment.attachment_id)
        fallback_download_url = str(payload.get("fallback_download_url") or "").strip()
        if fallback_download_url:
            fallback_download_url = f"{fallback_download_url}{payload['ticket_id']}"
        download_url = str(payload.get("download_url") or "").strip()
        if str(payload.get("download_strategy") or "") == "proxy":
            download_url = fallback_download_url
        if not download_url:
            download_url = fallback_download_url
        return ClientAttachmentDownloadTicketResponse(
            attachment_id=attachment.attachment_id,
            ticket_id=payload["ticket_id"],
            download_url=download_url,
            fallback_download_url=fallback_download_url,
            download_strategy=str(payload.get("download_strategy") or ""),
            expires_at=payload["expires_at"],
            mime_type=attachment.mime_type,
            file_name=file_name,
            size_bytes=attachment.size_bytes,
        )

    @router.get("/attachments/content/{attachment_id}")
    async def download_attachment_content(attachment_id: str, http_request: Request, ticket_id: str):
        gateway._require_http_auth(http_request)
        domain = gateway._require_core_domain()
        try:
            attachment = domain.services.attachment.validate_download_ticket(
                attachment_id=attachment_id,
                ticket_id=ticket_id,
            )
            content = domain.services.attachment.read_attachment_bytes(attachment_id)
        except ValueError as exc:
            gateway._raise_http_error(status_code=404, code=str(exc), message=str(exc))
        file_name = str((getattr(attachment, "meta", {}) or {}).get("file_name") or attachment.attachment_id)
        return Response(
            content=content,
            media_type=attachment.mime_type,
            headers={"Content-Disposition": build_attachment_content_disposition(file_name)},
        )

    @router.get("/threads/{thread_id}/attachments", response_model=list[ClientAttachmentResponse])
    async def list_thread_attachments(thread_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = domain.services.thread.get_by_thread_id(thread_id)
        if thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"未知 thread: {thread_id}")
        attachments = domain.services.attachment.list_attachments(
            owner_type="thread",
            owner_id=thread_id,
        )
        return [_attachment_response_from_view(item) for item in attachments]

    @router.post("/threads", response_model=ClientThreadResponse)
    async def create_thread(http_request: Request, payload: ClientThreadCreateRequest):
        gateway._require_http_auth(http_request)
        domain = gateway._require_core_domain()
        home_workspace_id = payload.resolved_home_workspace_id
        workspace = domain.services.workspace.get_by_workspace_id(home_workspace_id)
        if workspace is None:
            gateway._raise_http_error(
                status_code=404,
                code="workspace_not_found",
                message=f"未知 workspace: {home_workspace_id}",
            )
        if payload.pinned_procedure_id:
            procedure = domain.services.procedure.get_by_procedure_id(payload.pinned_procedure_id)
            if procedure is None or procedure.status != "active":
                gateway._raise_http_error(
                    status_code=404,
                    code="procedure_not_found",
                    message=f"未知 procedure: {payload.pinned_procedure_id}",
                )
        thread = domain.services.thread.create_thread(
            principal_id=domain.principal.id,
            home_workspace_id=workspace.id,
            title=payload.title,
            pinned_procedure_id=payload.pinned_procedure_id,
        )
        return _thread_response(thread, home_workspace_id)

    @router.get("/threads/{thread_id}", response_model=ClientThreadResponse)
    async def get_thread(thread_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = domain.services.thread.get_by_thread_id(thread_id)
        if thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"未知 thread: {thread_id}")
        workspace = _resolve_thread_home_workspace(gateway, domain, thread=thread)
        return _thread_response(thread, getattr(workspace, "workspace_id", ""))

    @router.get("/threads/{thread_id}/procedure-context", response_model=ClientThreadProcedureContextResponse)
    async def get_thread_procedure_context(thread_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = domain.services.thread.get_by_thread_id(thread_id)
        if thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"未知 thread: {thread_id}")
        return _thread_procedure_context_response(domain, thread)

    @router.put("/threads/{thread_id}/pinned-procedure", response_model=ClientThreadProcedureContextResponse)
    async def set_thread_pinned_procedure(thread_id: str, request: Request, payload: ClientThreadPinnedProcedureRequest):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = domain.services.thread.get_by_thread_id(thread_id)
        if thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"未知 thread: {thread_id}")
        procedure = domain.services.procedure.get_by_procedure_id(str(payload.procedure_id or "").strip())
        if procedure is None:
            gateway._raise_http_error(
                status_code=404,
                code="procedure_not_found",
                message=f"未知 procedure: {payload.procedure_id}",
            )
        if str(getattr(procedure, "status", "active") or "active").strip().lower() != "active":
            gateway._raise_http_error(
                status_code=409,
                code="procedure_not_active",
                message=f"procedure {payload.procedure_id} 当前不可固定",
            )
        domain.services.thread.set_pinned_procedure(thread_id=thread.id, pinned_procedure_id=procedure.procedure_id)
        refreshed = domain.services.thread.get_by_id(thread.id) or thread
        return _thread_procedure_context_response(domain, refreshed)

    @router.delete("/threads/{thread_id}/pinned-procedure", response_model=ClientThreadProcedureContextResponse)
    async def clear_thread_pinned_procedure(thread_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = domain.services.thread.get_by_thread_id(thread_id)
        if thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"未知 thread: {thread_id}")
        domain.services.thread.set_pinned_procedure(thread_id=thread.id, pinned_procedure_id=None)
        refreshed = domain.services.thread.get_by_id(thread.id) or thread
        return _thread_procedure_context_response(domain, refreshed)

    @router.post("/sessions", response_model=ClientSessionResponse)
    async def create_session(http_request: Request, payload: ClientSessionCreateRequest):
        gateway._require_http_auth(http_request)
        domain = gateway._require_core_domain()
        thread = domain.services.thread.get_by_thread_id(payload.thread_id)
        if thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"未知 thread: {payload.thread_id}")
        home_workspace = _resolve_thread_home_workspace(gateway, domain, thread=thread)
        active_workspace_id = payload.resolved_active_workspace_id or getattr(home_workspace, "workspace_id", "")
        workspace = _resolve_active_workspace(gateway, domain, requested_workspace_id=active_workspace_id, thread=thread)
        governance = domain.services.workspace.get_governance_view(workspace)
        client = domain.services.client.ensure_client(
            client_id=payload.client_id,
            principal_id=domain.principal.id,
            client_type=payload.client_type,
            display_name=payload.display_name or payload.client_id,
        )
        _bind_client_workspace(domain, client=client, workspace=home_workspace, role="home")
        _bind_client_workspace(domain, client=client, workspace=workspace, role="active")
        session = domain.services.session.create_session(
            thread_id=thread.id,
            client_id=client.id,
            active_workspace_id=workspace.id,
        )
        source = make_source(SourceKind.WEB.value, payload.client_id, client_id=payload.client_id)
        _bind_runtime_session(
            gateway,
            session_id=session.session_id,
            source=source,
            metadata={
                "thread_id": payload.thread_id,
                "home_workspace_id": getattr(home_workspace, "workspace_id", ""),
                "active_workspace_id": active_workspace_id,
                "workspace_id": active_workspace_id,
                "workspace_title": workspace.title,
                "workspace_base_mode": workspace.base_mode,
                "client_id": payload.client_id,
                "session_row_id": str(getattr(session, "id", "") or ""),
            },
        )
        return ClientSessionResponse(
            session_id=session.session_id,
            thread_id=payload.thread_id,
            active_workspace_id=active_workspace_id,
            workspace_id=active_workspace_id,
            client_id=payload.client_id,
            status=session.status,
        )

    @router.patch("/sessions/{session_id}/active-workspace", response_model=ClientSessionResponse)
    async def update_session_active_workspace(session_id: str, request: Request, payload: ClientActiveWorkspacePatchRequest):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        session_record = domain.services.session.get_by_session_id(session_id)
        if session_record is None:
            gateway._raise_http_error(status_code=404, code="session_not_found", message=f"未知 session: {session_id}")
        thread = domain.services.thread.get_by_id(session_record.thread_id)
        if thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"session {session_id} 缺少 thread")
        workspace = _require_workspace(gateway, domain, workspace_id=payload.active_workspace_id)
        client = domain.services.client.get_by_id(session_record.client_id)
        if client is not None:
            _bind_client_workspace(domain, client=client, workspace=workspace, role="active")
        updated = domain.services.session.set_active_workspace(
            session_id=session_id,
            active_workspace_id=workspace.id,
            metadata={"active_workspace_id": workspace.workspace_id},
        )
        source_client_id = str(payload.client_id or getattr(client, "client_id", "") or "client-http").strip() or "client-http"
        source = make_source(SourceKind.WEB.value, source_client_id, client_id=source_client_id)
        _bind_runtime_session(
            gateway,
            session_id=session_id,
            source=source,
            metadata={
                "thread_id": thread.thread_id,
                "active_workspace_id": workspace.workspace_id,
                "workspace_id": workspace.workspace_id,
                "workspace_title": workspace.title,
                "workspace_base_mode": workspace.base_mode,
                "client_id": source_client_id,
                "session_row_id": str(getattr(session_record, "id", "") or ""),
            },
        )
        await gateway.client_ws_manager.update_session_metadata(
            session_id,
            thread_id=thread.thread_id,
            client_id=source_client_id,
            workspace_id=workspace.workspace_id,
            client_type=str(getattr(client, "client_type", "") or ""),
            display_name=str(getattr(client, "display_name", "") or ""),
        )
        await gateway.publish_client_thread_event(
            thread.thread_id,
            event_type="workspace.changed",
            payload={
                "thread_id": thread.thread_id,
                "session_id": session_id,
                "active_workspace_id": workspace.workspace_id,
                "workspace_id": workspace.workspace_id,
                "client_id": source_client_id,
            },
        )
        return ClientSessionResponse(
            session_id=session_id,
            thread_id=thread.thread_id,
            active_workspace_id=workspace.workspace_id,
            workspace_id=workspace.workspace_id,
            client_id=getattr(client, "client_id", source_client_id),
            status=getattr(updated, "status", getattr(session_record, "status", "active")),
        )

    @router.post("/messages", response_model=ClientMessageResponse)
    async def create_message(http_request: Request, payload: ClientMessageCreateRequest):
        gateway._require_http_auth(http_request)
        domain = gateway._require_core_domain()
        thread = domain.services.thread.get_by_thread_id(payload.thread_id)
        if thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"未知 thread: {payload.thread_id}")
        home_workspace = _resolve_thread_home_workspace(gateway, domain, thread=thread)
        client = domain.services.client.ensure_client(
            client_id=payload.client_id,
            principal_id=domain.principal.id,
            client_type=payload.client_type,
            display_name=payload.display_name or payload.client_id,
        )
        session_record = domain.services.session.get_by_session_id(payload.session_id or "") if payload.session_id else None
        if session_record is not None and session_record.thread_id != thread.id:
            gateway._raise_http_error(
                status_code=400,
                code="session_thread_mismatch",
                message=f"session {payload.session_id} 不属于 thread: {payload.thread_id}",
            )
        workspace = _resolve_active_workspace(
            gateway,
            domain,
            requested_workspace_id=payload.resolved_active_workspace_id,
            session_record=session_record,
            thread=thread,
        )
        active_workspace_id = getattr(workspace, "workspace_id", "")
        governance = domain.services.workspace.get_governance_view(workspace)
        _bind_client_workspace(domain, client=client, workspace=home_workspace, role="home")
        _bind_client_workspace(domain, client=client, workspace=workspace, role="active")
        if session_record is None:
            session_record = domain.services.session.create_session(
                thread_id=thread.id,
                client_id=client.id,
                active_workspace_id=workspace.id,
            )
        source = make_source(SourceKind.WEB.value, payload.client_id, client_id=payload.client_id)
        _bind_runtime_session(
            gateway,
            session_id=session_record.session_id,
            source=source,
            metadata={
                "thread_id": payload.thread_id,
                "home_workspace_id": getattr(home_workspace, "workspace_id", ""),
                "active_workspace_id": active_workspace_id,
                "workspace_id": active_workspace_id,
                "workspace_title": workspace.title,
                "workspace_base_mode": workspace.base_mode,
                "client_id": payload.client_id,
                "session_row_id": str(getattr(session_record, "id", "") or ""),
            },
        )
        await gateway.client_ws_manager.update_session_metadata(
            session_record.session_id,
            thread_id=payload.thread_id,
            client_id=payload.client_id,
            workspace_id=active_workspace_id,
            client_type=payload.client_type,
            display_name=payload.display_name or payload.client_id,
        )
        client_metadata = _ensure_client_always_available_tools(payload.metadata)
        inbound_metadata = {
            "thread_id": payload.thread_id,
            "message_id": message.message_id if False else "",
            "home_workspace_id": getattr(home_workspace, "workspace_id", ""),
            "active_workspace_id": active_workspace_id,
            "workspace_id": active_workspace_id,
            "workspace_title": workspace.title,
            "workspace_base_mode": workspace.base_mode,
            "workspace_prompt_overlay": governance["prompt_overlay"],
            "workspace_default_execution_target": governance["default_execution_target"],
            "workspace_preferred_source_profiles": governance["preferred_source_profiles"],
            "workspace_memory_ranking_policy": governance["memory_ranking_policy"],
        }
        inbound_metadata.update(client_metadata)
        if payload.client_message_id:
            inbound_metadata["client_message_id"] = payload.client_message_id
        inbound_metadata["preferred_mode"] = payload.preferred_mode or workspace.base_mode
        if payload.options:
            inbound_metadata["input_options"] = dict(payload.options)
        if thread.pinned_procedure_id:
            procedure = domain.services.procedure.get_by_procedure_id(thread.pinned_procedure_id)
            if procedure is not None and procedure.status == "active":
                inbound_metadata["pinned_procedure_id"] = procedure.procedure_id
                inbound_metadata["pinned_procedure"] = _procedure_snapshot(procedure)
        message = domain.services.message.create_message(
            thread_id=thread.id,
            session_id=session_record.id,
            role=payload.role,
            content=payload.content,
            source_client_id=client.id,
            active_workspace_id=workspace.id,
            meta={
                "home_workspace_id": getattr(home_workspace, "workspace_id", ""),
                "active_workspace_id": active_workspace_id,
                "workspace_id": active_workspace_id,
                "workspace_base_mode": workspace.base_mode,
                "workspace_prompt_overlay": governance["prompt_overlay"],
                "workspace_default_execution_target": governance["default_execution_target"],
                "workspace_preferred_source_profiles": governance["preferred_source_profiles"],
                "workspace_memory_ranking_policy": governance["memory_ranking_policy"],
                **client_metadata,
                **({"client_message_id": payload.client_message_id} if payload.client_message_id else {}),
                "preferred_mode": payload.preferred_mode or workspace.base_mode,
                **({"input_options": dict(payload.options)} if payload.options else {}),
                **({"pinned_procedure_id": inbound_metadata["pinned_procedure_id"]} if inbound_metadata.get("pinned_procedure_id") else {}),
            },
        )
        inbound_metadata["message_id"] = message.message_id
        _record_context_pool_message(
            domain,
            message=message,
            thread=thread,
            session_record=session_record,
            client=client,
            active_workspace=workspace,
            home_workspace=home_workspace,
            metadata={"source": "client.message"},
        )
        await gateway.publish_client_thread_event(
            payload.thread_id,
            event_type="message.created",
            payload={
                "thread_id": payload.thread_id,
                "session_id": session_record.session_id,
                "message": _message_response(
                    message,
                    thread_id=payload.thread_id,
                    active_workspace_id=active_workspace_id,
                    session_id=session_record.session_id,
                    client_id=payload.client_id,
                ).model_dump(),
            },
        )
        inbound = InboundEvent(
            session_id=session_record.session_id,
            type=EventType.MESSAGE.value,
            role=payload.role,
            content=payload.content,
            source=source,
            target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
            metadata=inbound_metadata,
        )
        await gateway._event_bus.inbound_queue.put(inbound)
        return _message_response(
            message,
            thread_id=payload.thread_id,
            active_workspace_id=active_workspace_id,
            session_id=session_record.session_id,
            client_id=payload.client_id,
        )

    @router.post("/sessions/{session_id}/confirm-response", response_model=ClientConfirmResponseResult)
    async def submit_confirm_response(session_id: str, request: Request, payload: ClientConfirmResponseRequest):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        session_row = domain.services.session.get_by_session_id(session_id)
        if session_row is None:
            gateway._raise_http_error(
                status_code=404,
                code="session_not_found",
                message=f"未知 session: {session_id}",
            )

        source = make_source(SourceKind.WEB.value, str(payload.client_id or "client-http").strip() or "client-http")
        _bind_runtime_session(
            gateway,
            session_id=session_id,
            source=source,
            metadata={
                "client_id": str(payload.client_id or "").strip(),
            },
        )

        app_deps = getattr(gateway, "_dependencies", None)
        app_ref = getattr(app_deps, "app", None)
        approval_context = {}
        if app_ref is not None:
            context_getter = getattr(app_ref, "get_confirm_approval_context", None)
            if callable(context_getter):
                approval_context = dict(context_getter(payload.request_id) or {})

        resolved = gateway._interaction_responses.submit_confirmation_response(
            payload.accepted,
            request_id=payload.request_id,
            session_id=session_id,
            client_id=str(payload.client_id or "").strip(),
            approval_id=str(approval_context.get("approval_id") or ""),
            reason=payload.reason,
        )
        if not resolved:
            gateway._raise_http_error(
                status_code=409,
                code="stale_confirm_response",
                message="确认请求已失效、已处理，或与当前会话不匹配。",
            )

        updated_context = approval_context
        if app_ref is not None:
            context_getter = getattr(app_ref, "get_confirm_approval_context", None)
            if callable(context_getter):
                updated_context = dict(context_getter(payload.request_id) or updated_context or {})

        return ClientConfirmResponseResult(
            request_id=payload.request_id,
            session_id=session_id,
            accepted=payload.accepted,
            approval_id=str(updated_context.get("approval_id") or ""),
            approval_status=str(updated_context.get("approval_status") or ""),
            operation_id=str(updated_context.get("operation_id") or ""),
        )

    @router.post("/sessions/{session_id}/human-input-response", response_model=ClientHumanInputResponseResult)
    async def submit_human_input_response(session_id: str, request: Request, payload: ClientHumanInputResponseRequest):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        session_row = domain.services.session.get_by_session_id(session_id)
        if session_row is None:
            gateway._raise_http_error(
                status_code=404,
                code="session_not_found",
                message=f"未知 session: {session_id}",
            )

        source = make_source(SourceKind.WEB.value, str(payload.client_id or "client-http").strip() or "client-http")
        _bind_runtime_session(
            gateway,
            session_id=session_id,
            source=source,
            metadata={
                "client_id": str(payload.client_id or "").strip(),
            },
        )

        resolved = gateway._interaction_responses.submit_human_input_response(
            payload.answer_text or "",
            request_id=payload.request_id,
            session_id=session_id,
            selected_option=payload.selected_option,
        )
        if not resolved:
            gateway._raise_http_error(
                status_code=409,
                code="stale_input_response",
                message="补充输入请求已失效、已处理，或与当前会话不匹配。",
            )

        return ClientHumanInputResponseResult(
            request_id=payload.request_id,
            session_id=session_id,
            answer_text=payload.answer_text or "",
            selected_option=payload.selected_option,
        )

    @router.get("/threads/{thread_id}/messages", response_model=list[ClientMessageResponse])
    async def list_thread_messages(thread_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = domain.services.thread.get_by_thread_id(thread_id)
        if thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"未知 thread: {thread_id}")
        home_workspace = _resolve_thread_home_workspace(gateway, domain, thread=thread)
        messages = domain.services.message.list_messages_for_thread(thread.id)
        session_lookup = {}
        client_lookup = {}
        workspace_lookup = {}
        results: list[ClientMessageResponse] = []
        for item in messages:
            session_id = ""
            client_id = ""
            active_workspace_id = getattr(home_workspace, "workspace_id", "")
            if item.session_id is not None:
                session_row = session_lookup.get(item.session_id)
                if session_row is None:
                    session_row = domain.services.session.get_by_id(item.session_id)
                    session_lookup[item.session_id] = session_row
                session_id = getattr(session_row, "session_id", "")
                workspace_row_id = getattr(item, "active_workspace_id", None) or getattr(session_row, "active_workspace_id", None)
                if workspace_row_id is not None:
                    workspace_row = workspace_lookup.get(workspace_row_id)
                    if workspace_row is None:
                        workspace_row = domain.services.workspace.get_by_id(workspace_row_id)
                        workspace_lookup[workspace_row_id] = workspace_row
                    active_workspace_id = getattr(workspace_row, "workspace_id", active_workspace_id)
            if item.source_client_id is not None:
                client_row = client_lookup.get(item.source_client_id)
                if client_row is None:
                    client_row = domain.services.client.get_by_id(item.source_client_id)
                    client_lookup[item.source_client_id] = client_row
                client_id = getattr(client_row, "client_id", "")
            results.append(
                _message_response(
                    item,
                    thread_id=thread.thread_id,
                    active_workspace_id=active_workspace_id,
                    session_id=session_id,
                    client_id=client_id,
                )
            )
        return results

    @router.post("/operations", response_model=ClientOperationResponse)
    async def create_operation(http_request: Request, payload: ClientOperationCreateRequest):
        gateway._require_http_auth(http_request)
        domain = gateway._require_core_domain()
        thread = domain.services.thread.get_by_thread_id(payload.thread_id)
        if thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"未知 thread: {payload.thread_id}")
        workspace = _require_workspace(gateway, domain, workspace_id=payload.workspace_id)
        procedure, procedure_profile = _resolve_procedure_execution_profile(domain, payload=payload)
        preferred_tool_key = str(procedure_profile.get("preferred_tool_key") or "").strip()
        requested_execution_target = str(payload.execution_target or "").strip()
        execution_target_from_workspace_default = not requested_execution_target
        execution_target = normalize_execution_target(
            requested_execution_target
            or str(getattr(procedure, "default_execution_target", "") or "").strip()
            or workspace.default_execution_target,
            fallback=normalize_execution_target(workspace.default_execution_target),
        )
        implicit_specific_client_ok = execution_target_from_workspace_default or procedure is not None
        if requires_specific_client(execution_target) and not payload.target_client_id and not implicit_specific_client_ok:
            gateway._raise_http_error(
                status_code=400,
                code="target_client_required",
                message="execution_target=specific_client 时 target_client_id 为必填字段",
            )
        if payload.target_client_id and execution_target != EXECUTION_TARGET_SPECIFIC_CLIENT:
            gateway._raise_http_error(
                status_code=400,
                code="ambiguous_execution_target",
                message="仅当 execution_target=specific_client 时才允许传入 target_client_id",
            )
        target_client = None
        tool = None
        if payload.target_client_id:
            target_client = domain.services.client.get_by_client_id(payload.target_client_id)
            if target_client is None:
                gateway._raise_http_error(
                    status_code=404,
                    code="client_not_found",
                    message=f"未知 client: {payload.target_client_id}",
                )
            if not domain.services.client.is_bound_to_workspace(
                client_id=payload.target_client_id,
                workspace_id=payload.workspace_id,
            ):
                gateway._raise_http_error(
                    status_code=400,
                    code="client_workspace_mismatch",
                    message=f"client {payload.target_client_id} 不属于 workspace: {payload.workspace_id}",
                )
        tool_key = str(payload.tool_key or payload.tool_id or "").strip() or preferred_tool_key
        if tool_key:
            tool = domain.services.tool.resolve_tool_reference(
                tool_key=tool_key,
                workspace_id=workspace.id,
                target_client_id=payload.target_client_id,
            )
            if tool is None:
                gateway._raise_http_error(
                    status_code=404,
                    code="tool_not_found",
                    message=f"未知 tool 或抽象能力名: {tool_key}",
                )
            if target_client is not None and tool.provider_ref != target_client.client_id:
                gateway._raise_http_error(
                    status_code=400,
                    code="tool_client_mismatch",
                    message=f"tool {tool_key} 不属于 client: {payload.target_client_id}",
                )
            if not domain.services.tool.is_available_in_workspace(
                tool_id=tool.tool_id,
                workspace_id=workspace.id,
            ):
                gateway._raise_http_error(
                    status_code=400,
                    code="tool_workspace_mismatch",
                    message=f"tool {tool_key} 不属于 workspace: {payload.workspace_id}",
                )
            if not domain.services.workspace.tool_allowed(workspace, tool_key) and not domain.services.workspace.tool_allowed(
                workspace,
                domain.services.tool.get_abstract_tool_key(tool),
            ):
                gateway._raise_http_error(
                    status_code=403,
                    code="tool_not_allowed_in_workspace",
                    message=f"tool {tool_key} 不在 workspace {payload.workspace_id} 的允许列表内",
                )
        governance = domain.services.workspace.get_governance_view(workspace)
        if (
            str(payload.operation_type or "").strip() == "tool_call"
            and governance["tool_policy"] == "allowlist"
            and not payload.tool_id
        ):
            gateway._raise_http_error(
                status_code=400,
                code="tool_required_by_workspace_policy",
                message=f"workspace {payload.workspace_id} 启用了 tool allowlist，tool_call 必须显式提供 tool_id",
            )
        requesting_client = _resolve_requesting_client(
            domain,
            client_id=payload.client_id,
            session_id=payload.session_id,
        )
        routing_reason = ""
        resolved_execution_target = execution_target
        if target_client is None and execution_target in {
            EXECUTION_TARGET_SPECIFIC_CLIENT,
            EXECUTION_TARGET_WORKSPACE_ANY_CLIENT,
            EXECUTION_TARGET_PREFER_CLIENT_FALLBACK_CORE,
        }:
            target_client, routing_reason = _resolve_workspace_target_client(
                domain,
                workspace=workspace,
                tool=tool,
                tool_key=tool_key,
                execution_target=execution_target,
                requesting_client=requesting_client,
                routing_preferences=(
                    {
                        "preferred_target_client_ids": procedure_profile.get("preferred_target_client_ids") or [],
                        "preferred_target_client_types": procedure_profile.get("preferred_target_client_types") or [],
                        "tool_target_routing_policy": procedure_profile.get("tool_target_routing_policy") or "balanced",
                        "source": f"procedure:{procedure_profile.get('procedure_id') or 'unknown'}",
                    }
                    if procedure is not None
                    else None
                ),
            )
            if target_client is None:
                if execution_target == EXECUTION_TARGET_PREFER_CLIENT_FALLBACK_CORE:
                    if tool is not None and str(getattr(tool, "provider_type", "") or "") == "client":
                        gateway._raise_http_error(
                            status_code=409,
                            code="core_fallback_unavailable",
                            message=routing_reason or "Client tool 当前无可用核心降级路径",
                        )
                    resolved_execution_target = "core_only"
                elif execution_target == EXECUTION_TARGET_WORKSPACE_ANY_CLIENT or execution_target_from_workspace_default:
                    gateway._raise_http_error(
                        status_code=409,
                        code="workspace_client_unavailable",
                        message=routing_reason or f"No online client is available for workspace: {workspace.workspace_id}",
                    )
        if tool is not None and target_client is not None and tool.provider_ref != target_client.client_id:
            tool = domain.services.tool.resolve_tool_reference(
                tool_key=tool_key,
                workspace_id=workspace.id,
                target_client_id=target_client.client_id,
            )
            if tool is None:
                gateway._raise_http_error(
                    status_code=409,
                    code="tool_resolution_failed",
                    message=f"无法将 tool {tool_key} 解析到 client: {target_client.client_id}",
                )

        approval_required = bool(target_client is not None and tool is not None and _tool_requires_approval(tool))
        operation_arguments = dict(payload.arguments or {})
        operation_encrypted_arguments = None
        operation_arguments_encrypted = False
        if target_client is not None and tool is not None:
            try:
                protected_arguments = protect_sensitive_arguments(
                    operation_arguments,
                    purpose=CLIENT_TOOL_ARGUMENTS_PURPOSE,
                )
            except CredentialTransportError as exc:
                gateway._raise_http_error(
                    status_code=503 if exc.code == "credential_key_unavailable" else 400,
                    code=exc.code,
                    message=exc.message,
                )
            operation_arguments = dict(protected_arguments.public_arguments or {})
            operation_encrypted_arguments = protected_arguments.encrypted_arguments
            operation_arguments_encrypted = bool(operation_encrypted_arguments)

        operation = domain.services.operation.create_operation(
            thread_id=thread.id,
            workspace_id=workspace.id,
            operation_type=payload.operation_type,
            execution_target=resolved_execution_target,
            title=payload.title,
            target_client_id=getattr(target_client, "id", None),
            requested_by_client_id=requesting_client.id,
            status="waiting_approval" if approval_required else "queued",
            metadata={
                "target_client_id": getattr(target_client, "client_id", "") or payload.target_client_id or "",
                "tool_id": getattr(tool, "tool_id", "") or tool_key,
                "tool_key": tool_key,
                "abstract_tool_key": domain.services.tool.get_abstract_tool_key(tool) if tool is not None else "",
                "arguments": operation_arguments,
                "arguments_encrypted": operation_arguments_encrypted,
                "approval_required": approval_required,
                "routing_reason": routing_reason,
                **({"encrypted_arguments": operation_encrypted_arguments} if operation_encrypted_arguments else {}),
                **({"procedure_id": procedure_profile.get("procedure_id", "")} if procedure is not None else {}),
                **({"procedure": procedure_profile.get("procedure_snapshot", {})} if procedure is not None else {}),
            },
        )
        if approval_required:
            approval = domain.services.approval.create_approval(
                operation_id=operation.id,
                approval_type="operation_execution",
                risk_level=str(getattr(tool, "risk_level", "write") or "write"),
            )
            operation = domain.services.operation.update_status(
                operation_id=operation.id,
                status="waiting_approval",
                metadata={
                    "approval_id": approval.approval_id,
                    "approval_status": approval.status,
                    "approval_type": approval.approval_type,
                    "approval_risk_level": approval.risk_level,
                    "approval_required": True,
                },
            ) or operation
            await _publish_operation_update(
                gateway,
                operation=operation,
                thread_id=payload.thread_id,
                phase="approval",
                detail="等待审批后再执行",
            )
            return _operation_response(operation, workspace_id=payload.workspace_id, thread_id=payload.thread_id)

        await _publish_operation_update(
            gateway,
            operation=operation,
            thread_id=payload.thread_id,
            phase="queued",
            detail="操作已创建，等待调度",
        )
        if target_client is not None and tool is not None:
            operation, _ = await _dispatch_specific_client_operation(
                gateway,
                domain,
                operation=operation,
                thread=thread,
                workspace=workspace,
                requesting_client=requesting_client,
            )
        return _operation_response(operation, workspace_id=payload.workspace_id, thread_id=payload.thread_id)

    @router.get("/operations/{operation_id}", response_model=ClientOperationResponse)
    async def get_operation(operation_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        operation = domain.services.operation.get_by_operation_id(operation_id)
        if operation is None:
            gateway._raise_http_error(
                status_code=404,
                code="operation_not_found",
                message=f"未知 operation: {operation_id}",
            )
        workspace = _get_workspace_by_row_id(domain, operation.workspace_id)
        thread = domain.services.thread.get_by_id(operation.thread_id)
        return _operation_response(
            operation,
            workspace_id=getattr(workspace, "workspace_id", ""),
            thread_id=getattr(thread, "thread_id", ""),
        )

    @router.post("/approvals/{approval_id}/decision", response_model=ClientApprovalResponse)
    async def decide_approval(approval_id: str, request: Request, payload: ClientApprovalDecisionRequest):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        existing = domain.services.approval.get_by_approval_id(approval_id)
        if existing is None:
            gateway._raise_http_error(
                status_code=404,
                code="approval_not_found",
                message=f"未知 approval: {approval_id}",
            )
        if existing.status != "pending":
            gateway._raise_http_error(
                status_code=409,
                code="approval_already_decided",
                message=f"approval 已处理: {approval_id}",
            )
        client = None
        if payload.client_id:
            client = domain.services.client.ensure_client(
                client_id=payload.client_id,
                principal_id=domain.principal.id,
                client_type="electron",
                display_name=payload.client_id,
            )
        linked_operation = domain.services.operation.get_by_id(existing.operation_id)
        linked_metadata = dict(getattr(linked_operation, "meta", {}) or {}) if linked_operation is not None else {}
        if str(linked_metadata.get("confirm_request_id") or "").strip() and str(linked_metadata.get("confirm_session_id") or "").strip():
            approval, operation = await _resolve_chat_confirmation_from_approval(
                gateway,
                domain,
                approval=existing,
                payload=payload,
            )
            return ClientApprovalResponse(
                approval_id=approval.approval_id,
                operation_id=getattr(operation, "operation_id", ""),
                approval_type=approval.approval_type,
                risk_level=approval.risk_level,
                status=approval.status,
                decision=approval.decision,
                reason=approval.reason,
                operation_status=getattr(operation, "status", ""),
            )
        approval = domain.services.approval.decide_approval(
            approval_id=approval_id,
            decision=payload.decision,
            reason=payload.reason,
            decided_by_client_id=getattr(client, "id", None),
        )
        operation = domain.services.operation.get_by_id(approval.operation_id)
        thread = domain.services.thread.get_by_id(operation.thread_id) if operation is not None else None
        workspace = _get_workspace_by_row_id(domain, getattr(operation, "workspace_id", None)) if operation is not None else None
        requesting_client = domain.services.client.get_by_id(getattr(operation, "requested_by_client_id", None)) if operation is not None else None

        if operation is not None:
            if approval.status == "approved":
                operation = domain.services.operation.update_status(
                    operation_id=operation.id,
                    status="queued",
                    metadata={
                        "approval_id": approval.approval_id,
                        "approval_status": approval.status,
                        "approval_required": True,
                    },
                ) or operation
                if thread is not None:
                    await _publish_operation_update(
                        gateway,
                        operation=operation,
                        thread_id=thread.thread_id,
                        phase="approval",
                        detail="审批已通过，准备调度",
                    )
                if thread is not None and workspace is not None:
                    operation, _ = await _dispatch_specific_client_operation(
                        gateway,
                        domain,
                        operation=operation,
                        thread=thread,
                        workspace=workspace,
                        requesting_client=requesting_client,
                    )
            else:
                operation = domain.services.operation.update_status(
                    operation_id=operation.id,
                    status="rejected",
                    result_summary=approval.reason or "操作已被拒绝",
                    metadata={
                        "approval_id": approval.approval_id,
                        "approval_status": approval.status,
                        "approval_required": True,
                        "error": {
                            "code": "approval_rejected",
                            "message": approval.reason or "操作已被拒绝",
                        },
                    },
                ) or operation
                if thread is not None:
                    await _publish_operation_update(
                        gateway,
                        operation=operation,
                        thread_id=thread.thread_id,
                        phase="approval",
                        detail=approval.reason or "操作已被拒绝",
                        error={"code": "approval_rejected", "message": approval.reason or "操作已被拒绝"},
                    )
        return ClientApprovalResponse(
            approval_id=approval.approval_id,
            operation_id=getattr(operation, "operation_id", ""),
            approval_type=approval.approval_type,
            risk_level=approval.risk_level,
            status=approval.status,
            decision=approval.decision,
            reason=approval.reason,
            operation_status=getattr(operation, "status", ""),
        )

    @router.websocket("/ws")
    async def client_websocket_endpoint(websocket: WebSocket):
        if not await gateway._authorize_websocket(websocket):
            return
        thread_id = str(websocket.query_params.get("thread_id") or "").strip() or "client-tool-runtime"
        await websocket.accept()
        await gateway.client_ws_manager.connect(thread_id, websocket)
        dependencies = getattr(gateway, "_dependencies", None)
        domain = getattr(dependencies, "core_domain", None)
        initial_session_id = str(websocket.query_params.get("session_id") or "").strip()
        initial_client_id = str(websocket.query_params.get("client_id") or "").strip()
        initial_workspace_id = str(
            websocket.query_params.get("active_workspace_id")
            or websocket.query_params.get("workspace_id")
            or ""
        ).strip()
        initial_client_type = str(websocket.query_params.get("client_type") or "").strip()
        initial_display_name = str(websocket.query_params.get("display_name") or "").strip()
        if initial_session_id or initial_client_id:
            bound_client_id = initial_client_id
            bound_workspace_id = initial_workspace_id
            bound_client_type = initial_client_type
            bound_display_name = initial_display_name
            if domain is not None and initial_session_id:
                session_row, thread_row, workspace_row, client_row, session_error_code, session_error_message = _resolve_client_session_for_thread(
                    domain,
                    session_id=initial_session_id,
                    thread_id=thread_id,
                )
                if session_error_code:
                    await gateway._safe_send_json(
                        websocket,
                        {
                            "schema": "meetyou.client.ws.v1",
                            "kind": "error",
                            "error": RuntimeError(
                                code=session_error_code,
                                category="validation",
                                message=session_error_message,
                            ).model_dump(),
                        },
                    )
                    await websocket.close(code=4400)
                    await gateway.client_ws_manager.disconnect(thread_id, websocket)
                    return
                home_workspace_row = (
                    _get_workspace_by_row_id(
                        domain,
                        getattr(thread_row, "home_workspace_id", None) or getattr(thread_row, "workspace_id", None),
                    )
                    if thread_row is not None
                    else None
                )
                bound_client_id = getattr(client_row, "client_id", "") or bound_client_id
                bound_workspace_id = getattr(workspace_row, "workspace_id", "") or bound_workspace_id
                bound_client_type = getattr(client_row, "client_type", "") or bound_client_type
                bound_display_name = getattr(client_row, "display_name", "") or bound_display_name
                source = make_source(SourceKind.WEB.value, bound_client_id or "client-ws", client_id=bound_client_id)
                _bind_runtime_session(
                    gateway,
                    session_id=initial_session_id,
                    source=source,
                    metadata={
                        "thread_id": thread_id,
                        "home_workspace_id": getattr(home_workspace_row, "workspace_id", ""),
                        "active_workspace_id": bound_workspace_id,
                        "workspace_id": bound_workspace_id,
                        "client_id": bound_client_id,
                        "session_row_id": str(getattr(session_row, "id", "") or ""),
                    },
                )
            await gateway.client_ws_manager.bind_connection(
                websocket,
                thread_id=thread_id,
                client_id=bound_client_id,
                session_id=initial_session_id,
                workspace_id=bound_workspace_id,
                client_type=bound_client_type,
                display_name=bound_display_name,
            )
        connected = await gateway._safe_send_json(websocket, gateway.client_ws_manager.connection_payload(thread_id))
        if not connected:
            await gateway.client_ws_manager.disconnect(thread_id, websocket)
            return
        try:
            while True:
                try:
                    raw_frame = await websocket.receive_json()
                    if isinstance(raw_frame, dict) and await _handle_client_tool_frame(gateway, websocket, raw_frame, thread_id=thread_id):
                        continue
                    command = ClientWsCommand.model_validate(raw_frame)
                except WebSocketDisconnect:
                    break
                except ValidationError as exc:
                    sent = await gateway._safe_send_json(
                        websocket,
                        {
                            "schema": "meetyou.client.ws.v1",
                            "kind": "error",
                            "error": RuntimeError(
                                code="invalid_payload",
                                category="validation",
                                message=str(exc),
                            ).model_dump(),
                        },
                    )
                    if not sent:
                        break
                    continue
                action = str(command.action or "").strip()
                if action == "ping":
                    if not await gateway._safe_send_json(websocket, gateway.client_ws_manager.pong_payload()):
                        break
                    continue
                command_session_id = str(command.session_id or "").strip()
                if not command_session_id:
                    sent = await gateway._safe_send_json(
                        websocket,
                        {
                            "schema": "meetyou.client.ws.v1",
                            "kind": "error",
                            "error": RuntimeError(
                                code="session_id_required",
                                category="validation",
                                message="session_id 为必填字段",
                            ).model_dump(),
                        },
                    )
                    if not sent:
                        break
                    continue
                source = make_source(SourceKind.WEB.value, str(command.client_id or "client-ws").strip() or "client-ws")
                bound_client_id = str(command.client_id or "").strip()
                bound_workspace_id = ""
                bound_client_type = ""
                bound_display_name = ""
                if domain is not None:
                    session_row, thread_row, workspace_row, client_row, session_error_code, session_error_message = _resolve_client_session_for_thread(
                        domain,
                        session_id=command_session_id,
                        thread_id=thread_id,
                    )
                    if session_error_code:
                        sent = await gateway._safe_send_json(
                            websocket,
                            {
                                "schema": "meetyou.client.ws.v1",
                                "kind": "error",
                                "error": RuntimeError(
                                    code=session_error_code,
                                    category="validation",
                                    message=session_error_message,
                                ).model_dump(),
                            },
                        )
                        if not sent:
                            break
                        continue
                    home_workspace_row = (
                        _get_workspace_by_row_id(
                            domain,
                            getattr(thread_row, "home_workspace_id", None) or getattr(thread_row, "workspace_id", None),
                        )
                        if thread_row is not None
                        else None
                    )
                    _bind_runtime_session(
                        gateway,
                        session_id=command_session_id,
                        source=source,
                        metadata={
                            "thread_id": thread_id,
                            "home_workspace_id": getattr(home_workspace_row, "workspace_id", ""),
                            "active_workspace_id": getattr(workspace_row, "workspace_id", ""),
                            "workspace_id": getattr(workspace_row, "workspace_id", ""),
                            "client_id": getattr(client_row, "client_id", "") or str(command.client_id or "").strip(),
                            "session_row_id": str(getattr(session_row, "id", "") or ""),
                        },
                    )
                    bound_client_id = getattr(client_row, "client_id", "") or bound_client_id
                    bound_workspace_id = getattr(workspace_row, "workspace_id", "")
                    bound_client_type = getattr(client_row, "client_type", "")
                    bound_display_name = getattr(client_row, "display_name", "")
                else:
                    _bind_runtime_session(
                        gateway,
                        session_id=command_session_id,
                        source=source,
                        metadata={
                            "thread_id": thread_id,
                            "client_id": str(command.client_id or "").strip(),
                        },
                    )
                await gateway.client_ws_manager.bind_connection(
                    websocket,
                    thread_id=thread_id,
                    client_id=bound_client_id,
                    session_id=command_session_id,
                    workspace_id=bound_workspace_id,
                    client_type=bound_client_type,
                    display_name=bound_display_name,
                )
                if action == "confirm_response":
                    if command.request_id is None or command.accepted is None:
                        sent = await gateway._safe_send_json(
                            websocket,
                            {
                                "schema": "meetyou.client.ws.v1",
                                "kind": "error",
                                "error": RuntimeError(
                                    code="invalid_confirm_response",
                                    category="validation",
                                    message="request_id 和 accepted 为必填字段",
                                ).model_dump(),
                            },
                        )
                        if not sent:
                            break
                        continue
                    resolved = gateway._interaction_responses.submit_confirmation_response(
                        command.accepted,
                        request_id=command.request_id,
                        session_id=command_session_id,
                        client_id=str(command.client_id or "").strip(),
                        approval_id=str((command.metadata or {}).get("approval_id") or "").strip(),
                    )
                    if not resolved:
                        sent = await gateway._safe_send_json(
                            websocket,
                            {
                                "schema": "meetyou.client.ws.v1",
                                "kind": "error",
                                "error": RuntimeError(
                                    code="stale_confirm_response",
                                    message="确认请求已失效、已处理，或与当前会话不匹配。",
                                ).model_dump(),
                            },
                        )
                        if not sent:
                            break
                        continue
                    sent = await gateway._safe_send_json(
                        websocket,
                        {
                            "schema": "meetyou.client.ws.v1",
                            "kind": "ack",
                            "ack": {
                                "action": action,
                                "request_id": command.request_id,
                                "session_id": command_session_id,
                                "accepted": True,
                            },
                        },
                    )
                    if not sent:
                        break
                    continue
                if action == "input_response":
                    if command.request_id is None:
                        sent = await gateway._safe_send_json(
                            websocket,
                            {
                                "schema": "meetyou.client.ws.v1",
                                "kind": "error",
                                "error": RuntimeError(
                                    code="invalid_input_response",
                                    category="validation",
                                    message="request_id 为必填字段",
                                ).model_dump(),
                            },
                        )
                        if not sent:
                            break
                        continue
                    resolved = gateway._interaction_responses.submit_human_input_response(
                        command.answer_text or "",
                        request_id=command.request_id,
                        session_id=command_session_id,
                        selected_option=command.selected_option,
                    )
                    if not resolved:
                        sent = await gateway._safe_send_json(
                            websocket,
                            {
                                "schema": "meetyou.client.ws.v1",
                                "kind": "error",
                                "error": RuntimeError(
                                    code="stale_input_response",
                                    message="补充输入请求已失效、已处理，或与当前会话不匹配。",
                                ).model_dump(),
                            },
                        )
                        if not sent:
                            break
                        continue
                    sent = await gateway._safe_send_json(
                        websocket,
                        {
                            "schema": "meetyou.client.ws.v1",
                            "kind": "ack",
                            "ack": {
                                "action": action,
                                "request_id": command.request_id,
                                "session_id": command_session_id,
                                "accepted": True,
                            },
                        },
                    )
                    if not sent:
                        break
                    continue
                if action in {"stop", "append_guidance", "regenerate", "rollback", "list_checkpoints"}:
                    client_request_id = str(command.client_request_id or "").strip()
                    if client_request_id:
                        existing_event_id = gateway._session_manager.get_recent_inbound_event_id(
                            command_session_id,
                            source,
                            client_request_id,
                        )
                        if existing_event_id:
                            sent = await gateway._safe_send_json(
                                websocket,
                                {
                                    "schema": "meetyou.client.ws.v1",
                                    "kind": "ack",
                                    "ack": {
                                        "action": action,
                                        "request_id": client_request_id,
                                        "session_id": command_session_id,
                                        "event_id": existing_event_id,
                                        "accepted": True,
                                        "status": "accepted",
                                    },
                                },
                            )
                            if not sent:
                                break
                            continue
                    event = InboundEvent(
                        session_id=command_session_id,
                        type=EventType.CONTROL.value,
                        role="system",
                        content={
                            "action": action,
                            "guidance": command.guidance,
                            "checkpoint_id": command.checkpoint_id,
                            "turn_id": command.turn_id,
                            "stream_id": command.stream_id,
                        },
                        source=source,
                        target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                        metadata={
                            "control_kind": "reply_control",
                            **dict(command.metadata or {}),
                            **({"client_request_id": client_request_id} if client_request_id else {}),
                        },
                    )
                    if client_request_id:
                        remembered_event_id = gateway._session_manager.remember_inbound_event_id(
                            command_session_id,
                            source,
                            client_request_id,
                            event.event_id,
                        )
                        if remembered_event_id != event.event_id:
                            sent = await gateway._safe_send_json(
                                websocket,
                                {
                                    "schema": "meetyou.client.ws.v1",
                                    "kind": "ack",
                                    "ack": {
                                        "action": action,
                                        "request_id": client_request_id,
                                        "session_id": command_session_id,
                                        "event_id": remembered_event_id,
                                        "accepted": True,
                                        "status": "accepted",
                                    },
                                },
                            )
                            if not sent:
                                break
                            continue
                    await gateway._event_bus.inbound_queue.put(event)
                    sent = await gateway._safe_send_json(
                        websocket,
                        {
                            "schema": "meetyou.client.ws.v1",
                            "kind": "ack",
                            "ack": {
                                "action": action,
                                "request_id": client_request_id,
                                "session_id": command_session_id,
                                "event_id": event.event_id,
                                "accepted": True,
                                "status": "accepted",
                            },
                        },
                    )
                    if not sent:
                        break
                    continue
                sent = await gateway._safe_send_json(
                    websocket,
                    {
                        "schema": "meetyou.client.ws.v1",
                        "kind": "error",
                        "error": RuntimeError(
                            code="unsupported_action",
                            category="validation",
                            message=f"不支持的 action: {action}",
                        ).model_dump(),
                    },
                )
                if not sent:
                    break
        except WebSocketDisconnect:
            pass
        finally:
            await gateway.client_ws_manager.disconnect(thread_id, websocket)

    return router
