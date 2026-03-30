"""
应用级依赖注入容器与生命周期管理。

当前进程模型固定为 gateway-only 后端运行时：
- Brain / Heart / Memory / Proprioceptor
- FastAPI gateway
- 可选 Feishu 输入输出
"""

import asyncio
import logging
import traceback
from typing import Any

from adapters.base import create_adapter
from core.brain import Brain
from core.config import ConfigManager
from core.context import ContextManager
from core.event_bus import EventBus
from core.exceptions import ExceptionRouter, MeetYouError
from core.heart import Heart
from core.io_protocol import EventTarget, EventType, SourceKind, TargetKind, make_source
from core.logger import setup_logger
from core.runtime_context import (
    bind_event_context,
    get_event_context,
    reset_event_context,
)
from core.session_manager import SessionManager
from core.speaker import Speaker
from core.tools_manager import ToolsManager
from gateway.api import FastAPIGateway
from platform_layer.detector import detect_platform
from sensors.feishu_input_adapter import FeishuInputAdapter
from sensors.feishu_output_adapter import FeishuOutputAdapter
from sensors.proprioceptor import Proprioceptor
from tools import system_tools
from tools.mcp import MCPManager
from tools.memory import Memory

logger = logging.getLogger("meetyou.app")

_BRAIN_IMMEDIATE_KEYS = {
    "api_provider",
    "api_url",
    "api_key",
    "model",
    "soul_path",
}
_HEART_IMMEDIATE_KEYS = {
    "heartbeat_api_provider",
    "heartbeat_api_url",
    "heartbeat_api_key",
    "heartbeat_interval",
    "heart_model",
    "heartbeat_path",
}
_MEMORY_IMMEDIATE_KEYS = {
    "embedding_api_url",
    "embedding_api_key",
    "embedding_model",
}
_RESTART_REQUIRED_KEYS = {
    "cmd_policy_path",
    "enable_feishu_bot",
    "feishu_app_id",
    "feishu_app_secret",
    "feishu_broadcast_chat_ids",
    "feishu_default_chat_id",
    "feishu_chat_registry_path",
    "gateway_host",
    "gateway_port",
    "mcp_registry_url",
    "memory_file_path",
    "tools_schema_path",
}


