from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from core.config import ConfigManager
from core.exceptions import ConfigError
from core.protocol_schema import build_ui_protocol_schema
from core.source_catalog import SourceCatalogManager

from gateway.models import (
    ConfigEntryResponse,
    ConfigPatchRequest,
    ConfigPatchResponse,
    ConfigSnapshotResponse,
    HealthEnvelopeResponse,
    HealthResponse,
    MemoryClearResponse,
    MemoryGraphResponse,
    MemoryRecordMutationResponse,
    MemoryRecordPatchRequest,
    MemorySnapshotResponse,
    OperatorEndpointResponse,
    OperatorScheduledJobCreateRequest,
    OperatorScheduledJobDeleteResponse,
    OperatorScheduledJobResponse,
    OperatorScheduledJobUpdateRequest,
    OperatorSourceProfileResponse,
    OperatorWorkspaceCreateRequest,
    OperatorWorkspaceUpdateRequest,
    OperatorWorkspaceResponse,
    UiProtocolSchemaEnvelopeResponse,
    UiProtocolSchemaResponse,
)
from service_runtime.models import RuntimeErrorCategory


def _workspace_response(workspace) -> OperatorWorkspaceResponse:
    governance = gateway_workspace_governance(workspace)
    return OperatorWorkspaceResponse(
        workspace_id=workspace.workspace_id,
        title=workspace.title,
        status=workspace.status,
        base_mode=workspace.base_mode,
        description=governance["description"],
        prompt_overlay=governance["prompt_overlay"],
        default_execution_target=governance["default_execution_target"],
        tool_policy=governance["tool_policy"],
        allowed_tool_ids=governance["allowed_tool_ids"],
        preferred_target_endpoint_ids=governance["preferred_target_endpoint_ids"],
        preferred_endpoint_provider_types=governance["preferred_endpoint_provider_types"],
        preferred_source_profiles=governance["preferred_source_profiles"],
        tool_target_routing_policy=governance["tool_target_routing_policy"],
        memory_ranking_policy=governance["memory_ranking_policy"],
        tool_routing_overrides=governance["tool_routing_overrides"],
    )


def _scheduled_job_response(domain, job) -> OperatorScheduledJobResponse:
    workspace_id = ""
    if getattr(job, "workspace_id", None) is not None:
        workspace = domain.services.workspace.get_by_id(job.workspace_id)
        workspace_id = str(getattr(workspace, "workspace_id", "") or "")
    return OperatorScheduledJobResponse(
        job_id=job.job_id,
        kind=job.kind,
        name=job.name,
        workspace_id=workspace_id,
        singleton_key=str(getattr(job, "singleton_key", "") or ""),
        enabled=bool(job.enabled),
        deletable=bool(job.deletable),
        editable_fields=[str(item) for item in (job.editable_fields or [])],
        trigger_type=job.trigger_type,
        trigger_config=dict(job.trigger_config or {}),
        timezone=job.timezone,
        action_ref=job.action_ref,
        run_template=dict(job.run_template or {}),
        execution_policy=dict(job.execution_policy or {}),
        delivery_policy=dict(job.delivery_policy or {}),
        concurrency_policy=dict(job.concurrency_policy or {}),
        misfire_policy=dict(job.misfire_policy or {}),
        metadata=dict(getattr(job, "meta", {}) or {}),
        created_at=job.created_at.isoformat() if getattr(job, "created_at", None) is not None else "",
        updated_at=job.updated_at.isoformat() if getattr(job, "updated_at", None) is not None else "",
    )


def _interval_trigger_config(trigger_config: dict | None, interval_seconds: int | None) -> dict:
    config = dict(trigger_config or {})
    if interval_seconds is not None:
        config["type"] = "interval"
        config["interval_seconds"] = int(interval_seconds)
    return config


def gateway_workspace_governance(workspace) -> dict:
    from core.services.workspace_service import WorkspaceService

    return WorkspaceService.get_governance_view(workspace)


def _load_source_profile_catalog() -> dict[str, dict]:
    manager = SourceCatalogManager(ConfigManager())
    profiles = manager.get_source_profiles()
    return {
        str(name).strip(): dict(payload or {})
        for name, payload in profiles.items()
        if str(name).strip()
    }


