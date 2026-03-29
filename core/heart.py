"""
系统心脏模块。

后台心跳循环：按设定间隔探测系统状态，
如果检测到需要处理的事务则投递到事件总线。
每次心跳兼顾记忆衰减。
"""

import asyncio
import logging

import aiohttp

logger = logging.getLogger("meetyou.heart")


class Heart:
    """
    系统心脏。

    使用独立的 LLMAdapter 进行轻量级后台推理，
    将有意义的检测结果通过 event_bus 通知大脑。
    """

    def __init__(self, adapter, config, tools_manager, memory, event_bus, exception_router):
        """
        Args:
            adapter: 心跳用的 LLMAdapter 实例
            config: ConfigManager 实例
            tools_manager: ToolsManager 实例
            memory: Memory 实例
            event_bus: EventBus 实例
            exception_router: ExceptionRouter 实例
        """
        self._adapter = adapter
        self._config = config
        self._tools_manager = tools_manager
        self._memory = memory
        self._event_bus = event_bus
        self._exception_router = exception_router

        self._prompt = ""
        self._interval = 60
        self._api_key = ""
        self._api_url = ""
        self._model = ""
        self._http_session: aiohttp.ClientSession | None = None

    async def init_heart(self):
        """从配置初始化心脏参数并创建 HTTP session。"""
        try:
            self._prompt = self._config.get_prompt("heartbeat")
        except Exception as e:
            logger.error(f"加载心跳提示词失败: {e}")

        self._interval = int(self._config.get("heartbeat_interval") or 60)
        self._api_url = self._config.get("heartbeat_api_url") or ""
        self._api_key = self._config.get("heartbeat_api_key") or ""
        self._model = self._config.get("heart_model") or ""
        self._http_session = aiohttp.ClientSession()
        logger.info(f"Heart 初始化完成: 间隔 {self._interval}s, 模型 {self._model}")

    async def close_heart(self):
        """关闭 HTTP session。"""
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
        logger.info("Heart 已关闭")

    async def heartbeat_processor(self):
        """
        心跳核心处理协程。

        按固定间隔发起非流式请求，检测后台状态。
        有意义的结果投递到 sensory_queue。
        每次循环触发记忆衰减。
        """
        shutdown = self._event_bus.shutdown_event

        while True:
            if shutdown.is_set():
                break

            if not self._api_url or not self._model:
                logger.warning("心跳配置不完整 (api_url 或 model 缺失)，跳过")
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=self._interval)
                    break
                except asyncio.TimeoutError:
                    continue

            if self._http_session is None:
                break

            # 等待工具 schema 就绪
            if not self._tools_manager.tools_schema_dict:
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=1.0)
                    break
                except asyncio.TimeoutError:
                    continue

            # 发起心跳请求（非流式）
            try:
                tools = self._tools_manager.get_heartbeat_tools()
                result = await self._adapter.chat(
                    self._http_session,
                    self._api_url,
                    self._api_key,
                    self._model,
                    [{"role": "user", "content": self._prompt}],
                    tools=tools,
                )

                output = (result.get("content") or "").strip()
                if output and output not in ("[HEARTBEAT_OK]", "HEARTBEAT_OK"):
                    await self._event_bus.sensory_queue.put({
                        "source": "heart",
                        "content": output,
                    })
            except Exception as e:
                logger.error(f"心跳请求失败: {e}")

            # 记忆衰减
            self._memory.fade_memory()

            # 等待下一个周期（或 shutdown）
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=self._interval)
                break
            except asyncio.TimeoutError:
                pass
