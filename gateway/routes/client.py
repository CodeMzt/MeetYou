from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import ValidationError

from agent_protocol import build_capability_call_request
from core.credential_transport import CredentialTransportError, decrypt_json_payload
from core.http_headers import build_attachment_content_disposition
from core.io_protocol import EventTarget, EventType, InboundEvent, SourceKind, TargetKind, make_source
from core.public_contract import (
    EXECUTION_TARGET_PREFER_AGENT_FALLBACK_CORE,
    EXECUTION_TARGET_SPECIFIC_AGENT,
    EXECUTION_TARGET_WORKSPACE_ANY_AGENT,
    normalize_execution_target,
    requires_specific_agent,
)

from gateway.models import (
    ClientApprovalDecisionRequest,
    ClientDanxiActionResponse,
    ClientDanxiListResponse,
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
    ClientAvailableAgentResponse,
    ClientOperationCreateRequest,
    ClientOperationResponse,
    ClientMessageCreateRequest,
    ClientMessageResponse,
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
)
from service_runtime.models import RuntimeError
from tools.danxi_tools import get_shared_danxi_tools


_APPROVAL_RISK_LEVELS = {"write", "system", "device", "destructive", "local_write", "external_write"}
_DANXI_TOOLS = get_shared_danxi_tools()
_DANXI_LOGIN_PURPOSE = "danxi.client.login.v1"
_DANXI_WEBVPN_PURPOSE = "danxi.client.webvpn_cookie.v1"


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
    if not payload.encrypted_credentials:
        raise CredentialTransportError(
            "credential_encrypted_required",
            "Danxi 登录请求必须提供 encrypted_credentials，已禁用明文跨边界凭证传输。",
        )
    decrypted = decrypt_json_payload(payload.encrypted_credentials, purpose=_DANXI_LOGIN_PURPOSE)
    return {
        "email": str(decrypted.get("email") or ""),
        "password": str(decrypted.get("password") or ""),
        "session_key": str(decrypted.get("session_key") or payload.session_key or "default"),
        "use_webvpn": decrypted.get("use_webvpn"),
        "webvpn_cookie": str(decrypted.get("webvpn_cookie") or ""),
    }


def _resolve_danxi_webvpn_cookie_payload(payload: ClientDanxiWebvpnCookiePatchRequest) -> dict[str, Any]:
    if not payload.encrypted_credentials:
        raise CredentialTransportError(
            "credential_encrypted_required",
            "Danxi WebVPN 登录态更新必须提供 encrypted_credentials，已禁用明文跨边界凭证传输。",
        )
    decrypted = decrypt_json_payload(payload.encrypted_credentials, purpose=_DANXI_WEBVPN_PURPOSE)
    return {
        "session_key": str(decrypted.get("session_key") or payload.session_key or "default"),
        "cookie_header": str(decrypted.get("cookie_header") or ""),
        "enable_webvpn": bool(decrypted.get("enable_webvpn", True)),
    }


def _thread_response(thread, workspace_id: str) -> ClientThreadResponse:
    return ClientThreadResponse(
        thread_id=thread.thread_id,
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
        recommended_capabilities=routing["recommended_capabilities"],
        preferred_capability_ref=routing["preferred_capability_ref"],
        preferred_agent_ids=routing["preferred_agent_ids"],
        preferred_agent_types=routing["preferred_agent_types"],
        agent_routing_policy=routing["agent_routing_policy"],
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
        target_agent_id=str(metadata.get("target_agent_key") or ""),
        capability_id=str(metadata.get("capability_id") or ""),
        status=operation.status,
        approval_id=str(metadata.get("approval_id") or ""),
        approval_status=str(metadata.get("approval_status") or ""),
        approval_required=bool(metadata.get("approval_required", False)),
        routing_reason=str(metadata.get("routing_reason") or ""),
    )