class App:
    """
    gateway-only 后端运行时。

    负责统一创建所有依赖、启动 HTTP/WebSocket 网关，并处理入站事件。
    """

    def __init__(self):
        setup_logger(enable_console=True, component="gateway")

        self.event_bus = EventBus()
        self.exception_router = ExceptionRouter()
        self.config = ConfigManager()
        self.platform = detect_platform()

        self.main_adapter = create_adapter(self._get_main_provider())
        self.heart_adapter = create_adapter(self._get_heart_provider())

        self.memory = Memory()
        self.mcp_manager = MCPManager()
        system_tools.init_system_tools(
            self.platform,
            self.event_bus,
            self.config.get("cmd_policy_path") or "user/cmd_policy.json",
        )

        self.context_manager = ContextManager(
            self.memory, self.main_adapter, self.event_bus
        )
        self.tools_manager = ToolsManager(
            self.memory, self.context_manager, self.mcp_manager, system_tools
        )
        self.brain = Brain(
            self.main_adapter,
            self.tools_manager,
            self.context_manager,
            self.event_bus,
            self.exception_router,
        )
        self.heart = Heart(
            self.heart_adapter,
            self.config,
            self.tools_manager,
            self.memory,
            self.event_bus,
            self.exception_router,
        )

        self.session_manager = SessionManager()
        self.speaker = Speaker(self.session_manager)
        self.gateway: FastAPIGateway | None = None
        self.feishu_input: FeishuInputAdapter | None = None
        self.feishu_output: FeishuOutputAdapter | None = None
        self.proprioceptor = Proprioceptor(
            self.platform, self.context_manager, self.event_bus
        )
        self._brain_source = make_source(SourceKind.SYSTEM.value, "brain")

        self.exception_router.on_system_error(self._log_error)
        self.exception_router.on_user_error(self._display_error)
        self.event_bus.subscribe(
            self.event_bus.CONFIRM_REQUEST,
            self._handle_confirm_request,
        )

        logger.info("Gateway runtime 依赖注入完成")

    def _get_main_provider(self) -> str:
        return self.config.get("api_provider") or "openai"

    def _get_heart_provider(self) -> str:
        return self.config.get("heartbeat_api_provider") or self._get_main_provider()

    async def _log_error(self, error: MeetYouError):
        logger.error("[SYSTEM] %s: %s", type(error).__name__, error)

    async def _display_error(self, error: MeetYouError):
        context = get_event_context()
        session_id = context.get("session_id", "")
        target = context.get("target")
        if session_id:
            await self.speaker.emit_error(
                session_id,
                str(error),
                make_source(SourceKind.SYSTEM.value, "exception"),
                target=target if isinstance(target, EventTarget) else None,
            )
            return
        logger.warning("用户级异常未绑定会话，仅写日志: %s", error)

    async def _handle_confirm_request(self, event):
        await self.speaker.emit(event)

    def _register_feishu_broadcast_targets(self):
        raw_chat_ids = self.config.get("feishu_broadcast_chat_ids") or []
        if isinstance(raw_chat_ids, str):
            chat_ids = [item.strip() for item in raw_chat_ids.split(",") if item.strip()]
        elif isinstance(raw_chat_ids, list):
            chat_ids = [str(item).strip() for item in raw_chat_ids if str(item).strip()]
        else:
            chat_ids = []

        default_chat_id = self.config.get("feishu_default_chat_id") or ""
        if default_chat_id:
            chat_ids.append(str(default_chat_id).strip())

        for chat_id in list(dict.fromkeys(chat_ids)):
            source = make_source(SourceKind.FEISHU.value, chat_id)
            self.session_manager.get_or_create_session(
                source,
                session_id=f"feishu:chat:{chat_id}",
            )

    async def _refresh_brain_runtime(self):
        self.main_adapter = create_adapter(self._get_main_provider())
        self.context_manager.set_adapter(self.main_adapter)
        self.brain.set_adapter(self.main_adapter)
        sys_prompt = self.config.get_prompt("soul")
        if not self.brain.is_initialized:
            await self.brain.init_brain(sys_prompt)
            return
        persisted_context = await self.context_manager.load_context()
        await self.brain.refresh_base_prompt(sys_prompt, persisted_context)

    async def _refresh_heart_runtime(self):
        self.heart_adapter = create_adapter(self._get_heart_provider())
        self.heart.set_adapter(self.heart_adapter)
        await self.heart.refresh_config()

    def get_config_snapshot(self) -> dict[str, dict[str, Any]]:
        return self.config.snapshot()

    def get_config_entry(self, key: str) -> dict[str, Any]:
        return self.config.describe_key(key)

    async def apply_config_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        applied_keys, warnings = self.config.apply_updates(updates)
        if not applied_keys:
            return {
                "applied_keys": [],
                "reloaded_components": [],
                "restart_required_keys": [],
                "warnings": warnings,
            }

        self.config.reload()
        reloaded_components: set[str] = set()
        restart_required = sorted(_RESTART_REQUIRED_KEYS.intersection(applied_keys))

        if "enable_gateway" in applied_keys:
            warnings.append("enable_gateway 已弃用，gateway 进程由 launcher 控制。")

        if _BRAIN_IMMEDIATE_KEYS.intersection(applied_keys):
            await self._refresh_brain_runtime()
            reloaded_components.add("brain")

        if _HEART_IMMEDIATE_KEYS.intersection(applied_keys):
            await self._refresh_heart_runtime()
            reloaded_components.add("heart")

        if _MEMORY_IMMEDIATE_KEYS.intersection(applied_keys):
            self.memory.refresh_config(self.config)
            reloaded_components.add("memory")

        if restart_required:
            warnings.append(
                "以下配置已写入，但需要重启 gateway 才能完全生效: "
                + ", ".join(restart_required)
            )

        return {
            "applied_keys": applied_keys,
            "reloaded_components": sorted(reloaded_components),
            "restart_required_keys": restart_required,
            "warnings": warnings,
        }

    async def brain_processor(self):
        shutdown = self.event_bus.shutdown_event
        queue = self.event_bus.inbound_queue

        while True:
            get_task = asyncio.create_task(queue.get())
            shutdown_task = asyncio.create_task(shutdown.wait())
            done, pending = await asyncio.wait(
                [get_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if shutdown_task in done:
                break

            event = get_task.result()
            if event.type == EventType.CONFIRM_RESPONSE.value:
                resolved = self.event_bus.resolve_confirmation(
                    event.accepted,
                    request_id=event.request_id,
                    session_id=event.session_id,
                )
                if not resolved:
                    await self.speaker.emit_error(
                        event.session_id,
                        "确认请求已失效或与当前会话不匹配",
                        make_source(SourceKind.SYSTEM.value, "confirm"),
                    )
                    continue
                status = "已确认" if event.accepted else "已拒绝"
                await self.speaker.emit_status(
                    event.session_id,
                    f"[确认回复] {status}",
                    make_source(SourceKind.SYSTEM.value, "confirm"),
                    metadata={"confirm_request_id": event.request_id},
                )
                continue

            if event.type == EventType.SIGNAL.value:
                input_info = {
                    "role": "system",
                    "content": f"系统后台心跳截获重要潜意识事务，请立刻作为内部处理：{event.content}",
                }
            else:
                input_info = {"role": event.role, "content": event.content}

            target = EventTarget(kind=TargetKind.CURRENT_SESSION.value)
            token = bind_event_context(
                session_id=event.session_id,
                source=event.source,
                target=target,
            )
            try:
                api_key = self.config.get("api_key") or ""
                api_url = self.config.get("api_url") or ""
                model = self.config.get("model") or ""

                stream_id = await self.speaker.emit_stream_start(
                    event.session_id,
                    self._brain_source,
                    target=target,
                )
                async for chunk in self.brain.input_brain(
                    event.session_id,
                    input_info,
                    api_key,
                    api_url,
                    model,
                ):
                    await self.speaker.emit_stream_chunk(
                        event.session_id,
                        chunk,
                        self._brain_source,
                        stream_id,
                        target=target,
                    )
                await self.speaker.emit_stream_end(
                    event.session_id,
                    self._brain_source,
                    stream_id,
                    target=target,
                )
            except Exception as e:
                logger.error("Brain 处理异常: %s\n%s", e, traceback.format_exc())
                await self.speaker.emit_error(
                    event.session_id,
                    str(e),
                    self._brain_source,
                    target=target,
                )
            finally:
                reset_event_context(token)

    async def setup(self):
        tools_schema_path = self.config.get("tools_schema_path") or "user/tools.json"
        mcp_servers = self.config.get_mcp_servers()

        await self.memory.init_memory(self.config)
        await self.tools_manager.init_tools(tools_schema_path, mcp_servers)
        await self._refresh_brain_runtime()
        await self.heart.init_heart()

        if not self.config.get_bool("enable_gateway", True):
            logger.warning("enable_gateway=false 已忽略；当前架构始终以 gateway 运行。")

        host = self.config.get("gateway_host") or "127.0.0.1"
        port = int(self.config.get("gateway_port") or 8000)
        self.gateway = FastAPIGateway(
            self.event_bus,
            self.session_manager,
            config_snapshot_getter=self.get_config_snapshot,
            config_item_getter=self.get_config_entry,
            config_updater=self.apply_config_updates,
        )
        self.speaker.register_adapter(TargetKind.WEB.value, self.gateway.output_adapter)
        await self.gateway.start(host=host, port=port)

        if self.config.get_bool("enable_feishu_bot"):
            self.feishu_input = FeishuInputAdapter(
                self.event_bus,
                self.session_manager,
                self.config,
            )
            self.feishu_output = FeishuOutputAdapter(self.config)
            await self.feishu_output.init()
            self.speaker.register_adapter(TargetKind.FEISHU.value, self.feishu_output)
            self._register_feishu_broadcast_targets()
            await self.feishu_input.run()

        logger.info("Gateway runtime 初始化完成")

    async def run(self):
        await self.setup()
        try:
            await asyncio.gather(
                self.brain_processor(),
                self.heart.heartbeat_processor(),
                self.proprioceptor.run(),
            )
        finally:
            await self.shutdown()

    async def shutdown(self):
        logger.info("正在关闭...")
        self.event_bus.request_shutdown()
        if self.gateway is not None:
            await self.gateway.stop()
        if self.feishu_input is not None:
            await self.feishu_input.close()
        if self.feishu_output is not None:
            await self.feishu_output.close()
        await self.mcp_manager.close_mcp_servers()
        await self.brain.close_brain()
        await self.heart.close_heart()
        await self.memory.close_memory()
        logger.info("所有资源已释放")
