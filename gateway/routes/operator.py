from __future__ import annotations

from fastapi import APIRouter, Request
from core.config import ConfigManager
from core.exceptions import ConfigError
from core.protocol_schema import build_ui_protocol_schema
from core.services.endpoint_service import endpoint_hidden_from_operator
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
    OperatorEndpointMembershipRequest,
    OperatorMembershipMutationResponse,
    OperatorPrimaryWorkspaceRequest,
    OperatorScheduledJobCreateRequest,
    OperatorScheduledJobDeleteResponse,
    OperatorScheduledJobResponse,
    OperatorScheduledJobUpdateRequest,
    OperatorSkillDetailResponse,
    OperatorSkillResponse,
    OperatorSourceProfileResponse,
    OperatorWorkspaceCreateRequest,
    OperatorWorkspaceUpdateRequest,
    OperatorWorkspaceResponse,
    OperatorWorkspaceTopologyResponse,
    OperatorTopologyAddressResponse,
    OperatorTopologyEndpointResponse,
    OperatorTopologyMembershipResponse,
    OperatorTopologyWorkspaceResponse,
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


def _list_workspace_rows(workspace_service, *, include_archived: bool = False):
    try:
        return workspace_service.list_workspaces(include_archived=include_archived)
    except TypeError:
        return workspace_service.list_workspaces()


def _membership_response(domain, membership) -> OperatorTopologyMembershipResponse | None:
    workspace = domain.services.workspace.get_by_id(getattr(membership, "workspace_id", None))
    workspace_id = str(getattr(workspace, "workspace_id", "") or "").strip()
    if not workspace_id:
        return None
    return OperatorTopologyMembershipResponse(
        workspace_id=workspace_id,
        primary=bool(getattr(membership, "is_primary", False)),
        role=str(getattr(membership, "membership_role", "") or "member"),
        enabled=bool(getattr(membership, "enabled", True)),
        source=str(getattr(membership, "source", "") or "core"),
    )


def _membership_payloads(domain, rows) -> list[OperatorTopologyMembershipResponse]:
    payloads: list[OperatorTopologyMembershipResponse] = []
    for row in rows or []:
        payload = _membership_response(domain, row)
        if payload is not None:
            payloads.append(payload)
    return payloads


def _membership_workspace_ids(payloads: list[OperatorTopologyMembershipResponse]) -> list[str]:
    return [item.workspace_id for item in payloads if item.enabled]


def _membership_primary_workspace_id(payloads: list[OperatorTopologyMembershipResponse]) -> str:
    primary = next((item for item in payloads if item.enabled and item.primary), None)
    if primary is not None:
        return primary.workspace_id
    return next((item.workspace_id for item in payloads if item.enabled), "")


def _endpoint_display_name(endpoint, connections: list[dict]) -> str:
    meta = dict(getattr(endpoint, "meta", {}) or {})
    provider = connections[0].get("provider") if connections and isinstance(connections[0].get("provider"), dict) else {}
    meta_provider = meta.get("provider") if isinstance(meta.get("provider"), dict) else {}
    return str(
        provider.get("display_name")
        or meta.get("display_name")
        or meta_provider.get("display_name")
        or getattr(endpoint, "endpoint_id", "")
        or ""
    )


def _last_seen_at(endpoint, connections: list[dict]) -> str:
    if connections:
        return str(connections[-1].get("updated_at") or connections[-1].get("connected_at") or "")
    updated_at = getattr(endpoint, "updated_at", None)
    return updated_at.isoformat() if updated_at is not None else ""


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


