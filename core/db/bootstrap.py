from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from core.config import ConfigManager
from core.db.engine import create_db_engine, create_session_factory, get_database_url
from core.storage.object_store import build_object_store
from core.services.agent_dispatch_service import AgentDispatchService
from core.services import (
    AgentService,
    ApprovalService,
    AttachmentService,
    CapabilityService,
    ClientService,
    ConfigStateService,
    CoreServices,
    MemoryStateService,
    MessageService,
    OperationService,
    OperationCallService,
    PrincipalService,
    ProcedureService,
    SessionService,
    RuntimeStateBlobService,
    TaskStateService,
    ThreadService,
    WorkspaceService,
)


DEFAULT_PRINCIPAL_KEY = "self"
DEFAULT_PRINCIPAL_NAME = "Self"
DEFAULT_WORKSPACES = (
    {
        "workspace_id": "personal",
        "title": "Personal",
        "description": "默认个人工作空间，适合日常问答、个人记忆与轻量研究。",
        "base_mode": "general",
        "prompt_overlay": "Treat this as the default personal workspace. Prefer concise, broadly useful help unless the user asks for a specialized workflow.",
        "default_execution_target": "core_only",
        "metadata": {
            "capability_policy": "allow_all",
            "allowed_capability_ids": [],
            "preferred_agent_ids": [],
            "preferred_agent_types": [],
            "agent_routing_policy": "balanced",
            "capability_routing_overrides": {},
        },
    },
    {
        "workspace_id": "desktop-main",
        "title": "Desktop Main",
        "description": "主桌面开发与本地自动化工作空间。",
        "base_mode": "automation",
        "prompt_overlay": "This workspace is attached to the primary desktop environment. Prefer local development workflows, reproducible diagnosis, and explicit operator confirmation for write actions.",
        "default_execution_target": "specific_agent",
        "metadata": {
            "capability_policy": "allow_all",
            "allowed_capability_ids": [],
            "preferred_agent_ids": [],
            "preferred_agent_types": ["desktop"],
            "agent_routing_policy": "balanced",
            "capability_routing_overrides": {},
        },
    },
    {
        "workspace_id": "study",
        "title": "Study",
        "description": "学习资料、笔记与复盘工作空间。",
        "base_mode": "study",
        "prompt_overlay": "Prefer teaching-oriented explanations, structured notes, and review questions when the task fits a study workflow.",
        "default_execution_target": "core_only",
        "metadata": {
            "capability_policy": "allow_all",
            "allowed_capability_ids": [],
            "preferred_agent_ids": [],
            "preferred_agent_types": [],
            "agent_routing_policy": "balanced",
            "capability_routing_overrides": {},
        },
    },
    {
        "workspace_id": "home-lab",
        "title": "Home Lab",
        "description": "家庭实验室、边缘节点与设备编排工作空间。",
        "base_mode": "automation",
        "prompt_overlay": "Assume this workspace manages shared lab devices. Prefer device-aware automation plans and target available workspace agents when execution leaves the Core.",
        "default_execution_target": "workspace_any_agent",
        "metadata": {
            "capability_policy": "allow_all",
            "allowed_capability_ids": [],
            "preferred_agent_ids": [],
            "preferred_agent_types": ["raspi", "desktop"],
            "agent_routing_policy": "balanced",
            "capability_routing_overrides": {},
        },
    },
)
DEFAULT_PROCEDURES = (
    {
        "procedure_id": "daily_research_digest",
        "title": "Daily Research Digest",
        "description": "汇总指定主题的最新进展、来源与结论。",
        "prompt_overlay": "Prioritize current developments, cite sources, and structure findings into a concise daily digest.",
        "applicable_modes": ["research", "general"],
        "recommended_capabilities": ["search_web", "read_web_page", "search_memory", "summarize_text"],
        "recommended_source_profiles": ["policy_global", "workspace_local"],
        "default_execution_target": "core_only",
        "risk_profile": "read",
        "meta": {
            "preferred_capability_ref": "search_web",
            "preferred_agent_ids": [],
            "preferred_agent_types": [],
            "agent_routing_policy": "balanced",
        },
    },
    {
        "procedure_id": "code_review",
        "title": "Code Review",
        "description": "围绕代码变更、风险与验证给出结构化审查。",
        "prompt_overlay": "Focus on correctness, regressions, tests, and concrete follow-up actions before stylistic suggestions.",
        "applicable_modes": ["documents", "general", "research"],
        "recommended_capabilities": ["search_memory", "summarize_text"],
        "recommended_source_profiles": ["workspace_local"],
        "default_execution_target": "core_only",
        "risk_profile": "read",
        "meta": {
            "preferred_capability_ref": "search_memory",
            "preferred_agent_ids": [],
            "preferred_agent_types": [],
            "agent_routing_policy": "balanced",
        },
    },
    {
        "procedure_id": "desktop_fix_loop",
        "title": "Desktop Fix Loop",
        "description": "定位桌面环境问题，给出假设、验证与修复闭环。",
        "prompt_overlay": "Work in a diagnose-verify-fix loop, prefer reproducible evidence, and call out risks before write actions.",
        "applicable_modes": ["automation", "general"],
        "recommended_capabilities": ["search_memory", "manage_tasks"],
        "recommended_source_profiles": ["workspace_local"],
        "default_execution_target": "specific_agent",
        "risk_profile": "write",
        "meta": {
            "preferred_capability_ref": "manage_tasks",
            "preferred_agent_ids": [],
            "preferred_agent_types": ["desktop"],
            "agent_routing_policy": "balanced",
        },
    },
    {
        "procedure_id": "study_note_synthesis",
        "title": "Study Note Synthesis",
        "description": "把学习材料整理为结构化笔记、问题与复盘项。",
        "prompt_overlay": "Extract key concepts, create concise study notes, and finish with review questions or next steps.",
        "applicable_modes": ["study", "documents"],
        "recommended_capabilities": ["search_memory", "summarize_text", "manage_tasks"],
        "recommended_source_profiles": ["workspace_local"],
        "default_execution_target": "core_only",
        "risk_profile": "read",
        "meta": {
            "preferred_capability_ref": "summarize_text",
            "preferred_agent_ids": [],
            "preferred_agent_types": [],
            "agent_routing_policy": "balanced",
        },
    },
)