def _validate_source_profiles(gateway, values: list[str] | None) -> list[str]:
    requested = []
    seen: set[str] = set()
    for item in values or []:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        requested.append(normalized)
    available = _load_source_profile_catalog()
    invalid = [item for item in requested if item not in available]
    if invalid:
        gateway._raise_http_error(
            status_code=400,
            code="invalid_source_profile",
            category=RuntimeErrorCategory.VALIDATION.value,
            message=f"未知 source profile: {', '.join(invalid)}",
        )
    return requested


def _validate_memory_ranking_policy(gateway, value: str | None) -> str:
    normalized = str(value or "workspace_first").strip() or "workspace_first"
    if normalized not in {"workspace_first"}:
        gateway._raise_http_error(
            status_code=400,
            code="invalid_memory_ranking_policy",
            category=RuntimeErrorCategory.VALIDATION.value,
            message=f"未知 memory ranking policy: {normalized}",
        )
    return normalized


def build_operator_router(gateway) -> APIRouter:
    router = APIRouter(prefix="/operator", tags=["operator"])

    @router.get("/schema/ui", response_model=UiProtocolSchemaEnvelopeResponse)
    async def get_operator_ui_schema(request: Request):
        gateway._require_http_auth(request)
        return UiProtocolSchemaEnvelopeResponse(
            schema_name="meetyou.http.v1",
            ui_schema=UiProtocolSchemaResponse(**build_ui_protocol_schema()),
        )

    @router.get("/config", response_model=ConfigSnapshotResponse)
    async def get_operator_config(request: Request):
        gateway._require_http_auth(request)
        if gateway._dependencies.core_domain is not None:
            items = gateway._dependencies.core_domain.services.config_state.get_snapshot_view()
        else:
            items = await gateway._resolve(gateway._dependencies.config_snapshot_getter)
        return ConfigSnapshotResponse(
            items={
                key: ConfigEntryResponse(**value)
                for key, value in items.items()
            }
        )

    @router.get("/config/{key}", response_model=ConfigEntryResponse)
    async def get_operator_config_item(key: str, request: Request):
        gateway._require_http_auth(request)
        try:
            if gateway._dependencies.core_domain is not None:
                item = gateway._dependencies.core_domain.services.config_state.get_entry_view(key)
                if item is None:
                    raise KeyError(key)
            else:
                item = await gateway._resolve(gateway._dependencies.config_item_getter, key)
        except Exception as exc:
            gateway._raise_http_error(
                status_code=404,
                code="config_not_found",
                category=RuntimeErrorCategory.DEPENDENCY.value,
                message=str(exc),
                details={"key": key},
            )
        return ConfigEntryResponse(**item)

    @router.patch("/config", response_model=ConfigPatchResponse)
    async def patch_operator_config(http_request: Request, request: ConfigPatchRequest):
        gateway._require_http_auth(http_request)
        try:
            result = await gateway._resolve(gateway._dependencies.config_updater, request.updates)
        except (ConfigError, ValueError) as exc:
            gateway._raise_http_error(
                status_code=400,
                code="invalid_config_update",
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
            )
        return ConfigPatchResponse(**result)

    @router.get("/memory", response_model=MemorySnapshotResponse)
    async def get_operator_memory(
        request: Request,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
    ):
        gateway._require_http_auth(request)
        if gateway._dependencies.core_domain is not None:
            config = gateway._dependencies.core_domain.services.config_state.get_snapshot_view()
            payload = gateway._dependencies.core_domain.services.memory_state.build_snapshot_view(
                principal_id=gateway._dependencies.core_domain.principal.id,
                source_id=source_id,
                session_id=session_id,
                include_invalidated=include_invalidated,
                embedding_model=str(config.get("embedding_model", {}).get("value") or ""),
                embedding_api_url=str(config.get("embedding_api_url", {}).get("value") or ""),
            )
        else:
            payload = await gateway._resolve(
                gateway._dependencies.memory_snapshot_getter,
                source_id=source_id,
                session_id=session_id,
                include_invalidated=include_invalidated,
            )
        return MemorySnapshotResponse(**payload)

    @router.get("/memory/graph", response_model=MemoryGraphResponse)
    async def get_operator_memory_graph(
        request: Request,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
    ):
        gateway._require_http_auth(request)
        if gateway._dependencies.core_domain is not None:
            config = gateway._dependencies.core_domain.services.config_state.get_snapshot_view()
            payload = gateway._dependencies.core_domain.services.memory_state.build_graph_view(
                principal_id=gateway._dependencies.core_domain.principal.id,
                source_id=source_id,
                session_id=session_id,
                include_invalidated=include_invalidated,
                embedding_model=str(config.get("embedding_model", {}).get("value") or ""),
                embedding_api_url=str(config.get("embedding_api_url", {}).get("value") or ""),
            )
        else:
            payload = await gateway._resolve(
                gateway._dependencies.memory_graph_getter,
                source_id=source_id,
                session_id=session_id,
                include_invalidated=include_invalidated,
            )
        return MemoryGraphResponse(**payload)

    @router.delete("/memory", response_model=MemoryClearResponse)
    async def clear_operator_memory(request: Request):
        gateway._require_http_auth(request)
        payload = await gateway._resolve(gateway._dependencies.memory_clearer)
        return MemoryClearResponse(**payload)

    @router.patch("/memory/records/{memory_id}", response_model=MemoryRecordMutationResponse)
    async def update_operator_memory_record_status(memory_id: str, http_request: Request, request: MemoryRecordPatchRequest):
        gateway._require_http_auth(http_request)
        try:
            payload = await gateway._resolve(gateway._dependencies.memory_record_status_updater, memory_id, request.status)
        except KeyError:
            gateway._raise_http_error(
                status_code=404,
                code="memory_record_not_found",
                category=RuntimeErrorCategory.VALIDATION.value,
                message="Memory record not found.",
                details={"memory_id": memory_id},
            )
        except ValueError as exc:
            gateway._raise_http_error(
                status_code=400,
                code="memory_record_update_invalid",
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
                details={"memory_id": memory_id, "status": request.status},
            )
        return MemoryRecordMutationResponse(**payload)

    @router.delete("/memory/records/{memory_id}", response_model=MemoryRecordMutationResponse)
    async def delete_operator_memory_record(memory_id: str, request: Request):
        gateway._require_http_auth(request)
        try:
            payload = await gateway._resolve(gateway._dependencies.memory_record_deleter, memory_id)
        except KeyError:
            gateway._raise_http_error(
                status_code=404,
                code="memory_record_not_found",
                category=RuntimeErrorCategory.VALIDATION.value,
                message="Memory record not found.",
                details={"memory_id": memory_id},
            )
        except ValueError as exc:
            gateway._raise_http_error(
                status_code=400,
                code="memory_record_delete_invalid",
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
                details={"memory_id": memory_id},
            )
        return MemoryRecordMutationResponse(**payload)

    @router.get("/health", response_model=HealthEnvelopeResponse)
    async def operator_health(request: Request):
        gateway._require_http_auth(request)
        payload = await gateway._resolve(gateway._dependencies.health_getter) if gateway._dependencies.health_getter is not None else {}
        if isinstance(payload, HealthResponse):
            health_payload = payload
        elif hasattr(payload, "model_dump"):
            health_payload = HealthResponse(**payload.model_dump())
        else:
            health_payload = HealthResponse(**payload)
        return HealthEnvelopeResponse(schema_name="meetyou.http.v1", health=health_payload)

    @router.get("/clients")
    async def list_clients(request: Request):
        gateway._require_http_auth(request)
        return JSONResponse(
            status_code=410,
            content={
                "schema": "meetyou.http.v1",
                "kind": "error",
                "error": {
                    "code": "operator_clients_removed",
                    "message": "Operator clients are removed in V4. Use operator endpoints.",
                    "details": {
                        "legacy_path": "/operator/clients",
                        "replacement_path": "/operator/endpoints",
                    },
                },
            },
        )

    @router.get("/endpoints", response_model=list[OperatorEndpointResponse])
    async def list_endpoints(request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        snapshots = await gateway.endpoint_ws_manager.snapshot()
        by_endpoint: dict[str, list[dict]] = {}
        for item in snapshots:
            endpoint_id = str(item.get("endpoint_id") or "").strip()
            if endpoint_id:
                by_endpoint.setdefault(endpoint_id, []).append(dict(item))
        rows = []
        for endpoint in domain.services.endpoint.list_all():
            endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "")
            connections = by_endpoint.get(endpoint_id, [])
            last_seen_at = ""
            if connections:
                last_seen_at = str(connections[-1].get("updated_at") or connections[-1].get("connected_at") or "")
            elif getattr(endpoint, "updated_at", None) is not None:
                last_seen_at = endpoint.updated_at.isoformat()
            rows.append(
                OperatorEndpointResponse(
                    endpoint_id=endpoint_id,
                    endpoint_type=str(getattr(endpoint, "endpoint_type", "") or ""),
                    provider_type=str(getattr(endpoint, "provider_type", "") or ""),
                    transport_type=str(getattr(endpoint, "transport_type", "") or ""),
                    status=str(getattr(endpoint, "status", "") or ""),
                    connected=bool(connections),
                    connection_count=len(connections),
                    workspace_ids=list(getattr(endpoint, "workspace_scope", []) or []),
                    capability_count=len(domain.services.endpoint_capability.list_for_endpoint(endpoint_row_id=endpoint.id)),
                    labels=list(getattr(endpoint, "labels", []) or []),
                    last_seen_at=last_seen_at,
                )
            )
        return rows

    @router.get("/scheduled-jobs", response_model=list[OperatorScheduledJobResponse])
    async def list_scheduled_jobs(request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        return [_scheduled_job_response(domain, job) for job in domain.services.scheduler.list_jobs()]

    @router.post("/scheduled-jobs", response_model=OperatorScheduledJobResponse)
    async def create_scheduled_job(payload: OperatorScheduledJobCreateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        workspace_row_id = None
        if payload.workspace_id:
            workspace = domain.services.workspace.get_by_workspace_id(payload.workspace_id)
            if workspace is None:
                gateway._raise_http_error(
                    status_code=404,
                    code="workspace_not_found",
                    category=RuntimeErrorCategory.VALIDATION.value,
                    message=f"Unknown workspace: {payload.workspace_id}",
                )
            workspace_row_id = workspace.id
        try:
            job = domain.services.scheduler.create_job(
                job_id=payload.job_id,
                kind=payload.kind,
                name=payload.name,
                workspace_id=workspace_row_id,
                singleton_key=payload.singleton_key,
                enabled=payload.enabled,
                trigger_type=payload.trigger_type,
                trigger_config=_interval_trigger_config(payload.trigger_config, payload.interval_seconds),
                timezone=payload.timezone,
                action_ref=payload.action_ref,
                run_template=payload.run_template,
                execution_policy=payload.execution_policy,
                delivery_policy=payload.delivery_policy,
                concurrency_policy=payload.concurrency_policy,
                misfire_policy=payload.misfire_policy,
                metadata=payload.metadata,
            )
        except Exception as exc:
            gateway._raise_http_error(
                status_code=400,
                code="scheduled_job_create_failed",
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
            )
        return _scheduled_job_response(domain, job)

    @router.patch("/scheduled-jobs/{job_id}", response_model=OperatorScheduledJobResponse)
    async def update_scheduled_job(job_id: str, payload: OperatorScheduledJobUpdateRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        updates = payload.model_dump(exclude_unset=True)
        trigger_config = updates.pop("trigger_config", None)
        interval_seconds = updates.pop("interval_seconds", None)
        if trigger_config is not None or interval_seconds is not None:
            updates["trigger_config"] = _interval_trigger_config(trigger_config, interval_seconds)
        try:
            job = domain.services.scheduler.update_job(job_id=job_id, **updates)
        except Exception as exc:
            gateway._raise_http_error(
                status_code=400,
                code="scheduled_job_update_failed",
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
            )
        if job is None:
            gateway._raise_http_error(
                status_code=404,
                code="scheduled_job_not_found",
                category=RuntimeErrorCategory.VALIDATION.value,
                message=f"Unknown scheduled job: {job_id}",
            )
        return _scheduled_job_response(domain, job)

    @router.delete("/scheduled-jobs/{job_id}", response_model=OperatorScheduledJobDeleteResponse)
    async def delete_scheduled_job(job_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            deleted = domain.services.scheduler.delete_job(job_id=job_id)
        except ValueError as exc:
            gateway._raise_http_error(
                status_code=400,
                code="scheduled_job_not_deletable",
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
            )
        if not deleted:
            gateway._raise_http_error(
                status_code=404,
                code="scheduled_job_not_found",
                category=RuntimeErrorCategory.VALIDATION.value,
                message=f"Unknown scheduled job: {job_id}",
            )
        return OperatorScheduledJobDeleteResponse(job_id=job_id, deleted=True)

    @router.get("/workspaces", response_model=list[OperatorWorkspaceResponse])
    async def list_workspaces(request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        return [_workspace_response(workspace) for workspace in domain.services.workspace.list_workspaces()]

    @router.get("/source-profiles", response_model=list[OperatorSourceProfileResponse])
    async def list_source_profiles(request: Request):
        gateway._require_http_auth(request)
        profiles = _load_source_profile_catalog()
        return [
            OperatorSourceProfileResponse(
                profile_name=name,
                label=str(payload.get("label") or "").strip(),
                description=str(payload.get("description") or "").strip(),
                official_only=bool(payload.get("official_only", False)),
                default_freshness=str(payload.get("default_freshness") or "").strip(),
            )
            for name, payload in profiles.items()
        ]

    @router.post("/workspaces", response_model=OperatorWorkspaceResponse)
    async def create_workspace(http_request: Request, payload: OperatorWorkspaceCreateRequest):
        gateway._require_http_auth(http_request)
        domain = gateway._require_core_domain()
        workspace_key = str(payload.workspace_id or "").strip()
        if not workspace_key:
            gateway._raise_http_error(
                status_code=400,
                code="workspace_id_required",
                category=RuntimeErrorCategory.VALIDATION.value,
                message="workspace_id 为必填字段",
            )
        title = str(payload.title or "").strip() or workspace_key.replace("-", " ").replace("_", " ").title()
        workspace = domain.services.workspace.ensure_workspace(
            workspace_id=workspace_key,
            principal_id=domain.principal.id,
            title=title,
            description=str(payload.description or "").strip(),
            base_mode=str(payload.base_mode or "general").strip() or "general",
            prompt_overlay=str(payload.prompt_overlay or "").strip(),
            default_execution_target=str(payload.default_execution_target or "core_only").strip() or "core_only",
            metadata={
                "tool_policy": str(payload.tool_policy or "").strip(),
                "allowed_tool_ids": list(payload.allowed_tool_ids or []),
                "preferred_target_endpoint_ids": list(payload.preferred_target_endpoint_ids or []),
                "preferred_endpoint_provider_types": list(payload.preferred_endpoint_provider_types or []),
                "preferred_source_profiles": _validate_source_profiles(gateway, payload.preferred_source_profiles),
                "tool_target_routing_policy": str(payload.tool_target_routing_policy or "").strip(),
                "memory_ranking_policy": _validate_memory_ranking_policy(gateway, payload.memory_ranking_policy),
                "tool_routing_overrides": dict(payload.tool_routing_overrides or {}),
            },
        )
        return _workspace_response(workspace)

    @router.patch("/workspaces/{workspace_id}", response_model=OperatorWorkspaceResponse)
    async def update_workspace(http_request: Request, workspace_id: str, payload: OperatorWorkspaceUpdateRequest):
        gateway._require_http_auth(http_request)
        domain = gateway._require_core_domain()
        workspace = domain.services.workspace.get_by_workspace_id(workspace_id)
        if workspace is None:
            gateway._raise_http_error(
                status_code=404,
                code="workspace_not_found",
                category=RuntimeErrorCategory.VALIDATION.value,
                message=f"未知 workspace: {workspace_id}",
            )
        metadata: dict[str, object] = {}
        if payload.preferred_source_profiles is not None:
            metadata["preferred_source_profiles"] = _validate_source_profiles(gateway, payload.preferred_source_profiles)
        if payload.memory_ranking_policy is not None:
            metadata["memory_ranking_policy"] = _validate_memory_ranking_policy(gateway, payload.memory_ranking_policy)
        updated = domain.services.workspace.update_workspace(
            workspace_id=workspace_id,
            base_mode=payload.base_mode,
            metadata=metadata if metadata else None,
        )
        return _workspace_response(updated or workspace)

    return router
