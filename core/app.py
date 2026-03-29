"""
应用级依赖注入容器与生命周期管理。

App 类统一创建、注入、启动和关闭所有模块，
消除所有循环依赖和模块级全局单例。
"""

import asyncio
import logging
import traceback

from core.logger import setup_logger
from core.exceptions import ExceptionRouter, MeetYouError
from core.event_bus import EventBus
from core.config import ConfigManager
from adapters.base import create_adapter
from platform_layer.detector import detect_platform
from tools.memory import Memory
from tools.mcp import MCPManager
from tools import system_tools
from core.context import ContextManager
from core.tools_manager import ToolsManager
from core.brain import Brain
from core.heart import Heart
from sensors.listener import Listener
from sensors.proprioceptor import Proprioceptor

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
        self.listener = Listener(self.event_bus)
        self.proprioceptor = Proprioceptor(
            self.platform, self.context_manager, self.event_bus
        )

        # 注册异常回调
        self.exception_router.on_system_error(self._log_error)
        self.exception_router.on_user_error(self._display_error)

        logger.info("App 依赖注入完成")

    # ============================================================
    # 异常回调
    # ============================================================

    async def _log_error(self, error: MeetYouError):
        """系统级异常 → 写日志"""
        logger.error(f"[SYSTEM] {type(error).__name__}: {error}")

    async def _display_error(self, error: MeetYouError):
        """用户级异常 → 输出到界面"""
        self.listener.system_output(f"[错误] {error}")

    # ============================================================
    # 输出工具
    # ============================================================

    def output(self, text: str):
        """更新系统输出到界面"""
        text = text.replace("\r", "")
        self.listener.output_field.text += text
        self.listener.output_field.buffer.cursor_position = len(
            self.listener.output_field.text
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
        self.output("Mozart: ")
        input_info = {"role": "user", "content": start_prompt}
        async for chunk in self.brain.input_brain(input_info, api_key, api_url, model):
            self.output(chunk)
        self.output("\n")

        # 主循环
        shutdown = self.event_bus.shutdown_event
        queue = self.event_bus.sensory_queue

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

            if event["source"] == "user":
                input_info = {"role": "user", "content": event["content"]}
            elif event["source"] == "heart":
                input_info = {
                    "role": "system",
                    "content": f"系统后台心跳截获重要潜意识事务，请立刻作为内部处理：{event['content']}",
                }
            else:
                continue

            self.output("Mozart: ")
            try:
                async for chunk in self.brain.input_brain(
                    input_info, api_key, api_url, model
                ):
                    self.output(chunk)
            except Exception as e:
                logger.error(f"Brain 处理异常: {e}\n{traceback.format_exc()}")
                self.output(f"\n[系统错误] {e}")
            self.output("\n")

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

        logger.info("所有模块初始化完成")

    async def run(self):
        """启动所有核心协程。"""
        await self.setup()
        try:
            await asyncio.gather(
                self.brain_processor(),
                self.heart.heartbeat_processor(),
                self.listener.run(),
                self.proprioceptor.run(),
            )
        finally:
            await self.shutdown()

    async def shutdown(self):
        """优雅关闭所有资源。"""
        logger.info("正在关闭...")
        await self.mcp_manager.close_mcp_servers()
        await self.brain.close_brain()
        await self.heart.close_heart()
        await self.memory.close_memory()
        logger.info("所有资源已释放")
