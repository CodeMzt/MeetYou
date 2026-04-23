"""
Runtime lifecycle helpers for the Core App.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from core.exceptions import ConfigError
from core.db.bootstrap import bootstrap_core_domain
from core.db.importers import (
    import_config_state,
    import_memory_state,
    import_memory_state_payload,
    import_source_catalog_state,
    import_task_state,
)
from core.source_catalog import SOURCE_CATALOG_STATE_KEY
from core.state_backends import RuntimeStateBlobBackend
from core.status import RuntimeStatus
from gateway.api import FastAPIGateway
from sensors.feishu_input_adapter import FeishuInputAdapter
from sensors.feishu_output_adapter import FeishuOutputAdapter
from sensors.wechat_ilink_adapter import (
    DEFAULT_TOKEN_FILE,
    WeChatIlinkStateStore,
    WeChatInputAdapter,
    WeChatOutputService,
    WeChatSessionManager,
)
from adapters.wechat_ilink_client import (
    DEFAULT_CHANNEL_VERSION,
    DEFAULT_ILINK_BASE_URL,
    WeChatIlinkClient,
)
from tools import system_tools

logger = logging.getLogger("meetyou.app.lifecycle")


async def _maybe_await(callback, *args, **kwargs) -> None:
    if callback is None:
        return
    result = callback(*args, **kwargs)
    if inspect.isawaitable(result):
        await result


async def sync_config_state_to_db(app) -> None:
    core_services = getattr(app, "core_services", None)
    if core_services is None:
        return
    import_config_state(app.config, core_services)


async def sync_memory_state_to_db(app) -> None:
    core_services = getattr(app, "core_services", None)
    core_domain = getattr(app, "core_domain", None)
    if core_services is None or core_domain is None:
        return
    payload = core_services.state_blob.load_state(
        principal_id=core_domain.principal.id,
        state_key="memory_graph",
        default_factory=lambda: {"records": []},
    )
    import_memory_state_payload(
        payload,
        principal_id=core_domain.principal.id,
        workspaces=core_domain.workspaces,
        services=core_services,
        imported_from="runtime_state_blob:memory_graph",
    )


async def sync_task_state_to_db(app) -> None:
    core_services = getattr(app, "core_services", None)
    core_domain = getattr(app, "core_domain", None)
    if core_services is None or core_domain is None:
        return
    import_task_state(
        app.config.get("task_file_path") or "user/memory_tasks.json",
        principal_id=core_domain.principal.id,
        workspaces=core_domain.workspaces,
        services=core_services,
    )


async def sync_source_catalog_state_to_db(app) -> None:
    core_services = getattr(app, "core_services", None)
    core_domain = getattr(app, "core_domain", None)
    if core_services is None or core_domain is None:
        return
    import_source_catalog_state(
        app.config.get("source_catalog_path") or "user/source_catalog.json",
        principal_id=core_domain.principal.id,
        services=core_services,
    )


async def setup_app_runtime(app) -> None:
    tools_schema_path = app.config.get("tools_schema_path") or "user/tools.json"
    mcp_servers = app.config.get_mcp_servers()
    mcp_config_diagnostic = app.config.get_mcp_server_config_diagnostic()

    app.status_manager.set_global(RuntimeStatus.INITIALIZING.value, "Starting up")
    app.core_domain = bootstrap_core_domain(app.config)
    app.db_engine = app.core_domain.engine
    app.db_session_factory = app.core_domain.session_factory
    app.core_services = app.core_domain.services
    app.heart.set_core_services(app.core_services)
    state_blob_service = app.core_services.state_blob
    await app.memory.init_memory(app.config)
    app.memory.set_store_backend(
        RuntimeStateBlobBackend(
            state_blob_service,
            principal_id=app.core_domain.principal.id,
            state_key="memory_graph",
            default_factory=app.memory._store_layer.empty_store,
        ),
        migrate_current=True,
    )
    app.memory.set_db_sync_callback(app._sync_memory_state_to_db)
    app.task_manager.set_store_backend(
        RuntimeStateBlobBackend(
            state_blob_service,
            principal_id=app.core_domain.principal.id,
            state_key="task_store",
            default_factory=app.task_manager._empty_store,
        ),
        migrate_current=True,
    )
    app.tools_manager.set_state_backends(
        danxi_backend=RuntimeStateBlobBackend(
            state_blob_service,
            principal_id=app.core_domain.principal.id,
            state_key="danxi_state",
            default_factory=dict,
        ),
        office_backend=RuntimeStateBlobBackend(
            state_blob_service,
            principal_id=app.core_domain.principal.id,
            state_key="office_state",
            default_factory=dict,
        ),
        study_backend=RuntimeStateBlobBackend(
            state_blob_service,
            principal_id=app.core_domain.principal.id,
            state_key="study_progress",
            default_factory=dict,
        ),
    )
    app.mode_manager.set_source_catalog_backend(
        RuntimeStateBlobBackend(
            state_blob_service,
            principal_id=app.core_domain.principal.id,
            state_key=SOURCE_CATALOG_STATE_KEY,
            default_factory=dict,
        ),
        migrate_current=True,
    )
    capability_dispatcher = app.core_domain.agent_dispatch
    system_tools.set_capability_dispatcher(capability_dispatcher)
    app.tools_manager.set_core_domain(app.core_domain)
    tools_manager_dispatch_setter = getattr(app.tools_manager, "set_capability_dispatcher", None)
    if callable(tools_manager_dispatch_setter):
        tools_manager_dispatch_setter(capability_dispatcher)
    else:
        app.tools_manager.set_agent_dispatcher(capability_dispatcher)
    await sync_config_state_to_db(app)
    await sync_memory_state_to_db(app)
    logger.info(
        "Core MCP 边界: %s",
        mcp_config_diagnostic.get("message") or "未提供 Core MCP 配置诊断。",
    )
    await app.tools_manager.init_tools(tools_schema_path, mcp_servers)
    core_mcp_diagnostics = app.get_core_mcp_diagnostics()
    core_mcp_summary = core_mcp_diagnostics.get("summary") or {}
    logger.info(
        "Core MCP 运行态: configured=%s enabled=%s partial_failures=%s",
        int(core_mcp_summary.get("configured_server_count", 0) or 0),
        int(core_mcp_summary.get("enabled_count", 0) or 0),
        int(core_mcp_summary.get("partial_failure_count", 0) or 0),
    )
    await app._refresh_brain_runtime()
    await app.heart.init_heart()
    system_tools.set_background_status_provider(app.heart.get_background_status)
    system_tools.set_heartbeat_settings_provider(app.get_heartbeat_settings)
    system_tools.set_heartbeat_settings_updater(app.update_heartbeat_settings)

    host = app.config.get("gateway_host") or "127.0.0.1"
    port = int(app.config.get("gateway_port") or 8000)
    gateway_access_token = str(app.config.get("gateway_access_token") or "").strip()
    agent_access_token = str(app.config.get("agent_access_token") or "").strip()
    if host not in {"127.0.0.1", "localhost", "::1"} and not gateway_access_token:
        raise ConfigError("非本地 gateway_host 必须配置 gateway_access_token")
    app.gateway = FastAPIGateway(
        app.event_bus,
        app.session_manager,
        config_snapshot_getter=app.get_config_snapshot,
        config_item_getter=app.get_config_entry,
        config_updater=app.apply_config_updates,
        memory_snapshot_getter=app.get_memory_snapshot,
        memory_graph_getter=app.get_memory_graph,
        runtime_state_getter=app.get_runtime_state,
        runtime_usage_getter=app.get_runtime_usage,
        runtime_debug_getter=app.get_runtime_debug,
        health_getter=app._health_getter,
        ws_delivery_observer=(
            app._telemetry_recorder.observe_gateway_delivery
            if app._telemetry_recorder is not None
            else None
        ),
        core_domain=app.core_domain,
        agent_connection_prompt_getter=app.build_agent_connection_prompt,
        agent_connection_event_handler=app.inject_agent_connection_event,
        agent_access_token=agent_access_token,
        access_token=gateway_access_token,
        cors_origins=app.config.get("gateway_cors_origins") or [],
    )
    app.core_domain.agent_dispatch.set_transport(app.gateway.dispatch_agent_call)
    app.speaker.register_adapter("web", app.gateway.output_adapter)
    app.speaker.register_adapter("internal", app.gateway.agent_output_adapter)
    await app.gateway.start(host=host, port=port)

    if app.config.get_bool("enable_feishu_bot"):
        app.feishu_output = FeishuOutputAdapter(app.config)
        await app.feishu_output.init()
        app.feishu_input = FeishuInputAdapter(
            app.event_bus,
            app.session_manager,
            app.config,
            output_adapter=app.feishu_output,
        )
        app._register_feishu_broadcast_targets()
        await app.feishu_input.run()
        logger.info("Feishu Bot 已通过 Client API + client/ws 正式主链接入。")

    if app.config.get_bool("enable_wechat_bot"):
        wechat_client = WeChatIlinkClient(
            base_url=str(app.config.get("wechat_ilink_base_url") or DEFAULT_ILINK_BASE_URL),
            channel_version=str(app.config.get("wechat_ilink_channel_version") or DEFAULT_CHANNEL_VERSION),
        )
        wechat_state_store = WeChatIlinkStateStore(
            str(app.config.get("wechat_ilink_token_file") or DEFAULT_TOKEN_FILE)
        )
        wechat_session_manager = WeChatSessionManager(
            config=app.config,
            client=wechat_client,
            state_store=wechat_state_store,
        )
        app.wechat_output = WeChatOutputService(
            config=app.config,
            client=wechat_client,
            session_manager=wechat_session_manager,
            state_store=wechat_state_store,
        )
        app.wechat_input = WeChatInputAdapter(
            app.event_bus,
            app.session_manager,
            app.config,
            ilink_client=wechat_client,
            state_store=wechat_state_store,
            ilink_session_manager=wechat_session_manager,
            output_adapter=app.wechat_output,
        )
        await app.wechat_input.run()
        logger.info("WeChat iLink Bot 已通过 Client API + client/ws 正式主链接入。")

    app.status_manager.set_global(RuntimeStatus.IDLE.value, "")
    logger.info("Service runtime initialized")


def build_runtime_processors(app) -> tuple[Any, ...]:
    return (
        app.brain_processor(),
        app.heart.scheduler_processor(),
        app.heart.housekeeping_processor(),
        app.heart.heartbeat_processor(),
        app.proprioceptor.run(),
    )


async def run_app_runtime(app, *, on_ready=None, on_stopping=None) -> None:
    await setup_app_runtime(app)
    await _maybe_await(on_ready)
    try:
        await asyncio.gather(*build_runtime_processors(app))
    finally:
        await _maybe_await(on_stopping)
        await shutdown_app_runtime(app)


async def shutdown_app_runtime(app) -> None:
    logger.info("Shutting down...")
    app.status_manager.set_global(RuntimeStatus.SHUTTING_DOWN.value, "Shutting down")
    app.event_bus.request_shutdown()
    await app._session_execution_runtime.shutdown()
    if app.gateway is not None:
        await app.gateway.stop()
    if app.feishu_input is not None:
        await app.feishu_input.close()
    if app.feishu_output is not None:
        await app.feishu_output.close()
    if app.wechat_input is not None:
        await app.wechat_input.close()
    await app.mcp_manager.close_mcp_servers()
    await app.brain.close_brain()
    await app.heart.close_heart()
    await app.memory.close_memory()
    if app.db_engine is not None:
        app.db_engine.dispose()
    logger.info("All resources released")
