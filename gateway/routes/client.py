from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from core.io_protocol import EventTarget, EventType, InboundEvent, SourceKind, TargetKind, make_source
from core.public_contract import EXECUTION_TARGET_SPECIFIC_ENDPOINT, EXECUTION_TARGETS
from gateway.models import (
    AckPayload,
    AckResponse,
    ClientActiveWorkspacePatchRequest,
    ClientAvailableClientResponse,
    ClientConfirmResponseRequest,
    ClientConfirmResponseResult,
    ClientHumanInputResponseRequest,
    ClientHumanInputResponseResult,
    ClientMessageCreateRequest,
    ClientMessageResponse,
    ClientOperationCreateRequest,
    ClientOperationResponse,
    ClientSessionCreateRequest,
    ClientSessionResponse,
    ClientThreadCreateRequest,
    ClientThreadResponse,
    ClientWorkspaceResponse,
)


_HTTP_SCHEMA = "meetyou.http.v1"


def _workspace_response(workspace) -> ClientWorkspaceResponse:
    meta = dict(getattr(workspace, "meta", {}) or {})
    return ClientWorkspaceResponse(
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


def _message_response(message, *, thread_id: str, workspace_id: str, session_id: str = "") -> ClientMessageResponse:
    return ClientMessageResponse(
        message_id=message.message_id,
        thread_id=thread_id,
        session_id=session_id,
        active_workspace_id=workspace_id,
        workspace_id=workspace_id,
        client_id=str(getattr(message, "origin_endpoint_id", "") or ""),
        role=message.role,
        content=message.content,
        status=message.status,
        channel=message.channel,
        created_at=message.created_at.isoformat() if getattr(message, "created_at", None) is not None else "",
    )


def _operation_response(operation, *, thread_id: str = "", workspace_id: str = "") -> ClientOperationResponse:
    meta = dict(getattr(operation, "meta", {}) or {})
    execution_target = str(getattr(operation, "execution_target", "") or "").strip()
    target_endpoint_id = str(getattr(operation, "execution_target_id", "") or "").strip()
    if execution_target not in EXECUTION_TARGETS and target_endpoint_id:
        execution_target = EXECUTION_TARGET_SPECIFIC_ENDPOINT
    return ClientOperationResponse(
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


def build_client_router(gateway) -> APIRouter:
    router = APIRouter(prefix="/client", tags=["client-v4-http"])

    @router.get("/workspaces", response_model=list[ClientWorkspaceResponse])
    async def list_workspaces(request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        return [_workspace_response(workspace) for workspace in domain.services.workspace.list_workspaces()]

    @router.get("/workspaces/{workspace_id}/clients", response_model=list[ClientAvailableClientResponse])
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
            endpoints.append(
                ClientAvailableClientResponse(
                    client_id=endpoint.endpoint_id,
                    display_name=str(meta.get("display_name") or endpoint.endpoint_id),
                    client_type=endpoint.provider_type,
                    status="online" if endpoint.endpoint_id in connected else endpoint.status,
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

    @router.post("/threads", response_model=ClientThreadResponse)
    async def create_thread(payload: ClientThreadCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        workspace = _find_workspace(domain, payload.resolved_home_workspace_id)
        thread = domain.services.thread.create_thread(
            principal_id=domain.principal.id,
            workspace_id=workspace.id,
            title=payload.title,
            pinned_procedure_id=payload.pinned_procedure_id,
        )
        return _thread_response(thread, workspace.workspace_id)

    @router.get("/threads/{thread_id}", response_model=ClientThreadResponse)
    async def get_thread(thread_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = _find_thread(domain, thread_id)
        workspace = domain.services.workspace.get_by_id(getattr(thread, "home_workspace_id", None) or getattr(thread, "workspace_id", None))
        return _thread_response(thread, getattr(workspace, "workspace_id", ""))

    @router.post("/sessions", response_model=ClientSessionResponse)
    async def create_session(payload: ClientSessionCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = _find_thread(domain, payload.thread_id)
        workspace = _find_workspace(domain, payload.resolved_active_workspace_id or getattr(thread, "workspace_id", ""))
        endpoint = _find_endpoint(domain, payload.client_id)
        session = domain.services.session.create_session(
            thread_id=thread.id,
            origin_endpoint_id=getattr(endpoint, "id", None),
            workspace_id=workspace.id,
        )
        return ClientSessionResponse(
            session_id=session.session_id,
            thread_id=thread.thread_id,
            active_workspace_id=workspace.workspace_id,
            workspace_id=workspace.workspace_id,
            client_id=str(getattr(endpoint, "endpoint_id", "") or ""),
            status=session.status,
        )

    @router.patch("/sessions/{session_id}/active-workspace", response_model=ClientSessionResponse)
    async def patch_active_workspace(session_id: str, payload: ClientActiveWorkspacePatchRequest, request: Request):
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
        return ClientSessionResponse(
            session_id=session.session_id,
            thread_id=getattr(thread, "thread_id", ""),
            active_workspace_id=workspace.workspace_id,
            workspace_id=workspace.workspace_id,
            client_id="",
            status=session.status,
        )

    @router.post("/messages", response_model=ClientMessageResponse)
    async def create_message(payload: ClientMessageCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = _find_thread(domain, payload.thread_id)
        workspace = _find_workspace(domain, payload.resolved_active_workspace_id)
        session = domain.services.session.get_by_session_id(payload.session_id) if payload.session_id else None
        endpoint = _find_endpoint(domain, payload.client_id)
        message = domain.services.message.create_message(
            thread_id=thread.id,
            session_id=getattr(session, "id", None),
            role=payload.role or "user",
            content=payload.content,
            origin_endpoint_id=getattr(endpoint, "id", None),
            active_workspace_id=workspace.id,
            meta=dict(payload.metadata or {}),
        )
        source_id = str(getattr(endpoint, "endpoint_id", "") or payload.client_id or "ui.endpoint")
        event = InboundEvent(
            session_id=getattr(session, "session_id", "") or "",
            type=EventType.MESSAGE.value,
            role=payload.role or "user",
            content=payload.content,
            source=make_source(SourceKind.WEB.value, source_id, endpoint_id=source_id),
            target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
            metadata={
                "thread_id": thread.thread_id,
                "workspace_id": workspace.workspace_id,
                "message_id": message.message_id,
                **dict(payload.metadata or {}),
            },
        )
        if getattr(session, "session_id", ""):
            await gateway._event_bus.inbound_queue.put(event)
        return _message_response(message, thread_id=thread.thread_id, workspace_id=workspace.workspace_id, session_id=getattr(session, "session_id", ""))

    @router.get("/threads/{thread_id}/messages", response_model=list[ClientMessageResponse])
    async def list_messages(thread_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = _find_thread(domain, thread_id)
        workspace = domain.services.workspace.get_by_id(getattr(thread, "home_workspace_id", None) or getattr(thread, "workspace_id", None))
        return [
            _message_response(message, thread_id=thread.thread_id, workspace_id=getattr(workspace, "workspace_id", ""))
            for message in domain.services.message.list_messages_for_thread(thread.id)
        ]

    @router.post("/operations", response_model=ClientOperationResponse)
    async def create_operation(payload: ClientOperationCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = _find_thread(domain, payload.thread_id)
        workspace = _find_workspace(domain, payload.workspace_id)
        result = await domain.tool_router.dispatch_directed_tool(
            tool_key=str(payload.tool_key or payload.capability_id or payload.tool_id or "").strip(),
            arguments=dict(payload.arguments or {}),
            target_endpoint_id=str(payload.target_endpoint_id or ""),
            session_id=str(payload.session_id or ""),
            workspace_id=workspace.workspace_id,
            title=payload.title or payload.operation_type,
            confirmed=True,
        )
        operation = domain.services.operation.create_operation(
            thread_id=thread.id,
            workspace_id=workspace.id,
            operation_type=payload.operation_type,
            execution_target=payload.execution_target
            or (EXECUTION_TARGET_SPECIFIC_ENDPOINT if payload.target_endpoint_id else "core.local"),
            execution_target_type="endpoint",
            execution_target_id=str(result.get("execution_target_id") or payload.target_endpoint_id or ""),
            title=payload.title or payload.operation_type,
            status="succeeded",
            metadata={"tool_key": payload.tool_key or "", "result": result},
        )
        return _operation_response(operation, thread_id=thread.thread_id, workspace_id=workspace.workspace_id)

    @router.get("/operations/{operation_id}", response_model=ClientOperationResponse)
    async def get_operation(operation_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        operation = domain.services.operation.get_by_operation_id(operation_id)
        if operation is None:
            gateway._raise_http_error(status_code=404, code="operation_not_found", message=f"Unknown operation: {operation_id}")
        thread = domain.services.thread.get_by_id(operation.thread_id) if operation.thread_id else None
        workspace = domain.services.workspace.get_by_id(operation.workspace_id)
        return _operation_response(operation, thread_id=getattr(thread, "thread_id", ""), workspace_id=getattr(workspace, "workspace_id", ""))

    @router.post("/sessions/{session_id}/confirm-response", response_model=ClientConfirmResponseResult)
    async def confirm_response(session_id: str, payload: ClientConfirmResponseRequest, request: Request):
        gateway._require_http_auth(request)
        accepted = gateway._interaction_responses.submit_confirmation_response(
            payload.accepted,
            request_id=payload.request_id,
            session_id=session_id,
            client_id=payload.client_id,
        )
        return ClientConfirmResponseResult(accepted=bool(accepted), request_id=payload.request_id, session_id=session_id)

    @router.post("/sessions/{session_id}/human-input-response", response_model=ClientHumanInputResponseResult)
    async def human_input_response(session_id: str, payload: ClientHumanInputResponseRequest, request: Request):
        gateway._require_http_auth(request)
        accepted = gateway._interaction_responses.submit_human_input_response(
            payload.answer_text,
            request_id=payload.request_id,
            session_id=session_id,
            selected_option=payload.selected_option,
        )
        return ClientHumanInputResponseResult(accepted=bool(accepted), request_id=payload.request_id, session_id=session_id)

    @router.post("/ack", response_model=AckResponse)
    async def ack(request: Request):
        gateway._require_http_auth(request)
        return AckResponse(schema_name=_HTTP_SCHEMA, ack=AckPayload(action="ack", accepted=True))

    return router