def _validate_skill_type(gateway, value: str | None) -> str:
    normalized = str(value or "all").strip().lower() or "all"
    if normalized not in {"all", "mode", "reusable"}:
        gateway._raise_http_error(
            status_code=400,
            code="invalid_skill_type",
            category=RuntimeErrorCategory.VALIDATION.value,
            message=f"未知 skill_type: {normalized}",
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

    @router.get("/skills", response_model=list[OperatorSkillResponse])
    async def list_operator_skills(request: Request, skill_type: str = "all", query: str = ""):
        gateway._require_http_auth(request)
        normalized_skill_type = _validate_skill_type(gateway, skill_type)
        getter = gateway._dependencies.skill_list_getter
        if getter is not None:
            payload = await gateway._resolve(
                getter,
                skill_type=normalized_skill_type,
                query=str(query or "").strip(),
            )
        else:
            from core.assistant_modes import AssistantModeManager

            payload = AssistantModeManager(ConfigManager()).list_skills(
                skill_type=normalized_skill_type,
                query=str(query or "").strip(),
            )
        return [OperatorSkillResponse(**dict(item)) for item in payload]

    @router.get("/skills/{skill_id}", response_model=OperatorSkillDetailResponse)
    async def get_operator_skill(skill_id: str, request: Request):
        gateway._require_http_auth(request)
        getter = gateway._dependencies.skill_getter
        if getter is not None:
            payload = await gateway._resolve(getter, skill_id)
        else:
            from core.assistant_modes import AssistantModeManager

            payload = AssistantModeManager(ConfigManager()).load_skill(skill_id)
        if payload is None:
            gateway._raise_http_error(
                status_code=404,
                code="skill_not_found",
                category=RuntimeErrorCategory.DEPENDENCY.value,
                message=f"未知 SKILL: {skill_id}",
                details={"skill_id": skill_id},
            )
        return OperatorSkillDetailResponse(**dict(payload))

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

    @router.get("/endpoints", response_model=list[OperatorEndpointResponse])
    async def list_endpoints(request: Request, include_archived: bool = False):
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
            if not include_archived and endpoint_hidden_from_operator(endpoint):
                continue
            endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "")
            connections = by_endpoint.get(endpoint_id, [])
            connected = bool(connections)
            membership_service = getattr(domain.services, "endpoint_workspace_membership", None)
            memberships = (
                _membership_payloads(
                    domain,
                    membership_service.list_for_endpoint(endpoint_row_id=endpoint.id) if membership_service is not None else [],
                )
                if membership_service is not None
                else []
            )
            workspace_ids = _membership_workspace_ids(memberships) or list(getattr(endpoint, "workspace_scope", []) or [])
            rows.append(
                OperatorEndpointResponse(
                    endpoint_id=endpoint_id,
                    endpoint_type=str(getattr(endpoint, "endpoint_type", "") or ""),
                    provider_type=str(getattr(endpoint, "provider_type", "") or ""),
                    transport_type=str(getattr(endpoint, "transport_type", "") or ""),
                    status="online" if connected else "offline",
                    connected=connected,
                    connection_count=len(connections),
                    workspace_ids=workspace_ids,
                    capability_count=len(domain.services.endpoint_capability.list_for_endpoint(endpoint_row_id=endpoint.id)),
                    labels=list(getattr(endpoint, "labels", []) or []),
                    last_seen_at=_last_seen_at(endpoint, connections),
                )
            )
        return rows

    @router.get("/workspace-topology", response_model=OperatorWorkspaceTopologyResponse)
    async def get_workspace_topology(request: Request, include_archived: bool = False):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        snapshots = await gateway.endpoint_ws_manager.snapshot()
        by_endpoint: dict[str, list[dict]] = {}
        for item in snapshots:
            endpoint_id = str(item.get("endpoint_id") or "").strip()
            if endpoint_id:
                by_endpoint.setdefault(endpoint_id, []).append(dict(item))

        workspace_rows = _list_workspace_rows(domain.services.workspace, include_archived=include_archived)
        workspace_status = {str(getattr(row, "workspace_id", "") or ""): str(getattr(row, "status", "") or "") for row in workspace_rows}
        workspace_counts = {str(getattr(row, "workspace_id", "") or ""): {"total": 0, "online": 0} for row in workspace_rows}

        endpoint_payloads: list[OperatorTopologyEndpointResponse] = []
        endpoint_membership_service = getattr(domain.services, "endpoint_workspace_membership", None)
        visible_endpoint_row_ids = set()
        for endpoint in domain.services.endpoint.list_all():
            if not include_archived and endpoint_hidden_from_operator(endpoint):
                continue
            endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "")
            visible_endpoint_row_ids.add(getattr(endpoint, "id", None))
            connections = by_endpoint.get(endpoint_id, [])
            memberships = _membership_payloads(
                domain,
                endpoint_membership_service.list_for_endpoint(endpoint_row_id=endpoint.id) if endpoint_membership_service is not None else [],
            )
            workspace_ids = _membership_workspace_ids(memberships) or list(getattr(endpoint, "workspace_scope", []) or [])
            if not include_archived:
                workspace_ids = [item for item in workspace_ids if workspace_status.get(item, "active") != "archived"]
                memberships = [item for item in memberships if workspace_status.get(item.workspace_id, "active") != "archived"]
            connected = bool(connections)
            for workspace_id in workspace_ids:
                if workspace_id not in workspace_counts:
                    workspace_counts[workspace_id] = {"total": 0, "online": 0}
                workspace_counts[workspace_id]["total"] += 1
                if connected:
                    workspace_counts[workspace_id]["online"] += 1
            capabilities = [
                capability
                for capability in domain.services.endpoint_capability.list_for_endpoint(endpoint_row_id=endpoint.id)
                if getattr(capability, "enabled", True)
            ]
            meta = dict(getattr(endpoint, "meta", {}) or {})
            endpoint_payloads.append(
                OperatorTopologyEndpointResponse(
                    endpoint_id=endpoint_id,
                    display_name=_endpoint_display_name(endpoint, connections),
                    endpoint_type=str(getattr(endpoint, "endpoint_type", "") or ""),
                    provider_type=str(getattr(endpoint, "provider_type", "") or ""),
                    transport_type=str(getattr(endpoint, "transport_type", "") or ""),
                    status="online" if connected else "offline",
                    connected=connected,
                    connection_count=len(connections),
                    workspace_ids=workspace_ids,
                    primary_workspace_id=_membership_primary_workspace_id(memberships)
                    or str(meta.get("primary_workspace_id") or ""),
                    provider_declared_workspace_ids=[
                        str(item or "").strip()
                        for item in (meta.get("provider_declared_workspace_ids") or [])
                        if str(item or "").strip()
                    ],
                    capability_count=len(capabilities),
                    executable_tools=[str(getattr(capability, "tool_key", "") or "") for capability in capabilities],
                    labels=list(getattr(endpoint, "labels", []) or []),
                    last_seen_at=_last_seen_at(endpoint, connections),
                    core_owned=str(getattr(endpoint, "provider_type", "") or "").strip().lower() == "core",
                    memberships=memberships,
                )
            )

        address_payloads: list[OperatorTopologyAddressResponse] = []
        address_membership_service = getattr(domain.services, "endpoint_address_workspace_membership", None)
        for address in domain.services.endpoint_address.list_addresses() if hasattr(domain.services.endpoint_address, "list_addresses") else []:
            endpoint = domain.services.endpoint.get_by_id(getattr(address, "endpoint_id", None))
            if not include_archived and getattr(endpoint, "id", None) not in visible_endpoint_row_ids:
                continue
            memberships = _membership_payloads(
                domain,
                address_membership_service.list_for_address(address_row_id=address.id) if address_membership_service is not None else [],
            )
            workspace_ids = _membership_workspace_ids(memberships) or list(getattr(address, "workspace_scope", []) or [])
            if not include_archived:
                workspace_ids = [item for item in workspace_ids if workspace_status.get(item, "active") != "archived"]
                memberships = [item for item in memberships if workspace_status.get(item.workspace_id, "active") != "archived"]
            address_payloads.append(
                OperatorTopologyAddressResponse(
                    address_id=str(getattr(address, "address_id", "") or ""),
                    endpoint_id=str(getattr(endpoint, "endpoint_id", "") or ""),
                    display_name=str(getattr(address, "display_name", "") or getattr(address, "external_ref", "") or ""),
                    provider_type=str(getattr(address, "provider_type", "") or ""),
                    address_type=str(getattr(address, "address_type", "") or ""),
                    status=str(getattr(address, "status", "") or ""),
                    workspace_ids=workspace_ids,
                    primary_workspace_id=_membership_primary_workspace_id(memberships)
                    or str((getattr(address, "meta", {}) or {}).get("primary_workspace_id") or ""),
                    capabilities=list(getattr(address, "capabilities", []) or []),
                    memberships=memberships,
                )
            )

        workspaces = [
            OperatorTopologyWorkspaceResponse(
                workspace_id=str(getattr(workspace, "workspace_id", "") or ""),
                title=str(getattr(workspace, "title", "") or ""),
                status=str(getattr(workspace, "status", "") or ""),
                base_mode=str(getattr(workspace, "base_mode", "") or "general"),
                description=str(getattr(workspace, "description", "") or ""),
                endpoint_count=workspace_counts.get(str(getattr(workspace, "workspace_id", "") or ""), {}).get("total", 0),
                online_endpoint_count=workspace_counts.get(str(getattr(workspace, "workspace_id", "") or ""), {}).get("online", 0),
            )
            for workspace in workspace_rows
        ]
        return OperatorWorkspaceTopologyResponse(
            workspaces=workspaces,
            endpoints=endpoint_payloads,
            addresses=address_payloads,
        )

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
    async def list_workspaces(request: Request, include_archived: bool = False):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        return [
            _workspace_response(workspace)
            for workspace in _list_workspace_rows(domain.services.workspace, include_archived=include_archived)
        ]

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
            default_execution_target=str(payload.default_execution_target or "core.local").strip() or "core.local",
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
        current_governance = gateway_workspace_governance(workspace)
        metadata: dict[str, object] = {
            "tool_policy": current_governance["tool_policy"],
            "allowed_tool_ids": current_governance["allowed_tool_ids"],
            "preferred_target_endpoint_ids": current_governance["preferred_target_endpoint_ids"],
            "preferred_endpoint_provider_types": current_governance["preferred_endpoint_provider_types"],
            "preferred_source_profiles": current_governance["preferred_source_profiles"],
            "tool_target_routing_policy": current_governance["tool_target_routing_policy"],
            "memory_ranking_policy": current_governance["memory_ranking_policy"],
            "tool_routing_overrides": current_governance["tool_routing_overrides"],
        }
        metadata_changed = False
        if payload.tool_policy is not None:
            metadata["tool_policy"] = str(payload.tool_policy or "").strip()
            metadata_changed = True
        if payload.allowed_tool_ids is not None:
            metadata["allowed_tool_ids"] = list(payload.allowed_tool_ids or [])
            metadata_changed = True
        if payload.preferred_target_endpoint_ids is not None:
            metadata["preferred_target_endpoint_ids"] = list(payload.preferred_target_endpoint_ids or [])
            metadata_changed = True
        if payload.preferred_endpoint_provider_types is not None:
            metadata["preferred_endpoint_provider_types"] = list(payload.preferred_endpoint_provider_types or [])
            metadata_changed = True
        if payload.preferred_source_profiles is not None:
            metadata["preferred_source_profiles"] = _validate_source_profiles(gateway, payload.preferred_source_profiles)
            metadata_changed = True
        if payload.tool_target_routing_policy is not None:
            metadata["tool_target_routing_policy"] = str(payload.tool_target_routing_policy or "").strip()
            metadata_changed = True
        if payload.memory_ranking_policy is not None:
            metadata["memory_ranking_policy"] = _validate_memory_ranking_policy(gateway, payload.memory_ranking_policy)
            metadata_changed = True
        if payload.tool_routing_overrides is not None:
            metadata["tool_routing_overrides"] = dict(payload.tool_routing_overrides or {})
            metadata_changed = True
        updated = domain.services.workspace.update_workspace(
            workspace_id=workspace_id,
            title=payload.title,
            description=payload.description,
            prompt_overlay=payload.prompt_overlay,
            base_mode=payload.base_mode,
            default_execution_target=payload.default_execution_target,
            metadata=metadata if metadata_changed else None,
        )
        return _workspace_response(updated or workspace)

    @router.delete("/workspaces/{workspace_id}", response_model=OperatorWorkspaceResponse)
    async def archive_workspace(workspace_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            workspace = domain.services.workspace.archive_workspace(workspace_id=workspace_id)
        except ValueError as exc:
            gateway._raise_http_error(
                status_code=400,
                code="workspace_archive_forbidden",
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
            )
        if workspace is None:
            gateway._raise_http_error(
                status_code=404,
                code="workspace_not_found",
                category=RuntimeErrorCategory.VALIDATION.value,
                message=f"Unknown workspace: {workspace_id}",
            )
        return _workspace_response(workspace)

    @router.post("/workspaces/{workspace_id}/restore", response_model=OperatorWorkspaceResponse)
    async def restore_workspace(workspace_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        workspace = domain.services.workspace.restore_workspace(workspace_id=workspace_id)
        if workspace is None:
            gateway._raise_http_error(
                status_code=404,
                code="workspace_not_found",
                category=RuntimeErrorCategory.VALIDATION.value,
                message=f"Unknown workspace: {workspace_id}",
            )
        return _workspace_response(workspace)

    @router.post("/endpoints/{endpoint_id}/workspaces", response_model=OperatorMembershipMutationResponse)
    async def add_endpoint_workspace(endpoint_id: str, payload: OperatorEndpointMembershipRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            result = domain.services.endpoint_workspace_membership.add_workspace(
                endpoint_id=endpoint_id,
                workspace_id=payload.workspace_id,
                make_primary=payload.make_primary,
            )
        except KeyError as exc:
            gateway._raise_http_error(
                status_code=404,
                code=str(exc.args[0] if exc.args else "membership_target_not_found"),
                category=RuntimeErrorCategory.VALIDATION.value,
                message="Endpoint or workspace was not found.",
            )
        except ValueError as exc:
            gateway._raise_http_error(
                status_code=400,
                code=str(exc),
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
            )
        return OperatorMembershipMutationResponse(
            target_type="endpoint",
            target_id=result["endpoint_id"],
            workspace_ids=result["workspace_ids"],
            primary_workspace_id=result["primary_workspace_id"],
        )

    @router.delete("/endpoints/{endpoint_id}/workspaces/{workspace_id}", response_model=OperatorMembershipMutationResponse)
    async def remove_endpoint_workspace(endpoint_id: str, workspace_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            result = domain.services.endpoint_workspace_membership.remove_workspace(
                endpoint_id=endpoint_id,
                workspace_id=workspace_id,
            )
        except KeyError as exc:
            gateway._raise_http_error(
                status_code=404,
                code=str(exc.args[0] if exc.args else "membership_target_not_found"),
                category=RuntimeErrorCategory.VALIDATION.value,
                message="Endpoint or workspace was not found.",
            )
        except ValueError as exc:
            gateway._raise_http_error(
                status_code=400,
                code=str(exc),
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
            )
        return OperatorMembershipMutationResponse(
            target_type="endpoint",
            target_id=result["endpoint_id"],
            workspace_ids=result["workspace_ids"],
            primary_workspace_id=result["primary_workspace_id"],
        )

    @router.patch("/endpoints/{endpoint_id}/primary-workspace", response_model=OperatorMembershipMutationResponse)
    async def set_endpoint_primary_workspace(endpoint_id: str, payload: OperatorPrimaryWorkspaceRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            result = domain.services.endpoint_workspace_membership.set_primary_workspace(
                endpoint_id=endpoint_id,
                workspace_id=payload.workspace_id,
            )
        except KeyError as exc:
            gateway._raise_http_error(
                status_code=404,
                code=str(exc.args[0] if exc.args else "membership_target_not_found"),
                category=RuntimeErrorCategory.VALIDATION.value,
                message="Endpoint or workspace was not found.",
            )
        except ValueError as exc:
            gateway._raise_http_error(
                status_code=400,
                code=str(exc),
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
            )
        return OperatorMembershipMutationResponse(
            target_type="endpoint",
            target_id=result["endpoint_id"],
            workspace_ids=result["workspace_ids"],
            primary_workspace_id=result["primary_workspace_id"],
        )

    @router.post("/addresses/{address_id}/workspaces", response_model=OperatorMembershipMutationResponse)
    async def add_address_workspace(address_id: str, payload: OperatorEndpointMembershipRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            result = domain.services.endpoint_address_workspace_membership.add_workspace(
                address_id=address_id,
                workspace_id=payload.workspace_id,
                make_primary=payload.make_primary,
            )
        except KeyError as exc:
            gateway._raise_http_error(
                status_code=404,
                code=str(exc.args[0] if exc.args else "membership_target_not_found"),
                category=RuntimeErrorCategory.VALIDATION.value,
                message="Address or workspace was not found.",
            )
        except ValueError as exc:
            gateway._raise_http_error(
                status_code=400,
                code=str(exc),
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
            )
        return OperatorMembershipMutationResponse(
            target_type="address",
            target_id=result["address_id"],
            workspace_ids=result["workspace_ids"],
            primary_workspace_id=result["primary_workspace_id"],
        )

    @router.delete("/addresses/{address_id}/workspaces/{workspace_id}", response_model=OperatorMembershipMutationResponse)
    async def remove_address_workspace(address_id: str, workspace_id: str, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            result = domain.services.endpoint_address_workspace_membership.remove_workspace(
                address_id=address_id,
                workspace_id=workspace_id,
            )
        except KeyError as exc:
            gateway._raise_http_error(
                status_code=404,
                code=str(exc.args[0] if exc.args else "membership_target_not_found"),
                category=RuntimeErrorCategory.VALIDATION.value,
                message="Address or workspace was not found.",
            )
        except ValueError as exc:
            gateway._raise_http_error(
                status_code=400,
                code=str(exc),
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
            )
        return OperatorMembershipMutationResponse(
            target_type="address",
            target_id=result["address_id"],
            workspace_ids=result["workspace_ids"],
            primary_workspace_id=result["primary_workspace_id"],
        )

    @router.patch("/addresses/{address_id}/primary-workspace", response_model=OperatorMembershipMutationResponse)
    async def set_address_primary_workspace(address_id: str, payload: OperatorPrimaryWorkspaceRequest, request: Request):
        gateway._require_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            result = domain.services.endpoint_address_workspace_membership.set_primary_workspace(
                address_id=address_id,
                workspace_id=payload.workspace_id,
            )
        except KeyError as exc:
            gateway._raise_http_error(
                status_code=404,
                code=str(exc.args[0] if exc.args else "membership_target_not_found"),
                category=RuntimeErrorCategory.VALIDATION.value,
                message="Address or workspace was not found.",
            )
        except ValueError as exc:
            gateway._raise_http_error(
                status_code=400,
                code=str(exc),
                category=RuntimeErrorCategory.VALIDATION.value,
                message=str(exc),
            )
        return OperatorMembershipMutationResponse(
            target_type="address",
            target_id=result["address_id"],
            workspace_ids=result["workspace_ids"],
            primary_workspace_id=result["primary_workspace_id"],
        )

    return router
