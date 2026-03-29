"""
事件总线：解耦模块间通信。

所有模块通过发布/订阅事件进行交互，不再直接持有彼此引用。
同时承载原 context_manager 的 shutdown_event 和 sensory_queue 职责。
"""

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger("meetyou.event_bus")


class EventBus:
    """
    发布/订阅模式的事件总线。

    事件类型常量定义了系统内所有标准事件。
    模块通过 subscribe() 注册监听，通过 publish() 发布事件。
    """

    # ---- 事件类型常量 ----
    USER_INPUT = "user_input"
    HEART_SIGNAL = "heart_signal"
    SYSTEM_OUTPUT = "system_output"
    AI_OUTPUT = "ai_output"
    SHUTDOWN = "shutdown"
    ERROR = "error"
    CONFIRM_REQUEST = "confirm_request"

    def __init__(self):
        self._subscribers: dict[str, list] = defaultdict(list)
        self._shutdown_event = asyncio.Event()
        self._sensory_queue: asyncio.Queue = asyncio.Queue()
        self._pending_confirmation: asyncio.Future | None = None

    # ---- 核心信号 ----

    @property
    def shutdown_event(self) -> asyncio.Event:
        """全局关闭信号"""
        return self._shutdown_event

    @property
    def sensory_queue(self) -> asyncio.Queue:
        """感知信息队列（用户输入、心跳信号等）"""
        return self._sensory_queue

    def request_shutdown(self):
        """触发全局关闭"""
        self._shutdown_event.set()
        logger.info("全局关闭信号已触发")

    # ---- 用户确认机制 ----

    async def request_confirmation(self, prompt: str, timeout: float = 30.0) -> bool:
        """
        请求用户确认。

        发布 CONFIRM_REQUEST 事件（由 Listener 展示给用户），
        然后等待用户通过 resolve_confirmation() 回复 yes/no。

        Args:
            prompt: 展示给用户的确认提示文本
            timeout: 等待超时秒数，超时视为拒绝

        Returns:
            bool: 用户是否确认
        """
        loop = asyncio.get_running_loop()
        self._pending_confirmation = loop.create_future()

        await self.publish(self.CONFIRM_REQUEST, {"prompt": prompt})

        try:
            result = await asyncio.wait_for(self._pending_confirmation, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.info(f"用户确认超时（{timeout}s），默认拒绝")
            return False
        finally:
            self._pending_confirmation = None

    def resolve_confirmation(self, accepted: bool):
        """
        由 Listener 调用：用户回复了确认请求。

        Args:
            accepted: 用户是否同意
        """
        if self._pending_confirmation and not self._pending_confirmation.done():
            self._pending_confirmation.set_result(accepted)

    @property
    def has_pending_confirmation(self) -> bool:
        """是否有等待中的确认请求"""
        return self._pending_confirmation is not None and not self._pending_confirmation.done()

    # ---- 发布/订阅 ----

    def subscribe(self, event_type: str, callback):
        """
        订阅事件。

        Args:
            event_type: 事件类型字符串
            callback: 回调函数（支持同步和异步）
        """
        self._subscribers[event_type].append(callback)

    async def publish(self, event_type: str, data=None):
        """
        发布事件，依次通知所有订阅者。

        Args:
            event_type: 事件类型字符串
            data: 要传递给回调的数据
        """
        for callback in self._subscribers[event_type]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                logger.error(f"事件回调异常 [{event_type}]: {e}")
