"""
应用级依赖注入容器与生命周期管理。

App 类统一创建、注入、启动和关闭所有模块，
消除所有循环依赖和模块级全局单例。
"""

import asyncio
import logging
import traceback

from adapters.base import create_adapter
from core.brain import Brain
from core.context import ContextManager
from core.config import ConfigManager
from core.event_bus import EventBus
from core.exceptions import ExceptionRouter, MeetYouError
from core.heart import Heart
from core.io_protocol import EventTarget, EventType, SourceKind, TargetKind, make_source
from core.logger import setup_logger
from core.runtime_context import bind_event_context, reset_event_context
from core.session_manager import SessionManager
from core.speaker import Speaker
from core.tools_manager import ToolsManager
from gateway.api import FastAPIGateway
from platform_layer.detector import detect_platform
from sensors.cli_input_adapter import CLIInputAdapter
from sensors.cli_output_adapter import CLIOutputAdapter
from sensors.feishu_input_adapter import FeishuInputAdapter
from sensors.feishu_output_adapter import FeishuOutputAdapter
from sensors.proprioceptor import Proprioceptor
from tools import system_tools
from tools.mcp import MCPManager
from tools.memory import Memory

logger = logging.getLogger("meetyou.app")


class App:
    """
    应用级 DI 容器 + 生命周期管理器。

    按依赖顺序创建所有模块实例，注入依赖，
    管理启动和关闭流程。
    """

    def __init__(self):
        # Phase 1: 基础设施
        setup_logger()
        self.event_bus = EventBus()
        self.exception_router = ExceptionRouter()

        # Phase 2: 配置
        self.config = ConfigManager()

        # Phase 3: 平台层
        self.platform = detect_platform()

        # Phase 4: 适配器
        main_provider = self.config.get("api_provider") or "openai"
        heart_provider = self.config.get("heartbeat_api_provider") or main_provider
        self.main_adapter = create_adapter(main_provider)
        self.heart_adapter = create_adapter(heart_provider)

        # Phase 5: 工具层
        self.memory = Memory()
        self.mcp_manager = MCPManager()
        system_tools.init_system_tools(
            self.platform,
            self.event_bus,
            self.config.get("cmd_policy_path") or "user/cmd_policy.json",
        )

        # Phase 6: 核心模块
        self.context_manager = ContextManager(
            self.memory, self.main_adapter, self.event_bus
        )
        self.tools_manager = ToolsManager(
            self.memory, self.context_manager, self.mcp_manager, system_tools
        )
        self.brain = Brain(
            self.main_adapter, self.tools_manager, self.context_manager,
            self.event_bus, self.exception_router
        )
        self.heart = Heart(
            self.heart_adapter, self.config, self.tools_manager,
            self.memory, self.event_bus, self.exception_router
        )

        # Phase 7: 感知与 IO
        self.session_manager = SessionManager()
        self.speaker = Speaker(self.session_manager)
        self.cli_input = CLIInputAdapter(self.event_bus, self.session_manager)
        self.cli_output = CLIOutputAdapter(
            self.cli_input.app,
            self.cli_input.output_field,
            self.cli_input.input_field,
        )
        self.speaker.register_adapter(TargetKind.CLI.value, self.cli_output)
        self.gateway: FastAPIGateway | None = None
        self.feishu_input: FeishuInputAdapter | None = None
        self.feishu_output: FeishuOutputAdapter | None = None
        self.proprioceptor = Proprioceptor(
            self.platform, self.context_manager, self.event_bus
        )
        self._brain_source = make_source(SourceKind.SYSTEM.value, "brain")

        # 注册异常回调
        self.exception_router.on_system_error(self._log_error)
        self.exception_router.on_user_error(self._display_error)
        self.event_bus.subscribe(self.event_bus.CONFIRM_REQUEST, self._handle_confirm_request)

        logger.info("App 依赖注入完成")

    # ============================================================
    # 异常回调
    # ============================================================

    async def _log_error(self, error: MeetYouError):
        """系统级异常 → 写日志"""
        logger.error(f"[SYSTEM] {type(error).__name__}: {error}")

    async def _display_error(self, error: MeetYouError):
        """用户级异常 → 输出到界面"""
        await self.speaker.emit_error(
            self.cli_input.session_id,
            str(error),
            make_source(SourceKind.SYSTEM.value, "exception"),
        )

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

    # ============================================================
    # 核心处理协程
    # ============================================================

    async def brain_processor(self):
        """主控大脑逻辑：监听输入事件，通过模型获取回复。"""
        api_key = self.config.get("api_key") or ""
        api_url = self.config.get("api_url") or ""
        model = self.config.get("model") or ""

        # 启动问候
        start_prompt = self.config.get_prompt("start")
        input_info = {"role": "user", "content": start_prompt}
        startup_target = EventTarget(kind=TargetKind.BROADCAST.value)
        stream_id = await self.speaker.emit_stream_start(
            self.cli_input.session_id,
            self._brain_source,
            target=startup_target,
        )
        async for chunk in self.brain.input_brain(
            self.cli_input.session_id,
            input_info,
            api_key,
            api_url,
            model,
        ):
            await self.speaker.emit_stream_chunk(
                self.cli_input.session_id,
                chunk,
                self._brain_source,
                stream_id,
                target=startup_target,
            )
        await self.speaker.emit_stream_end(
            self.cli_input.session_id,
            self._brain_source,
            stream_id,
            target=startup_target,
        )

        # 主循环
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
                logger.error(f"Brain 处理异常: {e}\n{traceback.format_exc()}")
                await self.speaker.emit_error(
                    event.session_id,
                    str(e),
                    self._brain_source,
                    target=target,
                )
            finally:
                reset_event_context(token)

    # ============================================================
    # 生命周期
    # ============================================================

    async def setup(self):
        """异步初始化所有模块。"""
        tools_schema_path = self.config.get("tools_schema_path") or "user/tools.json"
        mcp_servers = self.config.get_mcp_servers()

        await self.memory.init_memory(self.config)
        await self.tools_manager.init_tools(tools_schema_path, mcp_servers)

        sys_prompt = self.config.get_prompt("soul")
        await self.brain.init_brain(sys_prompt)
        await self.heart.init_heart()

        if self.config.get_bool("enable_gateway"):
            self.gateway = FastAPIGateway(self.event_bus, self.session_manager)
            self.speaker.register_adapter(TargetKind.WEB.value, self.gateway.output_adapter)
            host = self.config.get("gateway_host") or "127.0.0.1"
            port = int(self.config.get("gateway_port") or 8000)
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

        logger.info("所有模块初始化完成")

    async def run(self):
        """启动所有核心协程。"""
        await self.setup()
        try:
            await asyncio.gather(
                self.brain_processor(),
                self.heart.heartbeat_processor(),
                self.cli_input.run(),
                self.proprioceptor.run(),
            )
        finally:
            await self.shutdown()

    async def shutdown(self):
        """优雅关闭所有资源。"""
        logger.info("正在关闭...")
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