def _message_response(message, *, thread_id: str, workspace_id: str, session_id: str = "", client_id: str = "") -> ClientMessageResponse:
    return ClientMessageResponse(
        message_id=message.message_id,
        thread_id=thread_id,
        session_id=session_id,
        workspace_id=workspace_id,
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


def _require_thread_workspace(gateway, domain, *, thread, workspace_id: str):
    workspace = domain.services.workspace.get_by_workspace_id(workspace_id)
    if workspace is None:
        gateway._raise_http_error(
            status_code=404,
            code="workspace_not_found",
            message=f"未知 workspace: {workspace_id}",
        )
    if thread.workspace_id != workspace.id:
        gateway._raise_http_error(
            status_code=400,
            code="thread_workspace_mismatch",
            message=f"thread {thread.thread_id} 不属于 workspace: {workspace_id}",
        )
    return workspace


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
        capability_policy=governance["capability_policy"],
        allowed_capability_ids=governance["allowed_capability_ids"],
        preferred_agent_ids=governance["preferred_agent_ids"],
        preferred_agent_types=governance["preferred_agent_types"],
        preferred_source_profiles=governance["preferred_source_profiles"],
        agent_routing_policy=governance["agent_routing_policy"],
        memory_ranking_policy=governance["memory_ranking_policy"],
        capability_routing_overrides=governance["capability_routing_overrides"],
    )


def _resolve_procedure_execution_profile(domain, *, payload) -> tuple[object | None, dict[str, Any]]:
    arguments = dict(payload.arguments or {}) if isinstance(payload.arguments, dict) else {}
    procedure_id = str(arguments.get("procedure_id") or "").strip()
    if not procedure_id and str(payload.operation_type or "") == "procedure_call":
        candidate = str(payload.capability_id or "").strip()
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
        "preferred_capability_ref": routing["preferred_capability_ref"],
        "preferred_agent_ids": routing["preferred_agent_ids"],
        "preferred_agent_types": routing["preferred_agent_types"],
        "agent_routing_policy": routing["agent_routing_policy"],
    }


def _resolve_workspace_target_agent(domain, *, workspace, capability, capability_ref: str = "", execution_target: str, requesting_client, explicit_target_agent=None, routing_preferences: dict[str, Any] | None = None) -> tuple[object | None, str]:
    if explicit_target_agent is not None:
        return explicit_target_agent, "Explicit agent target provided by client."

    normalized_execution_target = normalize_execution_target(execution_target)
    governance = domain.services.workspace.get_governance_view(workspace)
    abstract_key = domain.services.capability.get_abstract_capability_key(capability) if capability is not None else ""
    concrete_capability_id = str(getattr(capability, "capability_id", "") or "") if capability is not None else ""
    effective_preferences = domain.services.workspace.get_effective_agent_routing_preferences(
        workspace,
        capability_ref=capability_ref,
        abstract_capability_key=abstract_key,
        concrete_capability_id=concrete_capability_id,
    )
    merged_preferences = _merge_routing_preferences(effective_preferences, routing_preferences or {})
    preferred_agent_ids = list(merged_preferences.get("preferred_agent_ids") or [])
    preferred_agent_types = list(merged_preferences.get("preferred_agent_types") or [])
    agent_routing_policy = str(merged_preferences.get("agent_routing_policy") or governance.get("agent_routing_policy") or "balanced")
    preference_source = str(merged_preferences.get("source") or "workspace_default")
    requesting_client_id = getattr(requesting_client, "id", None)

    if capability is not None and str(getattr(capability, "provider_type", "") or "") == "agent":
        is_exact_capability_id = str(getattr(capability, "capability_id", "") or "") == str(capability_ref or "").strip()
        provider_agent = domain.services.agent.get_by_agent_id(str(getattr(capability, "provider_ref", "") or ""))
        if is_exact_capability_id and provider_agent is not None and domain.services.agent.is_bound_to_workspace(agent_id=provider_agent.agent_id, workspace_id=workspace.workspace_id):
            if getattr(provider_agent, "status", "") == "online":
                return provider_agent, "Resolved from capability provider within workspace scope."
            if normalized_execution_target == EXECUTION_TARGET_SPECIFIC_AGENT:
                return None, f"Capability provider agent is offline: {provider_agent.agent_id}"
            if normalized_execution_target == EXECUTION_TARGET_WORKSPACE_ANY_AGENT:
                return None, f"Capability provider agent is offline: {provider_agent.agent_id}"
            if normalized_execution_target == EXECUTION_TARGET_PREFER_AGENT_FALLBACK_CORE:
                return None, f"Capability provider agent is offline and no core fallback is available: {provider_agent.agent_id}"

    if normalized_execution_target not in {
        EXECUTION_TARGET_SPECIFIC_AGENT,
        EXECUTION_TARGET_WORKSPACE_ANY_AGENT,
        EXECUTION_TARGET_PREFER_AGENT_FALLBACK_CORE,
    }:
        return None, ""

    allowed_agent_ids = []
    if capability is not None:
        allowed_agent_ids = domain.services.capability.list_agents_for_capability_reference(
            capability_ref=abstract_key or capability_ref,
            workspace_id=workspace.id,
        )

    selected = domain.services.agent.select_workspace_agent(
        workspace_id=workspace.id,
        requesting_client_id=requesting_client_id,
        preferred_agent_ids=preferred_agent_ids,
        preferred_agent_types=preferred_agent_types,
        routing_policy=agent_routing_policy,
        allowed_agent_ids=allowed_agent_ids,
    )
    if selected is not None:
        return selected, f"Resolved by workspace agent routing policy ({agent_routing_policy}) via {preference_source}."
    if normalized_execution_target == EXECUTION_TARGET_PREFER_AGENT_FALLBACK_CORE:
        return None, "No workspace agent available; fallback to core_only."
    return None, f"No online agent is available for workspace: {workspace.workspace_id}"


