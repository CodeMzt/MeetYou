from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, Response
from starlette.responses import JSONResponse

from core.credential_transport import CredentialTransportError, decrypt_json_payload
from core.io_protocol import EventTarget, EventType, InboundEvent, SourceKind, TargetKind, make_source
from core.public_contract import EXECUTION_TARGET_ENDPOINT, EXECUTION_TARGETS
from core.services.tool_router_service import ToolRouterError
from gateway.models import (
    AckPayload,
    AckResponse,
    RuntimeActiveWorkspacePatchRequest,
    RuntimeApprovalDecisionRequest,
    RuntimeApprovalResponse,
    RuntimeAttachmentCompleteRequest,
    RuntimeAttachmentDownloadTicketResponse,
    RuntimeAttachmentResponse,
    RuntimeAttachmentUploadResult,
    RuntimeAttachmentUploadTicketRequest,
    RuntimeAttachmentUploadTicketResponse,
    RuntimeConfirmResponseRequest,
    RuntimeConfirmResponseResult,
    RuntimeDanxiActionResponse,
    RuntimeDanxiListResponse,
    RuntimeDanxiMessageTargetResponse,
    RuntimeDanxiPostResponse,
    RuntimeDanxiReplyCreateRequest,
    RuntimeDanxiReplyUpdateRequest,
    RuntimeDanxiSearchResponse,
    RuntimeDanxiSessionLoginRequest,
    RuntimeDanxiSessionResponse,
    RuntimeDanxiSummaryResponse,
    RuntimeDanxiWebvpnCookiePatchRequest,
    RuntimeDanxiProfileResponse,
    RuntimeHumanInputResponseRequest,
    RuntimeHumanInputResponseResult,
    RuntimeMessageCreateRequest,
    RuntimeMessageResponse,
    RuntimeOperationCreateRequest,
    RuntimeOperationResponse,
    RuntimeDefaultThreadRequest,
    RuntimeSessionCreateRequest,
    RuntimeSessionResponse,
    RuntimeThreadCreateRequest,
    RuntimeThreadResponse,
    RuntimeWorkspaceResponse,
    ContextPoolQueryResponse,
    EndpointAvailableResponse,
)
from tools.danxi_tools import DanxiError, get_shared_danxi_tools


_HTTP_SCHEMA = "meetyou.http.v1"
_SOURCE_KIND_ALIASES = {
    "browser": SourceKind.WEB.value,
    "desktop": SourceKind.WEB.value,
    "desktop_ui": SourceKind.WEB.value,
    "electron": SourceKind.WEB.value,
    "electron_ui": SourceKind.WEB.value,
    "edge": SourceKind.WEB.value,
    "edge_ui": SourceKind.WEB.value,
    "web": SourceKind.WEB.value,
    "web_ui": SourceKind.WEB.value,
    "feishu": SourceKind.FEISHU.value,
    "feishu_ui": SourceKind.FEISHU.value,
    "lark": SourceKind.FEISHU.value,
    "wechat": SourceKind.WECHAT.value,
    "wechat_ui": SourceKind.WECHAT.value,
    "meetwechat": SourceKind.WECHAT.value,
    "meetwechat_ui": SourceKind.WECHAT.value,
    "cli": SourceKind.CLI.value,
}
_SOURCE_TO_TARGET_KIND = {
    SourceKind.WEB.value: TargetKind.WEB.value,
    SourceKind.FEISHU.value: TargetKind.FEISHU.value,
    SourceKind.WECHAT.value: TargetKind.WECHAT.value,
    SourceKind.CLI.value: TargetKind.CLI.value,
}


