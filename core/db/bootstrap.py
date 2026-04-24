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
    ContextPoolService,
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
        "title": "个人",
        "description": "默认个人工作空间，适合日常问答、个人记忆与轻量研究。",
        "base_mode": "general",
        "prompt_overlay": "把这里视为默认个人工作空间；除非用户明确要求专门流程，否则优先给出简洁、通用、可直接执行的帮助。",
        "default_execution_target": "core_only",
        "metadata": {
            "capability_policy": "allow_all",
            "allowed_capability_ids": [],
            "preferred_agent_ids": [],
            "preferred_agent_types": [],
            "preferred_source_profiles": ["workspace_local"],
            "agent_routing_policy": "balanced",
            "memory_ranking_policy": "workspace_first",
            "capability_routing_overrides": {},
        },
    },
    {
        "workspace_id": "desktop-main",
        "title": "主桌面",
        "description": "主桌面开发与本地自动化工作空间。",
        "base_mode": "automation",
        "prompt_overlay": "该工作区绑定到主桌面环境；优先采用本地开发工作流、可复现诊断步骤，并在写入操作前明确提醒人工确认。",
        "default_execution_target": "specific_agent",
        "metadata": {
            "capability_policy": "allow_all",
            "allowed_capability_ids": [],
            "preferred_agent_ids": [],
            "preferred_agent_types": ["desktop"],
            "preferred_source_profiles": ["workspace_local"],
            "agent_routing_policy": "balanced",
            "memory_ranking_policy": "workspace_first",
            "capability_routing_overrides": {},
        },
    },
    {
        "workspace_id": "study",
        "title": "学习",
        "description": "学习资料、笔记与复盘工作空间。",
        "base_mode": "study",
        "prompt_overlay": "当任务符合学习场景时，优先采用教学式解释、结构化笔记和复习题。",
        "default_execution_target": "core_only",
        "metadata": {
            "capability_policy": "allow_all",
            "allowed_capability_ids": [],
            "preferred_agent_ids": [],
            "preferred_agent_types": [],
            "preferred_source_profiles": ["study_materials"],
            "agent_routing_policy": "balanced",
            "memory_ranking_policy": "workspace_first",
            "capability_routing_overrides": {},
        },
    },
    {
        "workspace_id": "home-lab",
        "title": "家庭实验室",
        "description": "家庭实验室、边缘节点与设备编排工作空间。",
        "base_mode": "automation",
        "prompt_overlay": "假设该工作区负责共享实验室设备；当执行离开 Core 时，优先采用感知设备环境的自动化方案并路由到可用工作区代理。",
        "default_execution_target": "workspace_any_agent",
        "metadata": {
            "capability_policy": "allow_all",
            "allowed_capability_ids": [],
            "preferred_agent_ids": [],
            "preferred_agent_types": ["raspi", "desktop"],
            "preferred_source_profiles": ["workspace_local"],
            "agent_routing_policy": "balanced",
            "memory_ranking_policy": "workspace_first",
            "capability_routing_overrides": {},
        },
    },
)
DEFAULT_PROCEDURES = (
    {
        "procedure_id": "daily_research_digest",
        "title": "每日研究摘要",
        "description": "汇总指定主题的最新进展、来源与结论。",
        "prompt_overlay": "优先关注最新进展，明确引用来源，并把结论整理成简洁的每日摘要。",
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
            "infer_keywords": ["research", "digest", "latest", "news", "updates", "monitor"],
        },
    },
    {
        "procedure_id": "code_review",
        "title": "代码审查",
        "description": "围绕代码变更、风险与验证给出结构化审查。",
        "prompt_overlay": "优先关注正确性、回归风险、测试覆盖和明确后续动作，风格建议放在后面。",
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
            "infer_keywords": ["code review", "review", "patch", "diff", "regression", "bug", "代码审查"],
        },
    },
    {
        "procedure_id": "desktop_fix_loop",
        "title": "桌面修复闭环",
        "description": "定位桌面环境问题，给出假设、验证与修复闭环。",
        "prompt_overlay": "按照诊断-验证-修复闭环推进，优先给出可复现证据，并在写入操作前明确提示风险。",
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
            "infer_keywords": ["desktop", "agent", "fix", "repair", "shell", "command", "桌面", "修复"],
        },
    },
    {
        "procedure_id": "study_note_synthesis",
        "title": "学习笔记整理",
        "description": "把学习材料整理为结构化笔记、问题与复盘项。",
        "prompt_overlay": "提炼关键概念，整理成简洁笔记，并以复习题或下一步建议收尾。",
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
            "infer_keywords": ["study", "note", "notes", "synthesis", "review question", "学习", "笔记", "复习"],
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
        context_pool=ContextPoolService(session_factory),
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
        context_pool=ContextPoolService(session_factory),
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
