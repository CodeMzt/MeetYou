"""
平台自动嗅探与工厂。

根据当前操作系统自动选择并实例化对应的平台适配器。
"""

import platform
import logging

from core.exceptions import PlatformError
from platform_layer.base import PlatformAdapter

logger = logging.getLogger("meetyou.platform.detector")

_SUPPORTED_PLATFORM_IDS = {
    "Windows": "windows",
    "Linux": "linux",
    "Darwin": "macos",
}


def normalize_platform_system(os_name: str) -> str:
    """
    将 `platform.system()` 返回值统一映射到仓库内部使用的 host_os 枚举。

    Returns:
        str: `windows` / `linux` / `macos`

    Raises:
        PlatformError: 不支持的操作系统
    """
    normalized = _SUPPORTED_PLATFORM_IDS.get(str(os_name or "").strip())
    if normalized:
        return normalized
    raise PlatformError(f"不支持的操作系统: {os_name}")


def detect_platform() -> PlatformAdapter:
    """
    自动嗅探当前操作系统并返回对应的平台适配器实例。

    Returns:
        PlatformAdapter: 当前平台的适配器

    Raises:
        PlatformError: 不支持的操作系统
    """
    os_name = platform.system()
    normalized = normalize_platform_system(os_name)

    if normalized == "windows":
        from platform_layer.windows import WindowsPlatformAdapter
        logger.info("检测到 Windows 平台")
        return WindowsPlatformAdapter()

    elif normalized == "linux":
        from platform_layer.linux import LinuxPlatformAdapter
        logger.info("检测到 Linux 平台")
        return LinuxPlatformAdapter()

    elif normalized == "macos":
        from platform_layer.macos import MacOSPlatformAdapter
        logger.info("检测到 macOS 平台")
        return MacOSPlatformAdapter()

    raise PlatformError(f"不支持的操作系统: {os_name}")