def _normalize_runtime_source_kind(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    if "." in normalized:
        normalized = normalized.split(".", 1)[0]
    return _SOURCE_KIND_ALIASES.get(normalized, "")


def _resolve_runtime_source_kind(*, endpoint_id: str = "", endpoint_type: str = "", metadata: dict | None = None) -> str:
    meta = dict(metadata or {})
    for candidate in (
        meta.get("source"),
        meta.get("transport"),
        meta.get("provider_type"),
        endpoint_type,
        endpoint_id,
    ):
        source_kind = _normalize_runtime_source_kind(candidate)
        if source_kind:
            return source_kind
    return SourceKind.WEB.value


def _runtime_target_for_source(source_kind: str, source_id: str, metadata: dict | None = None) -> EventTarget:
    return EventTarget(
        kind=_SOURCE_TO_TARGET_KIND.get(str(source_kind or "").strip().lower(), TargetKind.WEB.value),
        id=str(source_id or "").strip(),
        metadata=dict(metadata or {}),
    )


def _workspace_response(workspace) -> RuntimeWorkspaceResponse:
    meta = dict(getattr(workspace, "meta", {}) or {})
    return RuntimeWorkspaceResponse(
        workspace_id=workspace.workspace_id,
        title=workspace.title,
        status=workspace.status,
        base_mode=workspace.base_mode,
        description=str(meta.get("description") or ""),
        prompt_overlay=workspace.prompt_overlay,
        default_execution_target=workspace.default_execution_target,
        tool_policy=str(meta.get("tool_policy") or "allow_all"),
        allowed_tool_ids=list(meta.get("allowed_tool_ids") or []),
        preferred_target_endpoint_ids=list(meta.get("preferred_target_endpoint_ids") or []),
        preferred_endpoint_provider_types=list(meta.get("preferred_endpoint_provider_types") or []),
        preferred_source_profiles=list(meta.get("preferred_source_profiles") or []),
        tool_target_routing_policy=str(meta.get("tool_target_routing_policy") or "balanced"),
        memory_ranking_policy=str(meta.get("memory_ranking_policy") or "workspace_first"),
        tool_routing_overrides=dict(meta.get("tool_routing_overrides") or {}),
    )


def _thread_response(thread, workspace_id: str) -> RuntimeThreadResponse:
    return RuntimeThreadResponse(
        thread_id=thread.thread_id,
        home_workspace_id=workspace_id,
        workspace_id=workspace_id,
        title=thread.title,
        status=thread.status,
        summary=thread.summary,
    )


def _message_response(
    message,
    *,
    thread_id: str,
    workspace_id: str,
    session_id: str = "",
    idempotent_replay: bool = False,
) -> RuntimeMessageResponse:
    return RuntimeMessageResponse(
        message_id=message.message_id,
        thread_id=thread_id,
        session_id=session_id,
        active_workspace_id=workspace_id,
        workspace_id=workspace_id,
        endpoint_id=str(getattr(message, "origin_endpoint_id", "") or ""),
        role=message.role,
        content=message.content,
        status=message.status,
        channel=message.channel,
        created_at=message.created_at.isoformat() if getattr(message, "created_at", None) is not None else "",
        idempotent_replay=bool(idempotent_replay),
    )


def _operation_response(operation, *, thread_id: str = "", workspace_id: str = "") -> RuntimeOperationResponse:
    meta = dict(getattr(operation, "meta", {}) or {})
    execution_target = str(getattr(operation, "execution_target", "") or "").strip()
    target_endpoint_id = str(getattr(operation, "execution_target_id", "") or "").strip()
    if execution_target not in EXECUTION_TARGETS and target_endpoint_id:
        execution_target = EXECUTION_TARGET_ENDPOINT
    return RuntimeOperationResponse(
        operation_id=operation.operation_id,
        thread_id=thread_id,
        workspace_id=workspace_id,
        title=operation.title,
        operation_type=operation.operation_type,
        execution_target=execution_target,
        target_endpoint_id=target_endpoint_id,
        tool_key=str(meta.get("tool_key") or ""),
        tool_id=str(meta.get("tool_id") or meta.get("capability_id") or ""),
        capability_id=str(meta.get("capability_id") or ""),
        status=operation.status,
        approval_id="",
        approval_status="",
        approval_required=False,
        routing_reason=str(meta.get("routing_reason") or ""),
    )


def _find_workspace(domain, workspace_id: str):
    normalized = str(workspace_id or "").strip() or "personal"
    workspace = domain.services.workspace.get_by_workspace_id(normalized)
    if workspace is None:
        raise KeyError(normalized)
    return workspace


def _find_thread(domain, thread_id: str):
    thread = domain.services.thread.get_by_thread_id(str(thread_id or "").strip())
    if thread is None:
        raise KeyError(thread_id)
    return thread


def _find_endpoint(domain, endpoint_id: str = ""):
    normalized = str(endpoint_id or "").strip()
    if not normalized:
        return None
    return domain.services.endpoint.get_by_endpoint_id(normalized)


def _request_actor_row_id(domain):
    principal_key = str(getattr(domain.principal, "principal_key", "") or "self").strip() or "self"
    actor_id = f"user:{principal_key}"
    actor = domain.services.actor.get_by_actor_id(actor_id)
    if actor is None:
        actor = domain.services.actor.ensure_actor(
            actor_id=actor_id,
            actor_type="user",
            owner_user_id=principal_key,
            display_name=str(getattr(domain.principal, "display_name", "") or principal_key),
            permission_profile_id="profile.default_user",
            metadata={"principal_key": principal_key},
        )
    return getattr(actor, "id", None)


def _raise_tool_router_error(gateway, exc: ToolRouterError) -> None:
    status_code = 503 if exc.retryable else 400
    if exc.code in {"workspace_not_found", "execution_target_not_found"}:
        status_code = 404
    elif exc.code == "tool_confirmation_required":
        status_code = 409
    elif exc.code == "endpoint_tool_timeout":
        status_code = 504
    elif exc.code in {
        "endpoint_transport_unavailable",
        "external_executor_unavailable",
        "target_endpoint_unavailable",
        "execution_target_unavailable",
    }:
        status_code = 503
    gateway._raise_http_error(
        status_code=status_code,
        code=exc.code,
        category="dependency" if status_code in {503, 504} else "validation",
        message=exc.message,
        retryable=exc.retryable,
        details=exc.details,
    )


def _raise_runtime_dependency_error(gateway, exc: Exception, *, code: str = "runtime_dependency_error") -> None:
    gateway._raise_http_error(
        status_code=400,
        code=code,
        category="dependency",
        message=str(exc),
        retryable=False,
    )


def _public_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _attachment_record_response(record: dict[str, Any]) -> RuntimeAttachmentResponse:
    return RuntimeAttachmentResponse(**record)


def _decrypt_danxi_credentials(gateway, sealed_payload: dict[str, Any] | None, *, purpose: str) -> dict[str, Any]:
    if not sealed_payload:
        return {}
    try:
        payload = decrypt_json_payload(dict(sealed_payload), purpose=purpose)
    except CredentialTransportError as exc:
        gateway._raise_http_error(
            status_code=400,
            code="danxi_credentials_invalid",
            category="validation",
            message=getattr(exc, "message", str(exc)),
            retryable=False,
        )
    if not isinstance(payload, dict):
        gateway._raise_http_error(
            status_code=400,
            code="danxi_credentials_invalid",
            category="validation",
            message="Danxi 凭据载荷格式无效。",
            retryable=False,
        )
    return dict(payload)


async def _call_danxi(gateway, fn, *args, **kwargs):
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except DanxiError as exc:
        _raise_runtime_dependency_error(gateway, exc, code="danxi_runtime_error")


def build_runtime_router(gateway) -> APIRouter:
    router = APIRouter(prefix="/runtime", tags=["runtime-v4-http"])

    @router.get("/workspaces", response_model=list[RuntimeWorkspaceResponse])
    async def list_workspaces(request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        return [_workspace_response(workspace) for workspace in domain.services.workspace.list_workspaces()]

    @router.get("/workspaces/{workspace_id}/clients")
    async def legacy_list_workspace_clients(workspace_id: str, request: Request, include_tools: bool = True):
        del workspace_id, include_tools
        gateway._require_http_auth(request)
        return JSONResponse(
            status_code=410,
            content={
                "schema": _HTTP_SCHEMA,
                "kind": "error",
                "error": {
                    "code": "legacy_http_path_removed",
                    "message": "Workspace clients are removed in V4. Use workspace endpoints.",
                    "details": {
                        "legacy_path": "/runtime/workspaces/{workspace_id}/clients",
                        "replacement_path": "/runtime/workspaces/{workspace_id}/endpoints",
                    },
                },
            },
        )

    @router.get("/workspaces/{workspace_id}/endpoints", response_model=list[EndpointAvailableResponse])
    async def list_workspace_endpoints(workspace_id: str, request: Request, include_tools: bool = True):
        del include_tools
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        endpoints = []
        connected = await gateway.endpoint_ws_manager.connected_endpoint_ids()
        for endpoint in domain.services.endpoint.list_all():
            scope = [str(item) for item in (getattr(endpoint, "workspace_scope", []) or [])]
            if workspace_id not in scope and "*" not in scope:
                continue
            meta = dict(getattr(endpoint, "meta", {}) or {})
            is_connected = endpoint.endpoint_id in connected
            endpoints.append(
                EndpointAvailableResponse(
                    endpoint_id=endpoint.endpoint_id,
                    display_name=str(meta.get("display_name") or endpoint.endpoint_id),
                    endpoint_type=endpoint.endpoint_type,
                    provider_type=endpoint.provider_type,
                    status="online" if is_connected else "offline",
                    workspace_ids=scope,
                    transport_profile=endpoint.transport_type,
                    available_tools=[],
                    executable_tools=[
                        capability.tool_key
                        for capability in domain.services.endpoint_capability.list_for_endpoint(endpoint_row_id=endpoint.id)
                        if getattr(capability, "enabled", True)
                    ],
                )
            )
        return endpoints

    @router.get("/threads", response_model=list[RuntimeThreadResponse])
    async def list_threads(request: Request, workspace_id: str = "", limit: int = 50, cursor: str = ""):
        del cursor
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        workspace = _find_workspace(domain, workspace_id) if str(workspace_id or "").strip() else None
        rows = domain.services.thread.list_threads(
            principal_id=domain.principal.id,
            workspace_id=getattr(workspace, "id", None),
            limit=limit,
        )
        workspace_cache: dict[Any, str] = {}
        responses: list[RuntimeThreadResponse] = []
        for thread in rows:
            row_workspace_id = getattr(thread, "home_workspace_id", None) or getattr(thread, "workspace_id", None)
            if row_workspace_id not in workspace_cache:
                row_workspace = domain.services.workspace.get_by_id(row_workspace_id)
                workspace_cache[row_workspace_id] = str(getattr(row_workspace, "workspace_id", "") or "")
            responses.append(_thread_response(thread, workspace_cache[row_workspace_id]))
        return responses

    @router.post("/threads/default", response_model=RuntimeThreadResponse)
    async def ensure_default_thread(payload: RuntimeDefaultThreadRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        workspace = _find_workspace(domain, payload.workspace_id)
        thread = domain.services.thread.ensure_default_thread(
            principal_id=domain.principal.id,
            workspace_id=workspace.id,
            default_key=payload.default_key,
            title=payload.title,
        )
        return _thread_response(thread, workspace.workspace_id)

    @router.post("/threads", response_model=RuntimeThreadResponse)
    async def create_thread(payload: RuntimeThreadCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        workspace = _find_workspace(domain, payload.resolved_home_workspace_id)
        thread = domain.services.thread.create_thread(
            principal_id=domain.principal.id,
            workspace_id=workspace.id,
            title=payload.title,
        )
        return _thread_response(thread, workspace.workspace_id)

    @router.get("/threads/{thread_id}", response_model=RuntimeThreadResponse)
    async def get_thread(thread_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = _find_thread(domain, thread_id)
        workspace = domain.services.workspace.get_by_id(getattr(thread, "home_workspace_id", None) or getattr(thread, "workspace_id", None))
        return _thread_response(thread, getattr(workspace, "workspace_id", ""))

    @router.post("/sessions", response_model=RuntimeSessionResponse)
    async def create_session(payload: RuntimeSessionCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = _find_thread(domain, payload.thread_id)
        workspace = _find_workspace(domain, payload.resolved_active_workspace_id or getattr(thread, "workspace_id", ""))
        endpoint = _find_endpoint(domain, payload.endpoint_id)
        session = domain.services.session.create_session(
            thread_id=thread.id,
            origin_endpoint_id=getattr(endpoint, "id", None),
            workspace_id=workspace.id,
        )
        source_id = str(getattr(endpoint, "endpoint_id", "") or payload.endpoint_id or "runtime.endpoint").strip()
        source_kind = _resolve_runtime_source_kind(
            endpoint_id=source_id,
            endpoint_type=payload.endpoint_type,
            metadata={"provider_type": getattr(endpoint, "provider_type", "") if endpoint is not None else ""},
        )
        gateway._session_manager.bind_runtime_session(
            make_source(
                source_kind,
                source_id,
                endpoint_id=source_id,
                endpoint_type=payload.endpoint_type,
                display_name=payload.display_name,
            ),
            session_id=session.session_id,
            default_target=_runtime_target_for_source(
                source_kind,
                source_id,
                {
                    "endpoint_id": source_id,
                    "endpoint_type": payload.endpoint_type,
                    "thread_id": thread.thread_id,
                    "workspace_id": workspace.workspace_id,
                },
            ),
            metadata={
                "thread_id": thread.thread_id,
                "workspace_id": workspace.workspace_id,
                "active_workspace_id": workspace.workspace_id,
                "endpoint_id": source_id,
                "endpoint_type": payload.endpoint_type,
                "source_kind": source_kind,
            },
        )
        return RuntimeSessionResponse(
            session_id=session.session_id,
            thread_id=thread.thread_id,
            active_workspace_id=workspace.workspace_id,
            workspace_id=workspace.workspace_id,
            endpoint_id=str(getattr(endpoint, "endpoint_id", "") or ""),
            status=session.status,
        )

    @router.patch("/sessions/{session_id}/active-workspace", response_model=RuntimeSessionResponse)
    async def patch_active_workspace(session_id: str, payload: RuntimeActiveWorkspacePatchRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        workspace = _find_workspace(domain, payload.active_workspace_id)
        session = domain.services.session.set_active_workspace(
            session_id=session_id,
            active_workspace_id=workspace.id,
            metadata={"active_workspace_id": workspace.workspace_id},
        )
        if session is None:
            gateway._raise_http_error(status_code=404, code="session_not_found", message=f"Unknown session: {session_id}")
        thread = domain.services.thread.get_by_id(session.thread_id)
        return RuntimeSessionResponse(
            session_id=session.session_id,
            thread_id=getattr(thread, "thread_id", ""),
            active_workspace_id=workspace.workspace_id,
            workspace_id=workspace.workspace_id,
            endpoint_id="",
            status=session.status,
        )

    @router.post("/messages", response_model=RuntimeMessageResponse)
    async def create_message(payload: RuntimeMessageCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = _find_thread(domain, payload.thread_id)
        workspace = _find_workspace(domain, payload.resolved_active_workspace_id)
        session = domain.services.session.get_by_session_id(payload.session_id) if payload.session_id else None
        endpoint = _find_endpoint(domain, payload.endpoint_id)
        source_id = str(getattr(endpoint, "endpoint_id", "") or payload.endpoint_id or "ui.endpoint")
        metadata = dict(payload.metadata or {})
        role = payload.role or "user"
        endpoint_message_id = str(payload.endpoint_message_id or "").strip()
        origin_endpoint_row_id = getattr(endpoint, "id", None)
        if endpoint_message_id:
            existing_message = domain.services.message.get_by_endpoint_message_id(
                thread_id=thread.id,
                endpoint_message_id=endpoint_message_id,
                origin_endpoint_id=origin_endpoint_row_id,
                role=role,
            )
            if existing_message is not None:
                return _message_response(
                    existing_message,
                    thread_id=thread.thread_id,
                    workspace_id=workspace.workspace_id,
                    session_id=getattr(session, "session_id", ""),
                    idempotent_replay=True,
                )
            metadata["endpoint_message_id"] = endpoint_message_id
        message = domain.services.message.create_message(
            thread_id=thread.id,
            session_id=getattr(session, "id", None),
            role=role,
            content=payload.content,
            origin_endpoint_id=origin_endpoint_row_id,
            active_workspace_id=workspace.id,
            meta=metadata,
        )
        source_kind = _resolve_runtime_source_kind(
            endpoint_id=source_id,
            endpoint_type=payload.endpoint_type,
            metadata=metadata,
        )
        source_metadata = {
            **metadata,
            "endpoint_id": source_id,
            "endpoint_type": payload.endpoint_type,
            "display_name": payload.display_name,
        }
        event = InboundEvent(
            session_id=getattr(session, "session_id", "") or "",
            type=EventType.MESSAGE.value,
            role=role,
            content=payload.content,
            source=make_source(source_kind, source_id, **source_metadata),
            target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
            metadata={
                "thread_id": thread.thread_id,
                "workspace_id": workspace.workspace_id,
                "message_id": message.message_id,
                "endpoint_id": source_id,
                "endpoint_type": payload.endpoint_type,
                "source_kind": source_kind,
                **metadata,
            },
        )
        if getattr(session, "session_id", ""):
            await gateway._event_bus.inbound_queue.put(event)
        return _message_response(message, thread_id=thread.thread_id, workspace_id=workspace.workspace_id, session_id=getattr(session, "session_id", ""))

    @router.get("/threads/{thread_id}/messages", response_model=list[RuntimeMessageResponse])
    async def list_messages(thread_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = _find_thread(domain, thread_id)
        workspace = domain.services.workspace.get_by_id(getattr(thread, "home_workspace_id", None) or getattr(thread, "workspace_id", None))
        return [
            _message_response(message, thread_id=thread.thread_id, workspace_id=getattr(workspace, "workspace_id", ""))
            for message in domain.services.message.list_messages_for_thread(thread.id)
        ]

    @router.post("/operations", response_model=RuntimeOperationResponse)
    async def create_operation(payload: RuntimeOperationCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = _find_thread(domain, payload.thread_id)
        workspace = _find_workspace(domain, payload.workspace_id)
        try:
            result = await domain.tool_router.dispatch_tool_call(
                tool_key=str(payload.tool_key or payload.capability_id or payload.tool_id or "").strip(),
                arguments=dict(payload.arguments or {}),
                target_endpoint_id=str(payload.target_endpoint_id or ""),
                session_id=str(payload.session_id or ""),
                workspace_id=workspace.workspace_id,
                thread_row_id=thread.id,
                requested_by_actor_id=_request_actor_row_id(domain),
                title=payload.title or payload.operation_type,
                confirmed=True,
                return_operation=True,
            )
        except ToolRouterError as exc:
            _raise_tool_router_error(gateway, exc)
        operation_id = str(result.get("operation_id") or "").strip()
        operation = domain.services.operation.get_by_operation_id(operation_id) if operation_id else None
        if operation is None:
            operation = domain.services.operation.create_operation(
                thread_id=thread.id,
                workspace_id=workspace.id,
                operation_type=payload.operation_type,
                execution_target=payload.execution_target
                or (EXECUTION_TARGET_ENDPOINT if payload.target_endpoint_id else "core.local"),
                execution_target_type="endpoint",
                execution_target_id=str(result.get("execution_target_id") or payload.target_endpoint_id or ""),
                title=payload.title or payload.operation_type,
                status="succeeded",
                metadata={"tool_key": payload.tool_key or "", "result": result},
            )
        return _operation_response(operation, thread_id=thread.thread_id, workspace_id=workspace.workspace_id)

    @router.get("/operations/{operation_id}", response_model=RuntimeOperationResponse)
    async def get_operation(operation_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        operation = domain.services.operation.get_by_operation_id(operation_id)
        if operation is None:
            gateway._raise_http_error(status_code=404, code="operation_not_found", message=f"Unknown operation: {operation_id}")
        thread = domain.services.thread.get_by_id(operation.thread_id) if operation.thread_id else None
        workspace = domain.services.workspace.get_by_id(operation.workspace_id)
        return _operation_response(operation, thread_id=getattr(thread, "thread_id", ""), workspace_id=getattr(workspace, "workspace_id", ""))

    @router.post("/sessions/{session_id}/confirm-response", response_model=RuntimeConfirmResponseResult)
    async def confirm_response(session_id: str, payload: RuntimeConfirmResponseRequest, request: Request):
        gateway._require_http_auth(request)
        accepted = gateway._interaction_responses.submit_confirmation_response(
            payload.accepted,
            request_id=payload.request_id,
            session_id=session_id,
            endpoint_id=payload.endpoint_id,
        )
        return RuntimeConfirmResponseResult(accepted=bool(accepted), request_id=payload.request_id, session_id=session_id)

    @router.post("/sessions/{session_id}/human-input-response", response_model=RuntimeHumanInputResponseResult)
    async def human_input_response(session_id: str, payload: RuntimeHumanInputResponseRequest, request: Request):
        gateway._require_http_auth(request)
        accepted = gateway._interaction_responses.submit_human_input_response(
            payload.answer_text,
            request_id=payload.request_id,
            session_id=session_id,
            selected_option=payload.selected_option,
        )
        return RuntimeHumanInputResponseResult(accepted=bool(accepted), request_id=payload.request_id, session_id=session_id)

    @router.post("/approvals/{approval_id}/decision", response_model=RuntimeApprovalResponse)
    async def decide_approval(approval_id: str, payload: RuntimeApprovalDecisionRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        decision = str(payload.decision or "").strip().lower()
        if decision not in {"approve", "reject"}:
            gateway._raise_http_error(
                status_code=400,
                code="approval_decision_invalid",
                category="validation",
                message="approval decision must be approve or reject",
            )
        approval = domain.services.approval.decide_approval(
            approval_id=approval_id,
            decision=decision,
            reason=payload.reason,
            decided_by_actor_id=_request_actor_row_id(domain),
        )
        if approval is None:
            gateway._raise_http_error(
                status_code=404,
                code="approval_not_found",
                category="validation",
                message=f"Unknown approval: {approval_id}",
            )
        operation = domain.services.operation.get_by_id(approval.operation_id)
        operation_status = ""
        if operation is not None:
            next_status = "queued" if decision == "approve" else "rejected"
            operation = domain.services.operation.update_status(
                operation_id=operation.id,
                status=next_status,
                metadata={
                    "approval_id": approval.approval_id,
                    "approval_status": approval.status,
                    "approval_decision": approval.decision,
                    "approval_endpoint_id": payload.endpoint_id,
                },
            ) or operation
            operation_status = str(getattr(operation, "status", "") or "")
        return RuntimeApprovalResponse(
            approval_id=approval.approval_id,
            operation_id=str(getattr(operation, "operation_id", "") or ""),
            approval_type=approval.approval_type,
            risk_level=approval.risk_level,
            status=approval.status,
            decision=approval.decision,
            reason=approval.reason,
            operation_status=operation_status,
        )

    @router.get("/context-pool/query", response_model=ContextPoolQueryResponse)
    async def query_context_pool(
        request: Request,
        q: str = "",
        thread_id: str = "",
        session_id: str = "",
        active_workspace_id: str = "",
        limit: int = 8,
    ):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = domain.services.thread.get_by_thread_id(thread_id) if str(thread_id or "").strip() else None
        session = domain.services.session.get_by_session_id(session_id) if str(session_id or "").strip() else None
        workspace = (
            domain.services.workspace.get_by_workspace_id(active_workspace_id)
            if str(active_workspace_id or "").strip()
            else None
        )
        rows = domain.services.context_pool.query(
            principal_id=domain.principal.id,
            query_text=q,
            thread_id=getattr(thread, "id", None),
            session_id=getattr(session, "id", None),
            active_workspace_id=getattr(workspace, "id", None),
            limit=limit,
        )
        return ContextPoolQueryResponse(query=q, count=len(rows), items=rows)

    @router.post("/attachments/upload-ticket", response_model=RuntimeAttachmentUploadTicketResponse)
    async def create_attachment_upload_ticket(payload: RuntimeAttachmentUploadTicketRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        endpoint = _find_endpoint(domain, payload.endpoint_id)
        attachment, ticket = domain.services.attachment.create_upload_ticket(
            owner_type=payload.owner_type,
            owner_id=payload.owner_id,
            issuer_type="endpoint" if endpoint is not None else "runtime",
            issuer_ref=payload.endpoint_id or "runtime.http",
            kind=payload.kind,
            mime_type=payload.mime_type,
            file_name=payload.file_name,
            size_bytes=payload.size_bytes,
            lifecycle_policy=payload.lifecycle_policy,
            origin_endpoint_id=getattr(endpoint, "id", None),
        )
        record = domain.services.attachment.build_attachment_record_view(attachment)
        return RuntimeAttachmentUploadTicketResponse(
            attachment_id=attachment.attachment_id,
            ticket_id=ticket.ticket_id,
            upload_url=f"{_public_base_url(request)}/runtime/attachments/upload/{ticket.ticket_id}",
            expires_at=ticket.expires_at,
            object_key=attachment.object_key,
            status=attachment.status,
            created_at=str(record.get("created_at") or ""),
            updated_at=str(record.get("updated_at") or ""),
        )

    @router.put("/attachments/upload/{ticket_id}", response_model=RuntimeAttachmentUploadResult)
    async def upload_attachment_content(ticket_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            attachment = domain.services.attachment.store_upload_content(ticket_id, await request.body())
        except ValueError as exc:
            _raise_runtime_dependency_error(gateway, exc, code=str(exc))
        record = domain.services.attachment.build_attachment_record_view(attachment)
        return RuntimeAttachmentUploadResult(
            attachment_id=attachment.attachment_id,
            ticket_id=ticket_id,
            status=attachment.status,
            size_bytes=int(record.get("size_bytes") or 0),
            sha256=str(record.get("sha256") or ""),
            created_at=str(record.get("created_at") or ""),
            updated_at=str(record.get("updated_at") or ""),
            uploaded_at=str(record.get("uploaded_at") or ""),
        )

    @router.post("/attachments/{attachment_id}/complete", response_model=RuntimeAttachmentResponse)
    async def complete_attachment(attachment_id: str, payload: RuntimeAttachmentCompleteRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            attachment = domain.services.attachment.complete_attachment(
                attachment_id=attachment_id,
                ticket_id=payload.ticket_id,
                sha256=payload.sha256,
                size_bytes=payload.size_bytes,
            )
        except ValueError as exc:
            _raise_runtime_dependency_error(gateway, exc, code=str(exc))
        return _attachment_record_response(domain.services.attachment.build_attachment_record_view(attachment))

    @router.get("/threads/{thread_id}/attachments", response_model=list[RuntimeAttachmentResponse])
    async def list_thread_attachments(thread_id: str, request: Request, include_deleted: bool = False, limit: int = 100):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        records = domain.services.attachment.list_attachments(
            owner_type="thread",
            owner_id=thread_id,
            include_deleted=include_deleted,
            limit=limit,
        )
        return [_attachment_record_response(record) for record in records]

    @router.delete("/attachments/{attachment_id}", response_model=RuntimeAttachmentResponse)
    async def delete_attachment(attachment_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            record = domain.services.attachment.delete_attachment(attachment_id)
        except ValueError as exc:
            _raise_runtime_dependency_error(gateway, exc, code=str(exc))
        return _attachment_record_response(record)

    @router.get("/attachments/{attachment_id}/download-ticket", response_model=RuntimeAttachmentDownloadTicketResponse)
    async def create_attachment_download_ticket(attachment_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            ticket = domain.services.attachment.create_download_ticket(
                attachment_id=attachment_id,
                issuer_type="runtime",
                issuer_ref="runtime.http",
                fallback_download_url="",
            )
        except ValueError as exc:
            _raise_runtime_dependency_error(gateway, exc, code=str(exc))
        attachment = ticket["attachment"]
        fallback_url = (
            f"{_public_base_url(request)}/runtime/attachments/content/{attachment_id}"
            f"?ticket_id={ticket['ticket_id']}"
        )
        download_url = str(ticket.get("download_url") or "").strip() or fallback_url
        return RuntimeAttachmentDownloadTicketResponse(
            attachment_id=attachment_id,
            ticket_id=ticket["ticket_id"],
            download_url=download_url,
            fallback_download_url=fallback_url,
            download_strategy=str(ticket.get("download_strategy") or "proxy"),
            expires_at=str(ticket.get("expires_at") or ""),
            mime_type=str(getattr(attachment, "mime_type", "") or ""),
            file_name=str((getattr(attachment, "meta", {}) or {}).get("file_name") or attachment_id),
            size_bytes=int(getattr(attachment, "size_bytes", 0) or 0),
        )

    @router.get("/attachments/content/{attachment_id}")
    async def get_attachment_content(attachment_id: str, request: Request, ticket_id: str = ""):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            attachment = domain.services.attachment.validate_download_ticket(
                attachment_id=attachment_id,
                ticket_id=ticket_id,
            )
            content = domain.services.attachment.read_attachment_bytes(attachment_id)
        except ValueError as exc:
            _raise_runtime_dependency_error(gateway, exc, code=str(exc))
        return Response(content=content, media_type=str(getattr(attachment, "mime_type", "") or "application/octet-stream"))

    @router.post("/danxi/session/login", response_model=RuntimeDanxiSessionResponse)
    async def danxi_login(payload: RuntimeDanxiSessionLoginRequest, request: Request):
        gateway._require_http_auth(request)
        credentials = _decrypt_danxi_credentials(
            gateway,
            payload.encrypted_credentials,
            purpose="danxi.client.login.v1",
        )
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_login,
            email=str(credentials.get("email") or ""),
            password=str(credentials.get("password") or ""),
            session_key=payload.session_key,
            use_webvpn=credentials.get("use_webvpn"),
            webvpn_cookie=str(credentials.get("webvpn_cookie") or ""),
        )
        return RuntimeDanxiSessionResponse(**result)

    @router.get("/danxi/session", response_model=RuntimeDanxiSessionResponse)
    async def danxi_session(request: Request, session_key: str = "default"):
        gateway._require_http_auth(request)
        result = await _call_danxi(gateway, get_shared_danxi_tools().danxi_get_session_status, session_key)
        return RuntimeDanxiSessionResponse(**result)

    @router.patch("/danxi/session/webvpn-cookie", response_model=RuntimeDanxiSessionResponse)
    async def danxi_webvpn_cookie(payload: RuntimeDanxiWebvpnCookiePatchRequest, request: Request):
        gateway._require_http_auth(request)
        credentials = _decrypt_danxi_credentials(
            gateway,
            payload.encrypted_credentials,
            purpose="danxi.client.webvpn_cookie.v1",
        )
        cookie_header = str(credentials.get("cookie_header") or "").strip()
        if not cookie_header:
            gateway._raise_http_error(
                status_code=400,
                code="danxi_cookie_required",
                category="validation",
                message="WebVPN cookie must be encrypted and non-empty.",
            )
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_set_webvpn_cookie,
            cookie_header,
            session_key=payload.session_key,
            enable_webvpn=bool(credentials.get("enable_webvpn", True)),
        )
        return RuntimeDanxiSessionResponse(**result)

    @router.get("/danxi/profile", response_model=RuntimeDanxiProfileResponse)
    async def danxi_profile(request: Request, session_key: str = "default", refresh: bool = False):
        gateway._require_http_auth(request)
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_get_user_profile,
            session_key=session_key,
            refresh=refresh,
        )
        return RuntimeDanxiProfileResponse(**result)

    @router.get("/danxi/divisions", response_model=RuntimeDanxiListResponse)
    async def danxi_divisions(request: Request, session_key: str = "default"):
        gateway._require_http_auth(request)
        result = await _call_danxi(gateway, get_shared_danxi_tools().danxi_list_divisions, session_key=session_key)
        return RuntimeDanxiListResponse(**result)

    @router.get("/danxi/posts", response_model=RuntimeDanxiListResponse)
    async def danxi_posts(
        request: Request,
        session_key: str = "default",
        division_id: int | None = None,
        start_time: str = "",
        length: int = 20,
        offset: int = 0,
        tag: str = "",
        order: str = "time_created",
    ):
        del offset
        gateway._require_http_auth(request)
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_list_posts,
            division_id=division_id,
            start_time=start_time,
            length=length,
            tag=tag,
            order=order,
            session_key=session_key,
        )
        return RuntimeDanxiListResponse(**result)

    @router.get("/danxi/posts/{hole_id}", response_model=RuntimeDanxiPostResponse)
    async def danxi_post(hole_id: int, request: Request, session_key: str = "default"):
        gateway._require_http_auth(request)
        result = await _call_danxi(gateway, get_shared_danxi_tools().danxi_get_post, hole_id, session_key=session_key)
        return RuntimeDanxiPostResponse(**result)

    @router.get("/danxi/posts/{hole_id}/floors", response_model=RuntimeDanxiListResponse)
    async def danxi_floors(
        hole_id: int,
        request: Request,
        session_key: str = "default",
        offset: int = 0,
        size: int = 20,
        include_all: bool = False,
    ):
        gateway._require_http_auth(request)
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_list_floors,
            hole_id,
            session_key=session_key,
            offset=offset,
            size=size,
            include_all=include_all,
        )
        return RuntimeDanxiListResponse(**result)

    @router.post("/danxi/posts/{hole_id}/replies", response_model=RuntimeDanxiActionResponse)
    async def danxi_reply(hole_id: int, payload: RuntimeDanxiReplyCreateRequest, request: Request):
        gateway._require_http_auth(request)
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_reply_post,
            hole_id,
            payload.content,
            session_key=payload.session_key,
        )
        return RuntimeDanxiActionResponse(**result)

    @router.patch("/danxi/floors/{floor_id}", response_model=RuntimeDanxiActionResponse)
    async def danxi_edit_reply(floor_id: int, payload: RuntimeDanxiReplyUpdateRequest, request: Request):
        gateway._require_http_auth(request)
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_edit_reply,
            floor_id,
            payload.content,
            session_key=payload.session_key,
        )
        return RuntimeDanxiActionResponse(**result)

    @router.delete("/danxi/floors/{floor_id}", response_model=RuntimeDanxiActionResponse)
    async def danxi_delete_reply(floor_id: int, request: Request, confirm: bool = True, session_key: str = "default"):
        gateway._require_http_auth(request)
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_delete_reply,
            floor_id,
            confirm=confirm,
            session_key=session_key,
        )
        return RuntimeDanxiActionResponse(**result)

    @router.get("/danxi/posts/{hole_id}/summary", response_model=RuntimeDanxiSummaryResponse)
    async def danxi_summary(hole_id: int, request: Request, session_key: str = "default", floor_limit: int = 50):
        gateway._require_http_auth(request)
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_summarize_post,
            hole_id,
            session_key=session_key,
            floor_limit=floor_limit,
        )
        return RuntimeDanxiSummaryResponse(**result)

    @router.get("/danxi/search", response_model=RuntimeDanxiSearchResponse)
    async def danxi_search(
        request: Request,
        query: str,
        session_key: str = "default",
        accurate: bool = False,
        length: int = 20,
        start_floor: int | None = None,
        start_time: str = "",
        end_time: str = "",
    ):
        gateway._require_http_auth(request)
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_search_posts,
            query,
            accurate=accurate,
            length=length,
            start_floor=start_floor,
            start_time=start_time,
            end_time=end_time,
            session_key=session_key,
        )
        return RuntimeDanxiSearchResponse(**result)

    @router.get("/danxi/messages", response_model=RuntimeDanxiListResponse)
    async def danxi_messages(
        request: Request,
        session_key: str = "default",
        unread_only: bool = False,
        start_time: str = "",
    ):
        gateway._require_http_auth(request)
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_list_messages,
            unread_only=unread_only,
            start_time=start_time,
            session_key=session_key,
        )
        return RuntimeDanxiListResponse(**result)

    @router.get("/danxi/floors/{floor_id}/target", response_model=RuntimeDanxiMessageTargetResponse)
    async def danxi_floor_target(floor_id: int, request: Request, session_key: str = "default"):
        gateway._require_http_auth(request)
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_resolve_message_target,
            floor_id,
            session_key=session_key,
        )
        return RuntimeDanxiMessageTargetResponse(**result)

    @router.post("/ack", response_model=AckResponse)
    async def ack(request: Request):
        gateway._require_http_auth(request)
        return AckResponse(schema_name=_HTTP_SCHEMA, ack=AckPayload(action="ack", accepted=True))

    return router