def _merge_routing_preferences(*preferences: dict[str, Any]) -> dict[str, Any]:
    merged = {
        "preferred_agent_ids": [],
        "preferred_agent_types": [],
        "agent_routing_policy": "balanced",
        "source": "workspace_default",
    }
    for item in preferences:
        if not isinstance(item, dict):
            continue
        if item.get("preferred_agent_ids"):
            merged["preferred_agent_ids"] = list(item.get("preferred_agent_ids") or [])
        if item.get("preferred_agent_types"):
            merged["preferred_agent_types"] = list(item.get("preferred_agent_types") or [])
        if item.get("agent_routing_policy"):
            merged["agent_routing_policy"] = str(item.get("agent_routing_policy") or "balanced")
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
    workspace_row = _get_workspace_by_row_id(domain, session_row.workspace_id)
    client_row = domain.services.client.get_by_id(session_row.client_id)
    return session_row, thread_row, workspace_row, client_row, "", ""


def _bind_runtime_session(gateway, *, session_id: str, source, metadata: dict | None = None) -> str:
    return gateway._session_manager.bind_runtime_session(
        source,
        session_id=session_id,
        metadata=dict(metadata or {}),
    )


def _capability_requires_approval(capability) -> bool:
    if capability is None:
        return False
    if bool(getattr(capability, "requires_confirmation", False)):
        return True
    return str(getattr(capability, "risk_level", "") or "").strip().lower() in _APPROVAL_RISK_LEVELS


def _operation_event_payload(operation, *, thread_id: str, detail: str = "", phase: str = "", call_id: str = "", result: dict | None = None, error: dict | None = None) -> dict:
    metadata = dict(getattr(operation, "meta", {}) or {})
    payload = {
        "thread_id": thread_id,
        "operation_id": operation.operation_id,
        "title": operation.title,
        "operation_type": operation.operation_type,
        "execution_target": normalize_execution_target(operation.execution_target),
        "target_agent_id": str(metadata.get("target_agent_key") or ""),
        "capability_id": str(metadata.get("capability_id") or ""),
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


async def _dispatch_specific_agent_operation(gateway, domain, *, operation, thread, workspace, requesting_client) -> tuple[object, str]:
    metadata = dict(getattr(operation, "meta", {}) or {})
    target_agent_key = str(metadata.get("target_agent_key") or "")
    capability_key = str(metadata.get("capability_id") or "")
    if not target_agent_key or not capability_key:
        return operation, ""

    target_agent = domain.services.agent.get_by_agent_id(target_agent_key)
    if target_agent is None:
        error = {"code": "agent_not_found", "message": f"未知 agent: {target_agent_key}"}
        operation = domain.services.operation.update_status(
            operation_id=operation.id,
            status="failed",
            result_summary=error["message"],
            metadata={"error": error},
        ) or operation
        await _publish_operation_update(gateway, operation=operation, thread_id=thread.thread_id, detail=error["message"], error=error)
        return operation, ""

    capability = domain.services.capability.get_by_capability_id(capability_key)
    if capability is None:
        error = {"code": "capability_not_found", "message": f"未知 capability: {capability_key}"}
        operation = domain.services.operation.update_status(
            operation_id=operation.id,
            status="failed",
            result_summary=error["message"],
            metadata={"error": error},
        ) or operation
        await _publish_operation_update(gateway, operation=operation, thread_id=thread.thread_id, detail=error["message"], error=error)
        return operation, ""

    call = domain.services.operation_call.create_call(
        operation_id=operation.id,
        capability_id=capability.id,
        target_agent_id=target_agent.id,
        status="queued",
        arguments=metadata.get("arguments") if isinstance(metadata.get("arguments"), dict) else {},
    )
    dispatched = await gateway.dispatch_agent_call(
        agent_id=target_agent.agent_id,
        payload=build_capability_call_request(
            agent_id=target_agent.agent_id,
            message_id=f"dispatch-{call.call_id}",
            operation_id=operation.operation_id,
            call_id=call.call_id,
            workspace_id=workspace.workspace_id,
            capability_id=capability_key,
            arguments=dict(metadata.get("arguments") or {}),
            timeout_seconds=60,
            audit_context={
                "principal_id": "self",
                "requested_by_client_id": getattr(requesting_client, "client_id", ""),
                "operation_type": operation.operation_type,
            },
        ),
    )
    if not dispatched:
        error = {"code": "agent_offline", "message": f"Agent is offline: {target_agent.agent_id}"}
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
        detail="已通过 Agent 下发执行请求",
    )
    return operation, call.call_id


