"""
平台自动嗅探与工厂。

根据当前操作系统自动选择并实例化对应的平台适配器。
"""

import platform
import logging

from core.exceptions import PlatformError
from platform_layer.base import PlatformAdapter

logger = logging.getLogger("meetyou.platform.detector")


def detect_platform() -> PlatformAdapter:
    """
    自动嗅探当前操作系统并返回对应的平台适配器实例。

    Returns:
        PlatformAdapter: 当前平台的适配器

    Raises:
        PlatformError: 不支持的操作系统
    """
    os_name = platform.system()

    if os_name == "Windows":
        from platform_layer.windows import WindowsPlatformAdapter
        logger.info("检测到 Windows 平台")
        return WindowsPlatformAdapter()

    elif os_name == "Linux":
        from platform_layer.linux import LinuxPlatformAdapter
        logger.info("检测到 Linux 平台")
        return LinuxPlatformAdapter()

    elif os_name == "Darwin":
        from platform_layer.macos import MacOSPlatformAdapter
        logger.info("检测到 macOS 平台")
        return MacOSPlatformAdapter()

    else:
        raise PlatformError(f"不支持的操作系统: {os_name}")
