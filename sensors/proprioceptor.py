"""
本体感受器。

定期通过平台抽象层获取系统环境信息（UI 控件、运行应用等），
更新到 ContextManager 供 Brain 使用。
"""

import asyncio
import time
import logging

logger = logging.getLogger("meetyou.proprioceptor")


class Proprioceptor:
    """
    本体感受器。

    使用平台适配器获取系统环境信息，注入到 ContextManager。
    """

    def __init__(self, platform_adapter, context_manager, event_bus):
        """
        Args:
            platform_adapter: PlatformAdapter 实例
            context_manager: ContextManager 实例
            event_bus: EventBus 实例
        """
        self._platform = platform_adapter
        self._context = context_manager
        self._event_bus = event_bus

    def _fetch_info(self) -> tuple[dict, list]:
        """同步获取 UI 信息和运行应用列表（在线程中执行）"""
        ui_info = self._platform.get_ui_context()
        running_apps = self._platform.get_running_apps()
        return ui_info, running_apps

    async def run(self, interval_seconds: float = 5.0):
        """
        异步轮询运行，定期刷新感知信息。

        Args:
            interval_seconds: 刷新间隔（秒）
        """
        shutdown = self._event_bus.shutdown_event

        while not shutdown.is_set():
            try:
                ui_info, running_apps = await asyncio.to_thread(self._fetch_info)
                if ui_info:
                    self._context.proprioception_info["ui_info"] = ui_info
                    self._context.proprioception_info["running_apps"] = running_apps
                    self._context.proprioception_info["last_update_time"] = time.time()
            except Exception as e:
                logger.error(f"感知信息获取失败: {e}")

            try:
                await asyncio.wait_for(shutdown.wait(), timeout=interval_seconds)
                break
            except asyncio.TimeoutError:
                pass
