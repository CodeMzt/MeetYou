from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from core.credential_transport import CredentialTransportError, decrypt_json_payload
from core.io_protocol import EventTarget, EventType, InboundEvent, SourceKind, TargetKind, make_source
from core.public_contract import EXECUTION_TARGET_ENDPOINT, EXECUTION_TARGETS
from core.services.endpoint_service import EndpointThreadBindingError
from core.services.v5_service import ResearchTaskCitationError
from core.services.workspace_service import WorkspaceService
from core.services.tool_router_service import ToolRouterError
from gateway.models import (
    AckPayload,
    AckResponse,
    RuntimeActiveWorkspacePatchRequest,
    RuntimeApprovalDecisionRequest,
    RuntimeApprovalResponse,
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
    RuntimeReplyControlRequest,
    RuntimeReplyControlResult,
    RuntimeDefaultThreadRequest,
    RuntimeEndpointSessionResolveRequest,
    RuntimeEndpointSessionResolveResponse,
    RuntimeEndpointThreadBindingResponse,
    RuntimeSessionCreateRequest,
    RuntimeSessionResponse,
    RuntimeThreadCreateRequest,
    RuntimeThreadDeleteResponse,
    RuntimeThreadResponse,
    RuntimeWorkspaceResponse,
    ContextPoolQueryResponse,
    EndpointAvailableResponse,
    RuntimeArtifactResponse,
    RuntimeCheckpointCheckoutRequest,
    RuntimeConversationCheckpointCreateRequest,
    RuntimeConversationCheckpointResponse,
    RuntimeMessageEditRetryRequest,
    RuntimeMessageEditRetryResponse,
    RuntimeProjectCreateRequest,
    RuntimeProjectResponse,
    RuntimeProjectSourceCreateRequest,
    RuntimeProjectSourceFromMessageRequest,
    RuntimeProjectSourceResponse,
    RuntimeProjectUpdateRequest,
    RuntimeResearchTaskCreateRequest,
    RuntimeResearchTaskPatchRequest,
    RuntimeResearchTaskResponse,
    RuntimeThreadBranchResponse,
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
    governance = WorkspaceService.get_governance_view(workspace)
    return RuntimeWorkspaceResponse(
        workspace_id=workspace.workspace_id,
        title=workspace.title,
        status=workspace.status,
        base_mode=workspace.base_mode,
        description=str(governance.get("description") or ""),
        prompt_overlay=workspace.prompt_overlay,
        default_execution_target=workspace.default_execution_target,
        tool_policy=str(governance.get("tool_policy") or "allow_all"),
        allowed_tool_ids=list(governance.get("allowed_tool_ids") or []),
        preferred_target_endpoint_ids=list(governance.get("preferred_target_endpoint_ids") or []),
        preferred_endpoint_provider_types=list(governance.get("preferred_endpoint_provider_types") or []),
        preferred_source_profiles=list(governance.get("preferred_source_profiles") or []),
        tool_target_routing_policy=str(governance.get("tool_target_routing_policy") or "balanced"),
        memory_ranking_policy=str(governance.get("memory_ranking_policy") or "workspace_first"),
        tool_routing_overrides=dict(governance.get("tool_routing_overrides") or {}),
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


def _iso(row, attr: str) -> str:
    value = getattr(row, attr, None)
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else ""


def _project_response(project, workspace_id: str = "") -> RuntimeProjectResponse:
    return RuntimeProjectResponse(
        project_id=str(getattr(project, "project_id", "") or ""),
        workspace_id=workspace_id,
        title=str(getattr(project, "title", "") or ""),
        description=str(getattr(project, "description", "") or ""),
        instructions=str(getattr(project, "instructions", "") or ""),
        status=str(getattr(project, "status", "") or "active"),
        memory_scope=dict(getattr(project, "memory_scope", {}) or {}),
        metadata=dict(getattr(project, "meta", {}) or {}),
        created_at=_iso(project, "created_at"),
        updated_at=_iso(project, "updated_at"),
    )


def _project_source_response(source, *, project_id: str) -> RuntimeProjectSourceResponse:
    return RuntimeProjectSourceResponse(
        source_id=str(getattr(source, "source_id", "") or ""),
        project_id=project_id,
        source_type=str(getattr(source, "source_type", "") or "note"),
        title=str(getattr(source, "title", "") or ""),
        content=str(getattr(source, "content", "") or ""),
        content_type=str(getattr(source, "content_type", "") or "text"),
        checksum=str(getattr(source, "checksum", "") or ""),
        status=str(getattr(source, "status", "") or "active"),
        metadata=dict(getattr(source, "meta", {}) or {}),
        created_at=_iso(source, "created_at"),
        updated_at=_iso(source, "updated_at"),
    )


def _artifact_response(domain, artifact) -> RuntimeArtifactResponse:
    project = domain.services.project.get_by_id(getattr(artifact, "project_id", None)) if getattr(artifact, "project_id", None) else None
    thread = domain.services.thread.get_by_id(getattr(artifact, "thread_id", None)) if getattr(artifact, "thread_id", None) else None
    artifact_id = str(getattr(artifact, "artifact_id", "") or "")
    return RuntimeArtifactResponse(
        artifact_id=artifact_id,
        project_id=str(getattr(project, "project_id", "") or ""),
        thread_id=str(getattr(thread, "thread_id", "") or ""),
        artifact_type=str(getattr(artifact, "artifact_type", "") or "document"),
        filename=str(getattr(artifact, "filename", "") or ""),
        content_type=str(getattr(artifact, "content_type", "") or "application/octet-stream"),
        byte_size=int(getattr(artifact, "byte_size", 0) or 0),
        checksum=str(getattr(artifact, "checksum", "") or ""),
        status=str(getattr(artifact, "status", "") or "active"),
        download_url=f"/runtime/artifacts/{artifact_id}/download" if artifact_id else "",
        metadata=dict(getattr(artifact, "meta", {}) or {}),
        created_at=_iso(artifact, "created_at"),
        updated_at=_iso(artifact, "updated_at"),
    )


def _branch_response(domain, branch) -> RuntimeThreadBranchResponse:
    thread = domain.services.thread.get_by_id(getattr(branch, "thread_id", None))
    leaf = domain.services.message.get_by_id(getattr(branch, "current_leaf_message_id", None)) if getattr(branch, "current_leaf_message_id", None) else None
    return RuntimeThreadBranchResponse(
        branch_id=str(getattr(branch, "branch_id", "") or ""),
        thread_id=str(getattr(thread, "thread_id", "") or ""),
        parent_branch_id="",
        title=str(getattr(branch, "title", "") or ""),
        status=str(getattr(branch, "status", "") or "active"),
        current_leaf_message_id=str(getattr(leaf, "message_id", "") or ""),
        metadata=dict(getattr(branch, "meta", {}) or {}),
        created_at=_iso(branch, "created_at"),
        updated_at=_iso(branch, "updated_at"),
    )


def _checkpoint_response(domain, checkpoint) -> RuntimeConversationCheckpointResponse:
    thread = domain.services.thread.get_by_id(getattr(checkpoint, "thread_id", None))
    branch = None
    message = domain.services.message.get_by_id(getattr(checkpoint, "message_id", None)) if getattr(checkpoint, "message_id", None) else None
    for candidate in domain.services.conversation_version.list_branches(thread_id=getattr(thread, "thread_id", "")) or []:
        if getattr(candidate, "id", None) == getattr(checkpoint, "branch_id", None):
            branch = candidate
            break
    return RuntimeConversationCheckpointResponse(
        checkpoint_id=str(getattr(checkpoint, "checkpoint_id", "") or ""),
        thread_id=str(getattr(thread, "thread_id", "") or ""),
        branch_id=str(getattr(branch, "branch_id", "") or ""),
        message_id=str(getattr(message, "message_id", "") or ""),
        checkpoint_type=str(getattr(checkpoint, "checkpoint_type", "") or "manual"),
        title=str(getattr(checkpoint, "title", "") or ""),
        state=dict(getattr(checkpoint, "state", {}) or {}),
        status=str(getattr(checkpoint, "status", "") or "active"),
        metadata=dict(getattr(checkpoint, "meta", {}) or {}),
        created_at=_iso(checkpoint, "created_at"),
        updated_at=_iso(checkpoint, "updated_at"),
    )


def _research_task_response(domain, task) -> RuntimeResearchTaskResponse:
    project = domain.services.project.get_by_id(getattr(task, "project_id", None)) if getattr(task, "project_id", None) else None
    thread = domain.services.thread.get_by_id(getattr(task, "thread_id", None)) if getattr(task, "thread_id", None) else None
    artifact_response = None
    if getattr(task, "artifact_id", None):
        artifact = domain.services.artifact.get_by_id(getattr(task, "artifact_id", None))
        if artifact is not None:
            artifact_response = _artifact_response(domain, artifact)
    return RuntimeResearchTaskResponse(
        research_task_id=str(getattr(task, "research_task_id", "") or ""),
        project_id=str(getattr(project, "project_id", "") or ""),
        thread_id=str(getattr(thread, "thread_id", "") or ""),
        artifact_id=str(getattr(artifact_response, "artifact_id", "") or ""),
        topic=str(getattr(task, "topic", "") or ""),
        status=str(getattr(task, "status", "") or "planned"),
        plan=dict(getattr(task, "plan", {}) or {}),
        source_policy=dict(getattr(task, "source_policy", {}) or {}),
        evidence_ledger=list(getattr(task, "evidence_ledger", []) or []),
        output_format=str(getattr(task, "output_format", "") or "markdown"),
        summary=str(getattr(task, "summary", "") or ""),
        artifact=artifact_response,
        metadata=dict(getattr(task, "meta", {}) or {}),
        created_at=_iso(task, "created_at"),
        updated_at=_iso(task, "updated_at"),
    )


def _record_context_pool_runtime_user_message(
    domain,
    *,
    message,
    thread,
    session,
    endpoint,
    active_workspace,
) -> None:
    if str(getattr(message, "role", "") or "") != "user":
        return
    services = getattr(domain, "services", None)
    context_pool = getattr(services, "context_pool", None) if services is not None else None
    principal = getattr(domain, "principal", None)
    if context_pool is None or principal is None:
        return
    workspace_service = getattr(services, "workspace", None)
    home_workspace = active_workspace
    get_workspace_by_id = getattr(workspace_service, "get_by_id", None)
    home_workspace_row_id = getattr(thread, "home_workspace_id", None) or getattr(thread, "workspace_id", None)
    if callable(get_workspace_by_id) and home_workspace_row_id is not None:
        try:
            home_workspace = get_workspace_by_id(home_workspace_row_id) or active_workspace
        except Exception:
            home_workspace = active_workspace
    try:
        context_pool.record_message(
            principal_id=getattr(principal, "id", None),
            message=message,
            thread=thread,
            session=session,
            endpoint=endpoint,
            active_workspace=active_workspace,
            home_workspace=home_workspace,
            metadata={"source": "runtime.message"},
        )
    except Exception:
        return


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


def _require_thread(gateway, domain, thread_id: str):
    try:
        return _find_thread(domain, thread_id)
    except KeyError:
        gateway._raise_http_error(
            status_code=404,
            code="thread_not_found",
            message=f"Unknown thread: {thread_id}",
        )


def _find_endpoint(domain, endpoint_id: str = ""):
    normalized = str(endpoint_id or "").strip()
    if not normalized:
        return None
    return domain.services.endpoint.get_by_endpoint_id(normalized)


def _infer_provider_type(endpoint_id: str, fallback: str = "") -> str:
    normalized = str(endpoint_id or "").strip()
    if fallback:
        return str(fallback or "").strip().lower()
    if "." in normalized:
        return normalized.split(".", 1)[0].strip().lower()
    return "external"


def _ensure_endpoint_for_session_resolve(domain, payload: RuntimeEndpointSessionResolveRequest, workspace_id: str):
    endpoint_id = str(payload.endpoint_id or "").strip()
    if not endpoint_id:
        raise EndpointThreadBindingError("endpoint_id_required", "endpoint_id is required.")
    endpoint = domain.services.endpoint.get_by_endpoint_id(endpoint_id)
    if endpoint is not None:
        return endpoint
    provider_type = _infer_provider_type(endpoint_id, payload.provider_type)
    endpoint_type = str(payload.endpoint_type or f"{provider_type}_ui").strip() or "endpoint"
    return domain.services.endpoint.ensure_endpoint(
        endpoint_id=endpoint_id,
        endpoint_type=endpoint_type,
        provider_type=provider_type,
        transport_type="websocket",
        workspace_scope=[workspace_id] if workspace_id else [],
        status="active",
        labels=["input", "output"],
        metadata={
            "display_name": str(payload.display_name or endpoint_id).strip(),
            "declared_by": "runtime.endpoint_sessions.resolve",
        },
    )


def _session_response(session, *, thread, workspace, endpoint) -> RuntimeSessionResponse:
    return RuntimeSessionResponse(
        session_id=session.session_id,
        thread_id=thread.thread_id,
        active_workspace_id=workspace.workspace_id,
        workspace_id=workspace.workspace_id,
        endpoint_id=str(getattr(endpoint, "endpoint_id", "") or ""),
        status=session.status,
    )


def _binding_response(binding, *, endpoint, thread, workspace, address=None) -> RuntimeEndpointThreadBindingResponse:
    return RuntimeEndpointThreadBindingResponse(
        binding_id=str(getattr(binding, "binding_id", "") or ""),
        endpoint_id=str(getattr(endpoint, "endpoint_id", "") or ""),
        thread_id=str(getattr(thread, "thread_id", "") or ""),
        workspace_id=str(getattr(workspace, "workspace_id", "") or ""),
        address_id=str(getattr(address, "address_id", "") or ""),
        thread_strategy=str(getattr(binding, "thread_strategy", "") or ""),
        conversation_key=str(getattr(binding, "conversation_key", "") or ""),
        display_name=str(getattr(binding, "display_name", "") or ""),
        status=str(getattr(binding, "status", "") or "active"),
        metadata=dict(getattr(binding, "meta", {}) or {}),
    )


def _bind_gateway_runtime_session(gateway, *, session, thread, workspace, endpoint, endpoint_type: str = "", display_name: str = "") -> None:
    source_id = str(getattr(endpoint, "endpoint_id", "") or "runtime.endpoint").strip()
    source_kind = _resolve_runtime_source_kind(
        endpoint_id=source_id,
        endpoint_type=endpoint_type,
        metadata={"provider_type": getattr(endpoint, "provider_type", "") if endpoint is not None else ""},
    )
    gateway._session_manager.bind_runtime_session(
        make_source(
            source_kind,
            source_id,
            endpoint_id=source_id,
            endpoint_type=endpoint_type,
            display_name=display_name,
        ),
        session_id=session.session_id,
        default_target=_runtime_target_for_source(
            source_kind,
            source_id,
            {
                "endpoint_id": source_id,
                "endpoint_type": endpoint_type,
                "thread_id": thread.thread_id,
                "workspace_id": workspace.workspace_id,
            },
        ),
        metadata={
            "thread_id": thread.thread_id,
            "workspace_id": workspace.workspace_id,
            "active_workspace_id": workspace.workspace_id,
            "endpoint_id": source_id,
            "endpoint_type": endpoint_type,
            "source_kind": source_kind,
            "provider_type": str(getattr(endpoint, "provider_type", "") or ""),
        },
    )


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

    @router.get("/projects", response_model=list[RuntimeProjectResponse])
    async def list_projects(request: Request, workspace_id: str = "", include_archived: bool = False, limit: int = 100):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        workspace = _find_workspace(domain, workspace_id) if str(workspace_id or "").strip() else None
        rows = domain.services.project.list_projects(
            principal_id=domain.principal.id,
            workspace_id=getattr(workspace, "id", None),
            include_archived=include_archived,
            limit=limit,
        )
        return [
            _project_response(row, str(getattr(domain.services.workspace.get_by_id(getattr(row, "workspace_id", None)), "workspace_id", "") or ""))
            for row in rows
        ]

    @router.post("/projects", response_model=RuntimeProjectResponse)
    async def create_project(payload: RuntimeProjectCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        workspace = _find_workspace(domain, payload.workspace_id) if str(payload.workspace_id or "").strip() else None
        project = domain.services.project.create_project(
            principal_id=domain.principal.id,
            workspace_id=getattr(workspace, "id", None),
            title=payload.title,
            description=payload.description,
            instructions=payload.instructions,
            memory_scope=payload.memory_scope,
            metadata=payload.metadata,
        )
        return _project_response(project, str(getattr(workspace, "workspace_id", "") or ""))

    @router.patch("/projects/{project_id}", response_model=RuntimeProjectResponse)
    async def update_project(project_id: str, payload: RuntimeProjectUpdateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        project = domain.services.project.update_project(
            project_id=project_id,
            fields=payload.model_dump(exclude_unset=True),
        )
        if project is None:
            gateway._raise_http_error(status_code=404, code="project_not_found", message=f"Unknown project: {project_id}")
        workspace = domain.services.workspace.get_by_id(getattr(project, "workspace_id", None)) if getattr(project, "workspace_id", None) else None
        return _project_response(project, str(getattr(workspace, "workspace_id", "") or ""))

    @router.delete("/projects/{project_id}", response_model=RuntimeProjectResponse)
    async def archive_project(project_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        project = domain.services.project.archive_project(project_id=project_id)
        if project is None:
            gateway._raise_http_error(status_code=404, code="project_not_found", message=f"Unknown project: {project_id}")
        workspace = domain.services.workspace.get_by_id(getattr(project, "workspace_id", None)) if getattr(project, "workspace_id", None) else None
        return _project_response(project, str(getattr(workspace, "workspace_id", "") or ""))

    @router.get("/projects/{project_id}/sources", response_model=list[RuntimeProjectSourceResponse])
    async def list_project_sources(project_id: str, request: Request, include_archived: bool = False, limit: int = 100):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        rows = domain.services.project.list_sources(project_id=project_id, include_archived=include_archived, limit=limit)
        if rows is None:
            gateway._raise_http_error(status_code=404, code="project_not_found", message=f"Unknown project: {project_id}")
        return [_project_source_response(row, project_id=project_id) for row in rows]

    @router.post("/projects/{project_id}/sources", response_model=RuntimeProjectSourceResponse)
    async def create_project_source(project_id: str, payload: RuntimeProjectSourceCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            source = domain.services.project.add_source(
                project_id=project_id,
                principal_id=domain.principal.id,
                source_type=payload.source_type,
                title=payload.title,
                content=payload.content,
                content_type=payload.content_type,
                metadata=payload.metadata,
            )
        except ValueError as exc:
            gateway._raise_http_error(status_code=400, code="project_source_invalid", message=str(exc))
        if source is None:
            gateway._raise_http_error(status_code=404, code="project_not_found", message=f"Unknown project: {project_id}")
        return _project_source_response(source, project_id=project_id)

    @router.post("/projects/{project_id}/sources/from-message", response_model=RuntimeProjectSourceResponse)
    async def create_project_source_from_message(project_id: str, payload: RuntimeProjectSourceFromMessageRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        source = domain.services.project.save_message_source(
            project_id=project_id,
            principal_id=domain.principal.id,
            message_id=payload.message_id,
            title=payload.title,
            metadata=payload.metadata,
        )
        if source is None:
            gateway._raise_http_error(status_code=404, code="project_or_message_not_found", message="Unknown project or message.")
        return _project_source_response(source, project_id=project_id)

    @router.get("/projects/{project_id}/artifacts", response_model=list[RuntimeArtifactResponse])
    async def list_project_artifacts(project_id: str, request: Request, include_archived: bool = False, limit: int = 100):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        rows = domain.services.artifact.list_for_project(project_id=project_id, include_archived=include_archived, limit=limit)
        if rows is None:
            gateway._raise_http_error(status_code=404, code="project_not_found", message=f"Unknown project: {project_id}")
        return [_artifact_response(domain, row) for row in rows]

    @router.get("/artifacts/{artifact_id}/download")
    async def download_artifact(artifact_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        artifact = domain.services.artifact.get_by_artifact_id(artifact_id)
        if artifact is None:
            gateway._raise_http_error(status_code=404, code="artifact_not_found", message=f"Unknown artifact: {artifact_id}")
        path = domain.services.artifact.resolve_local_path(artifact)
        if not path:
            gateway._raise_http_error(status_code=501, code="artifact_backend_not_supported", message="Only local ArtifactStore downloads are available in this build.")
        from pathlib import Path

        file_path = Path(path)
        if not file_path.exists() or not file_path.is_file():
            gateway._raise_http_error(status_code=404, code="artifact_file_missing", message="Artifact file is missing from local storage.")
        return FileResponse(
            str(file_path),
            media_type=str(getattr(artifact, "content_type", "") or "application/octet-stream"),
            filename=str(getattr(artifact, "filename", "") or artifact_id),
        )

    @router.get("/research-tasks", response_model=list[RuntimeResearchTaskResponse])
    async def list_research_tasks(request: Request, project_id: str = "", limit: int = 100):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        project = domain.services.project.get_by_project_id(project_id) if str(project_id or "").strip() else None
        rows = domain.services.research_task.list_tasks(
            principal_id=domain.principal.id,
            project_id=getattr(project, "id", None),
            limit=limit,
        )
        return [_research_task_response(domain, row) for row in rows]

    @router.post("/research-tasks", response_model=RuntimeResearchTaskResponse)
    async def create_research_task(payload: RuntimeResearchTaskCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        project = domain.services.project.get_by_project_id(payload.project_id) if str(payload.project_id or "").strip() else None
        thread = domain.services.thread.get_by_thread_id(payload.thread_id) if str(payload.thread_id or "").strip() else None
        if payload.project_id and project is None:
            gateway._raise_http_error(status_code=404, code="project_not_found", message=f"Unknown project: {payload.project_id}")
        if payload.thread_id and thread is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"Unknown thread: {payload.thread_id}")
        try:
            task = domain.services.research_task.create_task(
                principal_id=domain.principal.id,
                project_id=getattr(project, "id", None),
                thread_id=getattr(thread, "id", None),
                topic=payload.topic,
                source_policy=payload.source_policy,
                output_format=payload.output_format,
                metadata=payload.metadata,
            )
        except ValueError as exc:
            gateway._raise_http_error(status_code=400, code="research_task_invalid", message=str(exc))
        return _research_task_response(domain, task)

    @router.get("/research-tasks/{research_task_id}", response_model=RuntimeResearchTaskResponse)
    async def get_research_task(research_task_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        task = domain.services.research_task.get_by_research_task_id(research_task_id)
        if task is None:
            gateway._raise_http_error(status_code=404, code="research_task_not_found", message=f"Unknown research task: {research_task_id}")
        return _research_task_response(domain, task)

    @router.patch("/research-tasks/{research_task_id}", response_model=RuntimeResearchTaskResponse)
    async def patch_research_task(research_task_id: str, payload: RuntimeResearchTaskPatchRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        fields = payload.model_dump(exclude_unset=True)
        action = str(fields.pop("action", "") or "").strip().lower()
        if action in {"start", "cancel", "complete"}:
            fields["status"] = {"start": "running", "cancel": "cancelled", "complete": "completed"}[action]
        report_markdown = fields.pop("report_markdown", None)
        report_filename = str(fields.pop("report_filename", "") or "").strip()
        task = domain.services.research_task.get_by_research_task_id(research_task_id)
        if task is None:
            gateway._raise_http_error(status_code=404, code="research_task_not_found", message=f"Unknown research task: {research_task_id}")
        if report_markdown is not None:
            evidence_ledger = fields.get("evidence_ledger")
            if not isinstance(evidence_ledger, list):
                evidence_ledger = list(getattr(task, "evidence_ledger", []) or [])
            try:
                citation_validation = domain.services.research_task.validate_report_citations(
                    str(report_markdown or ""),
                    evidence_ledger,
                )
            except ResearchTaskCitationError as exc:
                gateway._raise_http_error(
                    status_code=400,
                    code="research_report_citation_invalid",
                    message=str(exc),
                    details={
                        "missing_source_ids": exc.missing_source_ids,
                        "citation_ids": exc.citation_ids,
                        "evidence_source_ids": exc.evidence_source_ids,
                    },
                )
            artifact = domain.services.artifact.create_text_artifact(
                principal_id=domain.principal.id,
                project_id=getattr(task, "project_id", None),
                thread_id=getattr(task, "thread_id", None),
                text=str(report_markdown or ""),
                filename=report_filename or f"{research_task_id}.md",
                artifact_type="research_report",
                metadata={"research_task_id": research_task_id, "citation_validation": citation_validation},
            )
            fields["artifact_id"] = artifact.id
            fields.setdefault("metadata", {})
            fields["metadata"] = {
                **dict(fields.get("metadata") or {}),
                "artifact_id": artifact.artifact_id,
                "citation_validation": citation_validation,
            }
            fields.setdefault("status", "completed")
        task = domain.services.research_task.update_task(research_task_id=research_task_id, fields=fields) or task
        return _research_task_response(domain, task)

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
        thread = _require_thread(gateway, domain, thread_id)
        workspace = domain.services.workspace.get_by_id(getattr(thread, "home_workspace_id", None) or getattr(thread, "workspace_id", None))
        return _thread_response(thread, getattr(workspace, "workspace_id", ""))

    @router.delete("/threads/{thread_id}", response_model=RuntimeThreadDeleteResponse)
    async def delete_thread(thread_id: str, request: Request, force: bool = False):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        result = domain.services.thread.delete_thread(
            principal_id=domain.principal.id,
            thread_id=thread_id,
            force=force,
        )
        row = result.thread
        if row is None:
            return RuntimeThreadDeleteResponse(
                ok=False,
                thread_id=str(thread_id or ""),
                deleted=False,
                reason=result.reason or "not_found",
            )
        return RuntimeThreadDeleteResponse(
            ok=result.deleted,
            thread_id=str(getattr(row, "thread_id", "") or thread_id),
            deleted=result.deleted,
            status=str(getattr(row, "status", "") or ""),
            reason=result.reason,
            default_thread=result.default_thread,
        )

    @router.get("/threads/{thread_id}/branches", response_model=list[RuntimeThreadBranchResponse])
    async def list_thread_branches(thread_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        rows = domain.services.conversation_version.list_branches(thread_id=thread_id)
        if rows is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"Unknown thread: {thread_id}")
        return [_branch_response(domain, row) for row in rows]

    @router.get("/threads/{thread_id}/checkpoints", response_model=list[RuntimeConversationCheckpointResponse])
    async def list_thread_checkpoints(thread_id: str, request: Request, limit: int = 100):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        rows = domain.services.conversation_version.list_checkpoints(thread_id=thread_id, limit=limit)
        if rows is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"Unknown thread: {thread_id}")
        return [_checkpoint_response(domain, row) for row in rows]

    @router.post("/threads/{thread_id}/checkpoints", response_model=RuntimeConversationCheckpointResponse)
    async def create_thread_checkpoint(thread_id: str, payload: RuntimeConversationCheckpointCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        checkpoint = domain.services.conversation_version.create_checkpoint(
            thread_id=thread_id,
            title=payload.title,
            checkpoint_type=payload.checkpoint_type,
            metadata=payload.metadata,
        )
        if checkpoint is None:
            gateway._raise_http_error(status_code=404, code="thread_not_found", message=f"Unknown thread: {thread_id}")
        return _checkpoint_response(domain, checkpoint)

    @router.post("/threads/{thread_id}/checkpoints/{checkpoint_id}/restore", response_model=RuntimeConversationCheckpointResponse)
    async def restore_thread_checkpoint(thread_id: str, checkpoint_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        checkpoint = domain.services.conversation_version.restore_checkpoint(thread_id=thread_id, checkpoint_id=checkpoint_id)
        if checkpoint is None:
            gateway._raise_http_error(status_code=404, code="checkpoint_not_found", message=f"Unknown checkpoint: {checkpoint_id}")
        return _checkpoint_response(domain, checkpoint)

    @router.post("/threads/{thread_id}/checkpoints/{checkpoint_id}/checkout", response_model=RuntimeThreadBranchResponse)
    async def checkout_thread_checkpoint(thread_id: str, checkpoint_id: str, payload: RuntimeCheckpointCheckoutRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        branch = domain.services.conversation_version.checkout_checkpoint(
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            title=payload.title,
        )
        if branch is None:
            gateway._raise_http_error(status_code=404, code="checkpoint_not_found", message=f"Unknown checkpoint: {checkpoint_id}")
        return _branch_response(domain, branch)

    @router.post("/endpoint-sessions/resolve", response_model=RuntimeEndpointSessionResolveResponse)
    async def resolve_endpoint_session(payload: RuntimeEndpointSessionResolveRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            workspace = _find_workspace(domain, payload.workspace_id)
            endpoint = _ensure_endpoint_for_session_resolve(domain, payload, workspace.workspace_id)
            address = domain.services.endpoint_address.get_by_address_id(payload.address_id) if payload.address_id else None
            binding, thread = domain.services.endpoint_thread_binding.resolve_thread(
                principal_id=domain.principal.id,
                endpoint_row_id=endpoint.id,
                endpoint_public_id=endpoint.endpoint_id,
                workspace_row_id=workspace.id,
                workspace_public_id=workspace.workspace_id,
                thread_strategy=payload.thread_strategy,
                conversation_key=payload.conversation_key,
                address_row_id=getattr(address, "id", None),
                title=payload.title,
                display_name=payload.display_name,
                explicit_thread_id=payload.explicit_thread_id,
                metadata=payload.metadata,
            )
        except EndpointThreadBindingError as exc:
            status_code = 404 if exc.code in {"explicit_thread_not_found"} else 403 if exc.code in {"explicit_thread_forbidden"} else 400
            gateway._raise_http_error(status_code=status_code, code=exc.code, message=exc.message)
        session = domain.services.session.create_session(
            thread_id=thread.id,
            origin_endpoint_id=getattr(endpoint, "id", None),
            workspace_id=workspace.id,
        )
        _bind_gateway_runtime_session(
            gateway,
            session=session,
            thread=thread,
            workspace=workspace,
            endpoint=endpoint,
            endpoint_type=payload.endpoint_type or getattr(endpoint, "endpoint_type", ""),
            display_name=payload.display_name,
        )
        return RuntimeEndpointSessionResolveResponse(
            thread=_thread_response(thread, workspace.workspace_id),
            session=_session_response(session, thread=thread, workspace=workspace, endpoint=endpoint),
            binding=_binding_response(binding, endpoint=endpoint, thread=thread, workspace=workspace, address=address),
        )

    @router.post("/sessions", response_model=RuntimeSessionResponse)
    async def create_session(payload: RuntimeSessionCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = _require_thread(gateway, domain, payload.thread_id)
        workspace = _find_workspace(domain, payload.resolved_active_workspace_id or getattr(thread, "workspace_id", ""))
        endpoint = _find_endpoint(domain, payload.endpoint_id)
        session = domain.services.session.create_session(
            thread_id=thread.id,
            origin_endpoint_id=getattr(endpoint, "id", None),
            workspace_id=workspace.id,
        )
        _bind_gateway_runtime_session(
            gateway,
            session=session,
            thread=thread,
            workspace=workspace,
            endpoint=endpoint or type("_Endpoint", (), {"endpoint_id": payload.endpoint_id, "provider_type": ""})(),
            endpoint_type=payload.endpoint_type,
            display_name=payload.display_name,
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
        thread = _require_thread(gateway, domain, payload.thread_id)
        workspace = _find_workspace(domain, payload.resolved_active_workspace_id)
        session = domain.services.session.get_by_session_id(payload.session_id) if payload.session_id else None
        endpoint = _find_endpoint(domain, payload.endpoint_id)
        source_id = str(getattr(endpoint, "endpoint_id", "") or payload.endpoint_id or "ui.endpoint")
        metadata = dict(payload.metadata or {})
        if payload.preferred_mode:
            metadata["preferred_mode"] = payload.preferred_mode
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
        conversation_version = getattr(domain.services, "conversation_version", None)
        if conversation_version is not None:
            attached_message = conversation_version.attach_message_to_active_branch(
                thread_row_id=thread.id,
                message_row_id=message.id,
            )
            if attached_message is not None:
                message = attached_message
        _record_context_pool_runtime_user_message(
            domain,
            message=message,
            thread=thread,
            session=session,
            endpoint=endpoint,
            active_workspace=workspace,
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
            "provider_type": str(getattr(endpoint, "provider_type", "") or metadata.get("provider_type") or ""),
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
                "provider_type": str(getattr(endpoint, "provider_type", "") or metadata.get("provider_type") or ""),
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
        thread = _require_thread(gateway, domain, thread_id)
        workspace = domain.services.workspace.get_by_id(getattr(thread, "home_workspace_id", None) or getattr(thread, "workspace_id", None))
        return [
            _message_response(message, thread_id=thread.thread_id, workspace_id=getattr(workspace, "workspace_id", ""))
            for message in domain.services.message.list_messages_for_thread(thread.id)
        ]

    @router.post("/messages/{message_id}/edit-retry", response_model=RuntimeMessageEditRetryResponse)
    async def edit_retry_message(message_id: str, payload: RuntimeMessageEditRetryRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        result = domain.services.conversation_version.edit_retry(
            message_id=message_id,
            new_content=payload.content,
            title=payload.title,
        )
        if result is None:
            gateway._raise_http_error(status_code=404, code="message_not_found_or_not_user", message=f"Unknown user message: {message_id}")
        branch = result["branch"]
        message = result["message"]
        thread = domain.services.thread.get_by_id(getattr(message, "thread_id", None))
        workspace = domain.services.workspace.get_by_id(getattr(message, "active_workspace_id", None) or getattr(thread, "home_workspace_id", None))
        session = domain.services.session.get_by_id(getattr(message, "session_id", None)) if getattr(message, "session_id", None) else None
        return RuntimeMessageEditRetryResponse(
            branch=_branch_response(domain, branch),
            message=_message_response(
                message,
                thread_id=str(getattr(thread, "thread_id", "") or ""),
                workspace_id=str(getattr(workspace, "workspace_id", "") or ""),
                session_id=str(getattr(session, "session_id", "") or ""),
            ),
            replay_status=str(result.get("replay_status") or "branch_created"),
        )

    @router.post("/operations", response_model=RuntimeOperationResponse)
    async def create_operation(payload: RuntimeOperationCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        thread = _require_thread(gateway, domain, payload.thread_id)
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

    @router.post("/sessions/{session_id}/reply-control", response_model=RuntimeReplyControlResult)
    async def reply_control(session_id: str, payload: RuntimeReplyControlRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        normalized_session_id = str(session_id or "").strip()
        action = str(payload.action or "").strip().lower()
        if action not in {"stop", "append_guidance", "regenerate", "rollback"}:
            gateway._raise_http_error(
                status_code=400,
                code="reply_control_action_invalid",
                category="validation",
                message="reply control action must be stop, append_guidance, regenerate, or rollback",
            )
        session_service = getattr(getattr(domain, "services", None), "session", None)
        get_session = getattr(session_service, "get_by_session_id", None)
        if callable(get_session) and get_session(normalized_session_id) is None:
            gateway._raise_http_error(
                status_code=404,
                code="session_not_found",
                category="validation",
                message=f"Unknown session: {normalized_session_id}",
            )
        endpoint = _find_endpoint(domain, payload.endpoint_id)
        source_id = str(getattr(endpoint, "endpoint_id", "") or payload.endpoint_id or "ui.endpoint")
        metadata = dict(payload.metadata or {})
        source_kind = _resolve_runtime_source_kind(
            endpoint_id=source_id,
            endpoint_type=payload.endpoint_type,
            metadata=metadata,
        )
        request_id = str(payload.endpoint_request_id or "").strip()
        event_kwargs = {}
        if request_id:
            event_kwargs["event_id"] = request_id
        await gateway._event_bus.inbound_queue.put(
            InboundEvent(
                session_id=normalized_session_id,
                type=EventType.CONTROL.value,
                role="system",
                content={
                    "action": action,
                    "guidance": payload.guidance,
                    "checkpoint_id": payload.checkpoint_id,
                    "turn_id": payload.turn_id,
                    "stream_id": payload.stream_id,
                },
                source=make_source(
                    source_kind,
                    source_id,
                    endpoint_id=source_id,
                    endpoint_type=payload.endpoint_type,
                    provider_type=str(getattr(endpoint, "provider_type", "") or metadata.get("provider_type") or ""),
                ),
                target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                metadata={
                    "control_kind": "reply_control",
                    "endpoint_id": source_id,
                    "endpoint_type": payload.endpoint_type,
                    "source_kind": source_kind,
                    **metadata,
                },
                **event_kwargs,
            )
        )
        return RuntimeReplyControlResult(
            request_id=request_id,
            session_id=normalized_session_id,
            action=action,
            accepted=True,
            status="queued",
        )

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
        offset: str = "",
        tag: str = "",
        order: str = "time_updated",
    ):
        gateway._require_http_auth(request)
        result = await _call_danxi(
            gateway,
            get_shared_danxi_tools().danxi_list_posts,
            division_id=division_id,
            start_time=start_time,
            length=length,
            offset=offset,
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
