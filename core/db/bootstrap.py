from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from core.config import ConfigManager
from core.db.engine import create_db_engine, create_session_factory, get_database_url
from core.services import (
    ActorService,
    ActorDeliveryPreferenceService,
    ApprovalService,
    CapabilityService,
    ConfigStateService,
    ContextPoolService,
    CoreServices,
    DeliveryAttemptService,
    DeliveryService,
    EndpointAddressService,
    EndpointAddressWorkspaceMembershipService,
    EndpointCapabilityService,
    EndpointConnectionService,
    EndpointOutboxService,
    EndpointRegistryService,
    EndpointWorkspaceMembershipService,
    EndpointThreadBindingService,
    ArtifactService,
    ConversationVersionService,
    MemoryStateService,
    MessageService,
    OperationService,
    OperationCallService,
    PrincipalService,
    ProjectService,
    ResearchTaskService,
    RunEventService,
    RunService,
    ScheduledJobRunService,
    SchedulerService,
    SessionService,
    RuntimeStateBlobService,
    TaskStateService,
    ThreadService,
    ToolRouterService,
    WorkspaceService,
)


DEFAULT_PRINCIPAL_KEY = "self"
DEFAULT_PRINCIPAL_NAME = "Self"
DEFAULT_WORKSPACES = (
    {
        "workspace_id": "personal",
        "title": "Personal",
        "description": "Default personal workspace for everyday questions, memory, and lightweight research.",
        "base_mode": "general",
        "prompt_overlay": "Treat this as the default personal workspace unless the user selects a more specific workflow.",
        "default_execution_target": "core.local",
        "metadata": {
            "tool_policy": "allow_all",
            "allowed_tool_ids": [],
            "preferred_target_endpoint_ids": [],
            "preferred_endpoint_provider_types": [],
            "preferred_source_profiles": ["workspace_local"],
            "tool_target_routing_policy": "balanced",
            "memory_ranking_policy": "workspace_first",
            "tool_routing_overrides": {},
        },
    },
    {
        "workspace_id": "desktop-main",
        "title": "Desktop Main",
        "description": "Desktop development and local automation workspace.",
        "base_mode": "automation",
        "prompt_overlay": "Prefer local development workflows and reproducible verification. Request confirmation before risky writes.",
        "default_execution_target": "endpoint",
        "metadata": {
            "tool_policy": "allow_all",
            "allowed_tool_ids": [],
            "preferred_target_endpoint_ids": [],
            "preferred_endpoint_provider_types": ["desktop"],
            "preferred_source_profiles": ["workspace_local"],
            "tool_target_routing_policy": "balanced",
            "memory_ranking_policy": "workspace_first",
            "tool_routing_overrides": {},
        },
    },
    {
        "workspace_id": "study",
        "title": "学习",
        "description": "学习资料、笔记和复习工作区。",
        "base_mode": "general",
        "prompt_overlay": "学习任务使用教学式解释、结构化笔记和复习问题。",
        "default_execution_target": "core.local",
        "metadata": {
            "tool_policy": "allow_all",
            "allowed_tool_ids": [],
            "preferred_target_endpoint_ids": [],
            "preferred_endpoint_provider_types": [],
            "preferred_source_profiles": ["study_materials"],
            "tool_target_routing_policy": "balanced",
            "memory_ranking_policy": "workspace_first",
            "tool_routing_overrides": {},
        },
    },
    {
        "workspace_id": "home-lab",
        "title": "Home Lab",
        "description": "Home lab, edge nodes, and device orchestration workspace.",
        "base_mode": "automation",
        "prompt_overlay": "Use available endpoint providers when work must run outside Core.",
        "default_execution_target": "workspace_any_endpoint",
        "metadata": {
            "tool_policy": "allow_all",
            "allowed_tool_ids": [],
            "preferred_target_endpoint_ids": [],
            "preferred_endpoint_provider_types": ["raspi", "desktop"],
            "preferred_source_profiles": ["workspace_local"],
            "tool_target_routing_policy": "balanced",
            "memory_ranking_policy": "workspace_first",
            "tool_routing_overrides": {},
        },
    },
)
@dataclass(slots=True)
class CoreDomainContext:
    database_url: str
    engine: object
    session_factory: object
    services: CoreServices
    tool_router: object
    principal: object
    workspaces: dict[str, object]
    research_fetcher: object | None = None
    research_web_searcher: object | None = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_database_migrations(database_url: str) -> None:
    root = _project_root()
    config = AlembicConfig(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def build_core_services(session_factory) -> CoreServices:
    actor = ActorService(session_factory)
    workspace = WorkspaceService(session_factory)
    endpoint = EndpointRegistryService(session_factory)
    endpoint_workspace_membership = EndpointWorkspaceMembershipService(session_factory)
    endpoint_address = EndpointAddressService(session_factory)
    endpoint_address_workspace_membership = EndpointAddressWorkspaceMembershipService(session_factory)
    endpoint_thread_binding = EndpointThreadBindingService(session_factory)
    actor_delivery_preference = ActorDeliveryPreferenceService(session_factory)
    endpoint_capability = EndpointCapabilityService(session_factory)
    operation = OperationService(session_factory)
    operation_call = OperationCallService(session_factory)
    endpoint_outbox = EndpointOutboxService(session_factory)
    delivery_attempt = DeliveryAttemptService(session_factory)
    return CoreServices(
        principal=PrincipalService(session_factory),
        actor=actor,
        workspace=workspace,
        endpoint=endpoint,
        endpoint_connection=EndpointConnectionService(session_factory),
        endpoint_capability=endpoint_capability,
        endpoint_address=endpoint_address,
        endpoint_workspace_membership=endpoint_workspace_membership,
        endpoint_address_workspace_membership=endpoint_address_workspace_membership,
        endpoint_thread_binding=endpoint_thread_binding,
        actor_delivery_preference=actor_delivery_preference,
        endpoint_outbox=endpoint_outbox,
        delivery_attempt=delivery_attempt,
        delivery=DeliveryService(outbox_service=endpoint_outbox, attempt_service=delivery_attempt),
        capability=CapabilityService(session_factory),
        tool=CapabilityService(session_factory),
        thread=ThreadService(session_factory),
        session=SessionService(session_factory),
        run=RunService(session_factory),
        run_event=RunEventService(session_factory),
        scheduler=SchedulerService(session_factory),
        scheduled_job_run=ScheduledJobRunService(session_factory),
        tool_router=ToolRouterService(
            actor_service=actor,
            workspace_service=workspace,
            endpoint_service=endpoint,
            endpoint_capability_service=endpoint_capability,
            session_service=SessionService(session_factory),
            thread_service=ThreadService(session_factory),
            operation_service=operation,
            operation_call_service=operation_call,
        ),
        state_blob=RuntimeStateBlobService(session_factory),
        operation=operation,
        operation_call=operation_call,
        approval=ApprovalService(session_factory),
        message=MessageService(session_factory),
        config_state=ConfigStateService(session_factory),
        context_pool=ContextPoolService(session_factory),
        memory_state=MemoryStateService(session_factory),
        task_state=TaskStateService(session_factory),
        project=ProjectService(session_factory),
        artifact=ArtifactService(session_factory),
        conversation_version=ConversationVersionService(session_factory),
        research_task=ResearchTaskService(session_factory),
    )


def _ensure_v4_system_records(services: CoreServices) -> None:
    scheduler_actor = services.actor.ensure_actor(
        actor_id="system.scheduler",
        actor_type="system_scheduler",
        display_name="System Scheduler",
        permission_profile_id="profile.system_scheduler",
    )
    heartbeat_actor = services.actor.ensure_actor(
        actor_id="system.heartbeat",
        actor_type="system_heartbeat",
        display_name="System Heartbeat",
        permission_profile_id="profile.system_heartbeat",
    )
    maintenance_actor = services.actor.ensure_actor(
        actor_id="system.maintenance",
        actor_type="system_maintenance",
        display_name="System Maintenance",
        permission_profile_id="profile.system_maintenance",
    )
    del heartbeat_actor, maintenance_actor
    services.endpoint.ensure_endpoint(
        endpoint_id="core.local",
        endpoint_type="core_local",
        provider_type="core",
        transport_type="inproc",
        owner_actor_id=scheduler_actor.id,
        labels=["core", "execution"],
        priority=0,
        metadata={"execution_target": True},
    )
    services.endpoint.ensure_endpoint(
        endpoint_id="core.scheduler",
        endpoint_type="core_scheduler",
        provider_type="core",
        transport_type="inproc",
        owner_actor_id=scheduler_actor.id,
        labels=["core", "scheduler"],
        priority=0,
        metadata={"system_clock": True},
    )
    services.endpoint.ensure_endpoint(
        endpoint_id="core.inbox",
        endpoint_type="core_inbox",
        provider_type="core",
        transport_type="database",
        owner_actor_id=scheduler_actor.id,
        labels=["core", "delivery"],
        priority=10,
        metadata={"delivery_sink": True},
    )
    services.endpoint.ensure_endpoint(
        endpoint_id="core.notification",
        endpoint_type="core_notification",
        provider_type="core",
        transport_type="inproc",
        owner_actor_id=scheduler_actor.id,
        labels=["core", "notice"],
        priority=10,
        metadata={"delivery_sink": True},
    )
    services.scheduler.ensure_system_heartbeat(interval_seconds=600)


def _ensure_default_user_actor(services: CoreServices, principal) -> object:
    principal_key = str(getattr(principal, "principal_key", "") or DEFAULT_PRINCIPAL_KEY).strip() or DEFAULT_PRINCIPAL_KEY
    return services.actor.ensure_actor(
        actor_id=f"user:{principal_key}",
        actor_type="user",
        owner_user_id=principal_key,
        display_name=str(getattr(principal, "display_name", "") or DEFAULT_PRINCIPAL_NAME),
        permission_profile_id="profile.default_user",
        metadata={"principal_key": principal_key},
    )


def bootstrap_core_domain(
    config: ConfigManager | None = None,
    *,
    database_url: str | None = None,
    run_migrations: bool = True,
) -> CoreDomainContext:
    resolved_config = config or ConfigManager()
    resolved_database_url = str(database_url or get_database_url(resolved_config)).strip()
    if run_migrations:
        run_database_migrations(resolved_database_url)

    engine = create_db_engine(resolved_database_url)
    session_factory = create_session_factory(engine)
    services = build_core_services(session_factory)
    _ensure_v4_system_records(services)

    principal = services.principal.ensure_principal(
        principal_key=DEFAULT_PRINCIPAL_KEY,
        display_name=DEFAULT_PRINCIPAL_NAME,
    )
    _ensure_default_user_actor(services, principal)
    workspaces: dict[str, object] = {}
    for item in DEFAULT_WORKSPACES:
        workspace = services.workspace.ensure_workspace(
            workspace_id=item["workspace_id"],
            principal_id=principal.id,
            title=item["title"],
            description=item.get("description", ""),
            base_mode=item["base_mode"],
            prompt_overlay=item.get("prompt_overlay", ""),
            default_execution_target=item.get("default_execution_target", "core.local"),
            metadata=item.get("metadata"),
        )
        workspaces[item["workspace_id"]] = workspace
    services.endpoint.retire_acceptance_probe_endpoints()
    return CoreDomainContext(
        database_url=resolved_database_url,
        engine=engine,
        session_factory=session_factory,
        services=services,
        tool_router=services.tool_router,
        principal=principal,
        workspaces=workspaces,
    )

