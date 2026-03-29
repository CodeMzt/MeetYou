"""
系统状态管理器。

维护系统当前运行状态，通过 EventBus 发布状态变更事件，
供 Listener 渲染实时状态栏。
"""

import asyncio
import logging
from enum import Enum

logger = logging.getLogger("meetyou.status")


class SystemStatus(str, Enum):
    """系统状态枚举"""
    INITIALIZING = "initializing"
    IDLE = "idle"
    THINKING = "thinking"
    STREAMING = "streaming"
    TOOL_CALLING = "tool_calling"
    SUMMARIZING = "summarizing"
    CONFIRMING = "confirming"
    HEARTBEAT = "heartbeat"
    SHUTTING_DOWN = "shutting_down"


# 状态 → (中文标签, prompt_toolkit 颜色样式)
STATUS_DISPLAY = {
    SystemStatus.INITIALIZING: ("系统初始化中", "fg:ansiyellow"),
    SystemStatus.IDLE:         ("等待输入",     "fg:ansigreen"),
    SystemStatus.THINKING:     ("思考中",       "fg:ansiblue"),
    SystemStatus.STREAMING:    ("回复中",       "fg:ansicyan"),
    SystemStatus.TOOL_CALLING: ("调用工具",     "fg:ansimagenta"),
    SystemStatus.SUMMARIZING:  ("上下文压缩中", "fg:ansiyellow"),
    SystemStatus.CONFIRMING:   ("等待用户确认", "fg:ansired"),
    SystemStatus.HEARTBEAT:    ("心跳处理中",   "fg:ansiyellow"),
    SystemStatus.SHUTTING_DOWN:("正在关闭",     "fg:ansired"),
}


class StatusManager:
    """
    可观察的系统状态管理器。

    模块通过 set() / set_async() 更新状态，
    变更事件自动通过 EventBus 发布给 UI 层。

    用法:
        status.set(SystemStatus.THINKING)
        status.set(SystemStatus.TOOL_CALLING, "exec_sys_cmd")
    """

    def __init__(self, event_bus):
        self._event_bus = event_bus
        self._status = SystemStatus.INITIALIZING
        self._detail = ""

    @property
    def current(self) -> SystemStatus:
        return self._status

    @property
    def detail(self) -> str:
        return self._detail

    @property
    def display_label(self) -> str:
        """当前状态的中文展示标签"""
        label, _ = STATUS_DISPLAY.get(self._status, ("未知", ""))
        if self._detail:
            return f"{label}: {self._detail}"
        return label

    @property
    def display_style(self) -> str:
        """当前状态的颜色样式"""
        _, style = STATUS_DISPLAY.get(self._status, ("", ""))
        return style

    def set(self, status: SystemStatus, detail: str = ""):
        """
        同步更新状态。

        在有 running loop 的上下文中会通过 call_soon 调度事件发布。
        """
        self._status = status
        self._detail = detail
        # 尝试异步发布事件
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._publish())
        except RuntimeError:
            pass  # 没有 event loop 时（如纯同步上下文）静默跳过

    async def set_async(self, status: SystemStatus, detail: str = ""):
        """异步更新状态并发布事件。"""
        self._status = status
        self._detail = detail
        await self._publish()

    async def _publish(self):
        """发布状态变更事件"""
        await self._event_bus.publish(
            self._event_bus.STATUS_CHANGE,
            {
                "status": self._status,
                "detail": self._detail,
                "label": self.display_label,
                "style": self.display_style,
            },
        )
