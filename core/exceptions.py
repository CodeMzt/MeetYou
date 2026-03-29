"""
MeetYou 异常层次体系与异常分发器

异常分为两大类：
- SystemLevelError: 系统级异常 → 通过日志记录/保存
- UserLevelError:   用户级异常 → 通过界面呈现给用户（CLI/前端）

ExceptionRouter: 负责根据异常类型将其路由到对应的回调函数。
"""

import asyncio
import logging

logger = logging.getLogger("meetyou.exceptions")


# ============================================================
# 基类
# ============================================================

class MeetYouError(Exception):
    """所有 MeetYou 异常的基类"""

    def __init__(self, message: str = "", detail: str = ""):
        super().__init__(message)
        self.detail = detail


# ============================================================
# 系统级异常 — 写日志、不直接展示给用户
# ============================================================

class SystemLevelError(MeetYouError):
    """系统级异常基类"""


class APIConnectionError(SystemLevelError):
    """API 连接/通信异常（网络超时、HTTP 错误等）"""


class MemorySystemError(SystemLevelError):
    """记忆系统内部异常（图谱损坏、向量化失败等）"""


class PlatformError(SystemLevelError):
    """平台相关异常（UIAutomation 不可用等）"""


class AdapterError(SystemLevelError):
    """LLM 适配器异常（响应解析失败等）"""


# ============================================================
# 用户级异常 — 输出到界面（CLI / 前端）
# ============================================================

class UserLevelError(MeetYouError):
    """用户级异常基类"""


class ConfigError(UserLevelError):
    """配置错误（文件不存在、字段缺失、格式错误等）"""


class ToolExecutionError(UserLevelError):
    """工具执行失败"""


class CommandBlockedError(UserLevelError):
    """命令被安全策略拦截"""


class FormatError(UserLevelError):
    """数据格式错误"""


# ============================================================
# 异常分发器
# ============================================================

class ExceptionRouter:
    """
    异常分发器。
    根据异常类型将其路由到对应的回调函数。

    用法:
        router = ExceptionRouter()
        router.on_system_error(lambda e: logger.error(str(e)))
        router.on_user_error(lambda e: display_to_user(str(e)))
        await router.route(some_error)
    """

    def __init__(self):
        self._system_callbacks: list = []
        self._user_callbacks: list = []

    def on_system_error(self, callback):
        """注册系统级异常回调（日志打印/保存）"""
        self._system_callbacks.append(callback)

    def on_user_error(self, callback):
        """注册用户级异常回调（输出到 CLI / 前端接口）"""
        self._user_callbacks.append(callback)

    async def route(self, error: MeetYouError):
        """异步版本：根据异常类型分发到对应回调"""
        if isinstance(error, UserLevelError):
            for cb in self._user_callbacks:
                if asyncio.iscoroutinefunction(cb):
                    await cb(error)
                else:
                    cb(error)
        # 系统级异常 (包括 MeetYouError 未分类的)
        if isinstance(error, SystemLevelError):
            for cb in self._system_callbacks:
                if asyncio.iscoroutinefunction(cb):
                    await cb(error)
                else:
                    cb(error)
        # 所有异常兜底写日志
        logger.error(f"[{type(error).__name__}] {error} | detail={error.detail}")

    def route_sync(self, error: MeetYouError):
        """同步版本：用于非异步上下文"""
        if isinstance(error, UserLevelError):
            for cb in self._user_callbacks:
                cb(error)
        if isinstance(error, SystemLevelError):
            for cb in self._system_callbacks:
                cb(error)
        logger.error(f"[{type(error).__name__}] {error} | detail={error.detail}")