def build_client_router(gateway) -> APIRouter:
    router = APIRouter(prefix="/client", tags=["client"])

    @router.get("/workspaces", response_model=list[ClientWorkspaceResponse])
    async def list_workspaces(request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        return [_workspace_response(workspace) for workspace in domain.services.workspace.list_workspaces()]

    @router.get("/workspaces/{workspace_id}/agents", response_model=list[ClientAvailableAgentResponse])
    async def list_workspace_agents(workspace_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        workspace = domain.services.workspace.get_by_workspace_id(workspace_id)
        if workspace is None:
            gateway._raise_http_error(status_code=404, code="workspace_not_found", message=f"未知 workspace: {workspace_id}")
        rows = []
        for agent in domain.services.agent.list_agents():
            if agent.status != "online":
                continue
            bindings = domain.services.agent.list_workspace_bindings(agent.agent_id)
            if not any(binding.enabled and binding.workspace_id == workspace.id for binding in bindings):
                continue
            owner_client = domain.services.client.get_by_id(agent.owner_client_id) if getattr(agent, "owner_client_id", None) else None
            rows.append(
                ClientAvailableAgentResponse(
                    agent_id=agent.agent_id,
                    display_name=agent.display_name,
                    agent_type=agent.agent_type,
                    status=agent.status,
                    transport_profile=agent.transport_profile,
                    owner_client_id=getattr(owner_client, "client_id", ""),
                    workspace_ids=[workspace_id],
                )
            )
        rows.sort(key=lambda item: (0 if item.owner_client_id else 1, item.display_name.lower(), item.agent_id))
        return rows

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
        workspace = domain.services.workspace.get_by_workspace_id(payload.workspace_id)
        if workspace is None:
            gateway._raise_http_error(
                status_code=404,
                code="workspace_not_found",
                message=f"未知 workspace: {payload.workspace_id}",
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
            workspace_id=workspace.id,
            title=payload.title,
            pinned_procedure_id=payload.pinned_procedure_id,
        )
        return _thread_response(thread, payload.workspace_id)

    @router.get("/threads/{thread_id}", response_model=ClientThreadResponse)
    async def get_thread(thread_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = domain.services.thread.get_by_thread_id(thread_id)
        if thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"未知 thread: {thread_id}")
        workspace = _get_workspace_by_row_id(domain, thread.workspace_id)
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
        workspace = _require_thread_workspace(gateway, domain, thread=thread, workspace_id=payload.workspace_id)
        governance = domain.services.workspace.get_governance_view(workspace)
        client = domain.services.client.ensure_client(
            client_id=payload.client_id,
            principal_id=domain.principal.id,
            client_type=payload.client_type,
            display_name=payload.display_name or payload.client_id,
        )
        session = domain.services.session.create_session(
            thread_id=thread.id,
            client_id=client.id,
            workspace_id=workspace.id,
        )
        return ClientSessionResponse(
            session_id=session.session_id,
            thread_id=payload.thread_id,
            workspace_id=payload.workspace_id,
            client_id=payload.client_id,
            status=session.status,
        )

    @router.post("/messages", response_model=ClientMessageResponse)
    async def create_message(http_request: Request, payload: ClientMessageCreateRequest):
        gateway._require_http_auth(http_request)
        domain = gateway._require_core_domain()
        thread = domain.services.thread.get_by_thread_id(payload.thread_id)
        if thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"未知 thread: {payload.thread_id}")
        workspace = _require_thread_workspace(gateway, domain, thread=thread, workspace_id=payload.workspace_id)
        governance = domain.services.workspace.get_governance_view(workspace)
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
        if session_record is not None and session_record.workspace_id != workspace.id:
            gateway._raise_http_error(
                status_code=400,
                code="session_workspace_mismatch",
                message=f"session {payload.session_id} 不属于 workspace: {payload.workspace_id}",
            )
        if session_record is None:
            session_record = domain.services.session.create_session(
                thread_id=thread.id,
                client_id=client.id,
                workspace_id=workspace.id,
            )
        source = make_source(SourceKind.WEB.value, payload.client_id, client_id=payload.client_id)
        _bind_runtime_session(
            gateway,
            session_id=session_record.session_id,
            source=source,
            metadata={
                "thread_id": payload.thread_id,
                "workspace_id": payload.workspace_id,
                "client_id": payload.client_id,
            },
        )
        inbound_metadata = {
            "thread_id": payload.thread_id,
            "message_id": message.message_id if False else "",
            "workspace_id": payload.workspace_id,
            "workspace_title": workspace.title,
            "workspace_base_mode": workspace.base_mode,
            "workspace_prompt_overlay": governance["prompt_overlay"],
            "workspace_default_execution_target": governance["default_execution_target"],
            "workspace_preferred_source_profiles": governance["preferred_source_profiles"],
            "workspace_memory_ranking_policy": governance["memory_ranking_policy"],
        }
        inbound_metadata.update(dict(payload.metadata or {}))
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
            meta={
                "workspace_id": payload.workspace_id,
                "workspace_base_mode": workspace.base_mode,
                "workspace_prompt_overlay": governance["prompt_overlay"],
                "workspace_default_execution_target": governance["default_execution_target"],
                "workspace_preferred_source_profiles": governance["preferred_source_profiles"],
                "workspace_memory_ranking_policy": governance["memory_ranking_policy"],
                **dict(payload.metadata or {}),
                **({"client_message_id": payload.client_message_id} if payload.client_message_id else {}),
                "preferred_mode": payload.preferred_mode or workspace.base_mode,
                **({"input_options": dict(payload.options)} if payload.options else {}),
                **({"pinned_procedure_id": inbound_metadata["pinned_procedure_id"]} if inbound_metadata.get("pinned_procedure_id") else {}),
            },
        )
        inbound_metadata["message_id"] = message.message_id
        await gateway.publish_client_thread_event(
            payload.thread_id,
            event_type="message.created",
            payload={
                "thread_id": payload.thread_id,
                "session_id": session_record.session_id,
                "message": _message_response(
                    message,
                    thread_id=payload.thread_id,
                    workspace_id=payload.workspace_id,
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
            workspace_id=payload.workspace_id,
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
        workspace = _get_workspace_by_row_id(domain, thread.workspace_id)
        messages = domain.services.message.list_messages_for_thread(thread.id)
        session_lookup = {}
        client_lookup = {}
        results: list[ClientMessageResponse] = []
        for item in messages:
            session_id = ""
            client_id = ""
            if item.session_id is not None:
                session_row = session_lookup.get(item.session_id)
                if session_row is None:
                    session_row = domain.services.session.get_by_id(item.session_id)
                    session_lookup[item.session_id] = session_row
                session_id = getattr(session_row, "session_id", "")
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
                    workspace_id=getattr(workspace, "workspace_id", ""),
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
        workspace = _require_thread_workspace(gateway, domain, thread=thread, workspace_id=payload.workspace_id)
        procedure, procedure_profile = _resolve_procedure_execution_profile(domain, payload=payload)
        preferred_capability_ref = str(procedure_profile.get("preferred_capability_ref") or "").strip()
        requested_execution_target = str(payload.execution_target or "").strip()
        execution_target_from_workspace_default = not requested_execution_target
        execution_target = normalize_execution_target(
            requested_execution_target
            or str(getattr(procedure, "default_execution_target", "") or "").strip()
            or workspace.default_execution_target,
            fallback=normalize_execution_target(workspace.default_execution_target),
        )
        implicit_specific_agent_ok = execution_target_from_workspace_default or procedure is not None
        if requires_specific_agent(execution_target) and not payload.target_agent_id and not implicit_specific_agent_ok:
            gateway._raise_http_error(
                status_code=400,
                code="target_agent_required",
                message="execution_target=specific_agent 时 target_agent_id 为必填字段",
            )
        if payload.target_agent_id and execution_target != EXECUTION_TARGET_SPECIFIC_AGENT:
            gateway._raise_http_error(
                status_code=400,
                code="ambiguous_execution_target",
                message="仅当 execution_target=specific_agent 时才允许传入 target_agent_id",
            )
        target_agent = None
        capability = None
        if payload.target_agent_id:
            target_agent = domain.services.agent.get_by_agent_id(payload.target_agent_id)
            if target_agent is None:
                gateway._raise_http_error(
                    status_code=404,
                    code="agent_not_found",
                    message=f"未知 agent: {payload.target_agent_id}",
                )
            if not domain.services.agent.is_bound_to_workspace(
                agent_id=payload.target_agent_id,
                workspace_id=payload.workspace_id,
            ):
                gateway._raise_http_error(
                    status_code=400,
                    code="agent_workspace_mismatch",
                    message=f"agent {payload.target_agent_id} 不属于 workspace: {payload.workspace_id}",
                )
        capability_ref = str(payload.capability_id or "").strip() or preferred_capability_ref
        if capability_ref:
            capability = domain.services.capability.resolve_capability_reference(
                capability_ref=capability_ref,
                workspace_id=workspace.id,
                target_agent_id=payload.target_agent_id,
            )
            if capability is None:
                gateway._raise_http_error(
                    status_code=404,
                    code="capability_not_found",
                    message=f"未知 capability 或抽象能力名: {capability_ref}",
                )
            if target_agent is not None and capability.provider_ref != target_agent.agent_id:
                gateway._raise_http_error(
                    status_code=400,
                    code="capability_agent_mismatch",
                    message=f"capability {capability_ref} 不属于 agent: {payload.target_agent_id}",
                )
            if not domain.services.capability.is_available_in_workspace(
                capability_id=capability.capability_id,
                workspace_id=workspace.id,
            ):
                gateway._raise_http_error(
                    status_code=400,
                    code="capability_workspace_mismatch",
                    message=f"capability {capability_ref} 不属于 workspace: {payload.workspace_id}",
                )
            if not domain.services.workspace.capability_allowed(workspace, capability_ref) and not domain.services.workspace.capability_allowed(
                workspace,
                domain.services.capability.get_abstract_capability_key(capability),
            ):
                gateway._raise_http_error(
                    status_code=403,
                    code="capability_not_allowed_in_workspace",
                    message=f"capability {capability_ref} 不在 workspace {payload.workspace_id} 的允许列表内",
                )
        governance = domain.services.workspace.get_governance_view(workspace)
        if (
            str(payload.operation_type or "").strip() == "capability_call"
            and governance["capability_policy"] == "allowlist"
            and not payload.capability_id
        ):
            gateway._raise_http_error(
                status_code=400,
                code="capability_required_by_workspace_policy",
                message=f"workspace {payload.workspace_id} 启用了 capability allowlist，capability_call 必须显式提供 capability_id",
            )
        requesting_client = _resolve_requesting_client(
            domain,
            client_id=payload.client_id,
            session_id=payload.session_id,
        )
        routing_reason = ""
        resolved_execution_target = execution_target
        if target_agent is None and execution_target in {
            EXECUTION_TARGET_SPECIFIC_AGENT,
            EXECUTION_TARGET_WORKSPACE_ANY_AGENT,
            EXECUTION_TARGET_PREFER_AGENT_FALLBACK_CORE,
        }:
            target_agent, routing_reason = _resolve_workspace_target_agent(
                domain,
                workspace=workspace,
                capability=capability,
                capability_ref=capability_ref,
                execution_target=execution_target,
                requesting_client=requesting_client,
                routing_preferences=(
                    {
                        "preferred_agent_ids": procedure_profile.get("preferred_agent_ids") or [],
                        "preferred_agent_types": procedure_profile.get("preferred_agent_types") or [],
                        "agent_routing_policy": procedure_profile.get("agent_routing_policy") or "balanced",
                        "source": f"procedure:{procedure_profile.get('procedure_id') or 'unknown'}",
                    }
                    if procedure is not None
                    else None
                ),
            )
            if target_agent is None:
                if execution_target == EXECUTION_TARGET_PREFER_AGENT_FALLBACK_CORE:
                    if capability is not None and str(getattr(capability, "provider_type", "") or "") == "agent":
                        gateway._raise_http_error(
                            status_code=409,
                            code="core_fallback_unavailable",
                            message=routing_reason or "Agent capability 当前无可用核心降级路径",
                        )
                    resolved_execution_target = "core_only"
                elif execution_target == EXECUTION_TARGET_WORKSPACE_ANY_AGENT or execution_target_from_workspace_default:
                    gateway._raise_http_error(
                        status_code=409,
                        code="workspace_agent_unavailable",
                        message=routing_reason or f"No online agent is available for workspace: {workspace.workspace_id}",
                    )
        if capability is not None and target_agent is not None and capability.provider_ref != target_agent.agent_id:
            capability = domain.services.capability.resolve_capability_reference(
                capability_ref=capability_ref,
                workspace_id=workspace.id,
                target_agent_id=target_agent.agent_id,
            )
            if capability is None:
                gateway._raise_http_error(
                    status_code=409,
                    code="capability_resolution_failed",
                    message=f"无法将 capability {capability_ref} 解析到 agent: {target_agent.agent_id}",
                )

        approval_required = bool(target_agent is not None and capability is not None and _capability_requires_approval(capability))
        operation = domain.services.operation.create_operation(
            thread_id=thread.id,
            workspace_id=workspace.id,
            operation_type=payload.operation_type,
            execution_target=resolved_execution_target,
            title=payload.title,
            target_agent_id=getattr(target_agent, "id", None),
            requested_by_client_id=requesting_client.id,
            status="waiting_approval" if approval_required else "queued",
            metadata={
                "target_agent_key": getattr(target_agent, "agent_id", "") or payload.target_agent_id or "",
                "capability_id": getattr(capability, "capability_id", "") or capability_ref,
                "capability_ref": capability_ref,
                "abstract_capability_key": domain.services.capability.get_abstract_capability_key(capability) if capability is not None else "",
                "arguments": dict(payload.arguments or {}),
                "approval_required": approval_required,
                "routing_reason": routing_reason,
                **({"procedure_id": procedure_profile.get("procedure_id", "")} if procedure is not None else {}),
                **({"procedure": procedure_profile.get("procedure_snapshot", {})} if procedure is not None else {}),
            },
        )
        if approval_required:
            approval = domain.services.approval.create_approval(
                operation_id=operation.id,
                approval_type="operation_execution",
                risk_level=str(getattr(capability, "risk_level", "write") or "write"),
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
        if target_agent is not None and capability is not None:
            operation, _ = await _dispatch_specific_agent_operation(
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
                    operation, _ = await _dispatch_specific_agent_operation(
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
        thread_id = str(websocket.query_params.get("thread_id") or "").strip()
        if not thread_id:
            await gateway._send_ws_error_and_close(
                websocket,
                code="thread_id_required",
                message="thread_id 为必填字段",
                close_code=4400,
            )
            return
        await websocket.accept()
        await gateway.client_ws_manager.connect(thread_id, websocket)
        dependencies = getattr(gateway, "_dependencies", None)
        domain = getattr(dependencies, "core_domain", None)
        connected = await gateway._safe_send_json(websocket, gateway.client_ws_manager.connection_payload(thread_id))
        if not connected:
            await gateway.client_ws_manager.disconnect(thread_id, websocket)
            return
        try:
            while True:
                try:
                    command = ClientWsCommand.model_validate(await websocket.receive_json())
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
                if domain is not None:
                    session_row, _, workspace_row, client_row, session_error_code, session_error_message = _resolve_client_session_for_thread(
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
                    _bind_runtime_session(
                        gateway,
                        session_id=command_session_id,
                        source=source,
                        metadata={
                            "thread_id": thread_id,
                            "workspace_id": getattr(workspace_row, "workspace_id", ""),
                            "client_id": getattr(client_row, "client_id", "") or str(command.client_id or "").strip(),
                            "session_row_id": str(getattr(session_row, "id", "") or ""),
                        },
                    )
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
