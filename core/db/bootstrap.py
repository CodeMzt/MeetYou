from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from core.config import ConfigManager
from core.db.engine import create_db_engine, create_session_factory, get_database_url
from core.storage.object_store import build_object_store
from core.services import (
    ActorService,
    ApprovalService,
    AttachmentService,
    CapabilityService,
    ClientService,
    ConfigStateService,
    ContextPoolService,
    CoreServices,
    DeliveryAttemptService,
    DeliveryService,
    EndpointCapabilityService,
    EndpointConnectionService,
    EndpointOutboxService,
    EndpointRegistryService,
    MemoryStateService,
    MessageService,
    OperationService,
    OperationCallService,
    PrincipalService,
    ProcedureService,
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
        "default_execution_target": "specific_endpoint",
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
        "title": "Study",
        "description": "Study materials, notes, and review workspace.",
        "base_mode": "study",
        "prompt_overlay": "Use teaching-style explanations, structured notes, and review questions for study tasks.",
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
DEFAULT_PROCEDURES = (
    {
        "procedure_id": "daily_research_digest",
        "title": "Daily Research Digest",
        "description": "Summarize recent progress, sources, and conclusions for a specified topic.",
        "prompt_overlay": "Prioritize recent developments, cite sources clearly, and return a concise digest.",
        "applicable_modes": ["research", "general"],
        "recommended_capabilities": ["search_web", "read_web_page", "search_memory", "summarize_text"],
        "recommended_source_profiles": ["policy_global", "workspace_local"],
        "default_execution_target": "core.local",
        "risk_profile": "read",
        "meta": {
            "preferred_tool_key": "search_web",
            "preferred_target_endpoint_ids": [],
            "preferred_endpoint_provider_types": [],
            "tool_target_routing_policy": "balanced",
            "infer_keywords": ["research", "digest", "latest", "news", "updates", "monitor"],
        },
    },
    {
        "procedure_id": "code_review",
        "title": "Code Review",
        "description": "Review code changes for correctness, regressions, risk, and missing tests.",
        "prompt_overlay": "Focus on correctness, regression risk, test coverage, and clear next actions.",
        "applicable_modes": ["documents", "general", "research"],
        "recommended_capabilities": ["search_memory", "summarize_text"],
        "recommended_source_profiles": ["workspace_local"],
        "default_execution_target": "core.local",
        "risk_profile": "read",
        "meta": {
            "preferred_tool_key": "search_memory",
            "preferred_target_endpoint_ids": [],
            "preferred_endpoint_provider_types": [],
            "tool_target_routing_policy": "balanced",
            "infer_keywords": ["code review", "review", "patch", "diff", "regression", "bug"],
        },
    },
    {
        "procedure_id": "desktop_fix_loop",
        "title": "Desktop Fix Loop",
        "description": "Diagnose, verify, and repair desktop environment issues.",
        "prompt_overlay": "Move through diagnosis, verification, and repair. Ask before risky writes.",
        "applicable_modes": ["automation", "general"],
        "recommended_capabilities": ["search_memory", "manage_tasks"],
        "recommended_source_profiles": ["workspace_local"],
        "default_execution_target": "specific_endpoint",
        "risk_profile": "write",
        "meta": {
            "preferred_tool_key": "manage_tasks",
            "preferred_target_endpoint_ids": [],
            "preferred_endpoint_provider_types": ["desktop"],
            "tool_target_routing_policy": "balanced",
            "infer_keywords": ["desktop", "endpoint", "fix", "repair", "shell", "command"],
        },
    },
    {
        "procedure_id": "study_note_synthesis",
        "title": "Study Note Synthesis",
        "description": "Organize study materials into structured notes, questions, and review items.",
        "prompt_overlay": "Extract key ideas, organize concise notes, and end with review prompts or next steps.",
        "applicable_modes": ["study", "documents"],
        "recommended_capabilities": ["search_memory", "summarize_text", "manage_tasks"],
        "recommended_source_profiles": ["workspace_local"],
        "default_execution_target": "core.local",
        "risk_profile": "read",
        "meta": {
            "preferred_tool_key": "summarize_text",
            "preferred_target_endpoint_ids": [],
            "preferred_endpoint_provider_types": [],
            "tool_target_routing_policy": "balanced",
            "infer_keywords": ["study", "note", "notes", "synthesis", "review question"],
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
    endpoint_capability = EndpointCapabilityService(session_factory)
    operation = OperationService(session_factory)
    operation_call = OperationCallService(session_factory)
    endpoint_outbox = EndpointOutboxService(session_factory)
    delivery_attempt = DeliveryAttemptService(session_factory)
    return CoreServices(
        principal=PrincipalService(session_factory),
        actor=actor,
        workspace=workspace,
        client=ClientService(session_factory),
        endpoint=endpoint,
        endpoint_connection=EndpointConnectionService(session_factory),
        endpoint_capability=endpoint_capability,
        endpoint_outbox=endpoint_outbox,
        delivery_attempt=delivery_attempt,
        delivery=DeliveryService(outbox_service=endpoint_outbox, attempt_service=delivery_attempt),
        capability=CapabilityService(session_factory),
        tool=CapabilityService(session_factory),
        procedure=ProcedureService(session_factory),
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
        attachment=AttachmentService(session_factory),
        message=MessageService(session_factory),
        config_state=ConfigStateService(session_factory),
        context_pool=ContextPoolService(session_factory),
        memory_state=MemoryStateService(session_factory),
        task_state=TaskStateService(session_factory),
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


def bootstrap_core_domain(
    config: ConfigManager | None = None,
    *,
    database_url: str | None = None,
    attachment_storage_root: Path | None = None,
    run_migrations: bool = True,
) -> CoreDomainContext:
    resolved_config = config or ConfigManager()
    resolved_database_url = str(database_url or get_database_url(resolved_config)).strip()
    if run_migrations:
        run_database_migrations(resolved_database_url)

    engine = create_db_engine(resolved_database_url)
    session_factory = create_session_factory(engine)
    object_store = build_object_store(resolved_config, storage_root_override=attachment_storage_root)
    services = build_core_services(session_factory)
    services.attachment = AttachmentService(session_factory, storage_root=attachment_storage_root, object_store=object_store)
    _ensure_v4_system_records(services)

    principal = services.principal.ensure_principal(
        principal_key=DEFAULT_PRINCIPAL_KEY,
        display_name=DEFAULT_PRINCIPAL_NAME,
    )
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
    for item in DEFAULT_PROCEDURES:
        services.procedure.ensure_procedure(
            procedure_id=item["procedure_id"],
            principal_id=principal.id,
            title=item["title"],
            description=item["description"],
            prompt_overlay=item["prompt_overlay"],
            applicable_modes=item["applicable_modes"],
            recommended_capabilities=item["recommended_capabilities"],
            recommended_source_profiles=item["recommended_source_profiles"],
            default_execution_target=item["default_execution_target"],
            risk_profile=item["risk_profile"],
            meta=item.get("meta"),
        )

    return CoreDomainContext(
        database_url=resolved_database_url,
        engine=engine,
        session_factory=session_factory,
        services=services,
        tool_router=services.tool_router,
        principal=principal,
        workspaces=workspaces,
    )