@dataclass(slots=True)
class CoreDomainContext:
    database_url: str
    engine: object
    session_factory: object
    services: CoreServices
    agent_dispatch: AgentDispatchService
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
    return CoreServices(
        principal=PrincipalService(session_factory),
        workspace=WorkspaceService(session_factory),
        client=ClientService(session_factory),
        agent=AgentService(session_factory),
        capability=CapabilityService(session_factory),
        procedure=ProcedureService(session_factory),
        thread=ThreadService(session_factory),
        session=SessionService(session_factory),
        state_blob=RuntimeStateBlobService(session_factory),
        operation=OperationService(session_factory),
        operation_call=OperationCallService(session_factory),
        approval=ApprovalService(session_factory),
        attachment=AttachmentService(session_factory),
        message=MessageService(session_factory),
        config_state=ConfigStateService(session_factory),
        memory_state=MemoryStateService(session_factory),
        task_state=TaskStateService(session_factory),
    )


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
    services = CoreServices(
        principal=PrincipalService(session_factory),
        workspace=WorkspaceService(session_factory),
        client=ClientService(session_factory),
        agent=AgentService(session_factory),
        capability=CapabilityService(session_factory),
        procedure=ProcedureService(session_factory),
        thread=ThreadService(session_factory),
        session=SessionService(session_factory),
        state_blob=RuntimeStateBlobService(session_factory),
        operation=OperationService(session_factory),
        operation_call=OperationCallService(session_factory),
        approval=ApprovalService(session_factory),
        attachment=AttachmentService(session_factory, storage_root=attachment_storage_root, object_store=object_store),
        message=MessageService(session_factory),
        config_state=ConfigStateService(session_factory),
        memory_state=MemoryStateService(session_factory),
        task_state=TaskStateService(session_factory),
    )
    agent_dispatch = AgentDispatchService(
        agent_service=services.agent,
        capability_service=services.capability,
        session_service=services.session,
        thread_service=services.thread,
        workspace_service=services.workspace,
        operation_service=services.operation,
        operation_call_service=services.operation_call,
    )

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
            default_execution_target=item.get("default_execution_target", "core_only"),
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
        agent_dispatch=agent_dispatch,
        principal=principal,
        workspaces=workspaces,
    )
