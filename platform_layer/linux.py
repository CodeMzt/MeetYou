"""
Linux 平台适配器（插头）— 基础实现。

UI 感知标记为不支持，其余使用 psutil 提供运行宿主机感知。
"""

import logging

import psutil

from platform_layer.base import PlatformAdapter

logger = logging.getLogger("meetyou.platform.linux")


class LinuxPlatformAdapter(PlatformAdapter):
    """Linux 平台适配器 — 基础实现"""

    _DEFAULT_IGNORE = ["systemd", "kthreadd", "init", "snapd"]

    def describe_capabilities(self) -> dict:
        return {
            "ui_context": {
                "status": "disabled",
                "availability": "disabled",
                "supported_platforms": ["windows"],
                "windows_only": True,
                "notes": "Linux 下不提供 UI Automation 替代实现；get_ui_context() 固定返回 ui_automation_not_implemented_on_linux。",
            },
            "running_apps": {
                "status": "enabled",
                "availability": "full",
                "supported_platforms": ["windows", "linux", "macos"],
                "windows_only": False,
                "notes": "Linux 下继续提供运行进程感知。",
            },
            "system_vitals": {
                "status": "enabled",
                "availability": "full",
                "supported_platforms": ["windows", "linux", "macos"],
                "windows_only": False,
                "notes": "Linux 下继续提供 CPU、内存与电池状态。",
            },
        }

    def get_ui_context(self) -> dict:
        return {"status": "ui_automation_not_implemented_on_linux"}

    def get_running_apps(self, ignore_list=None, mem_threshold=0.5) -> list[str]:
        ignore = ignore_list or self._DEFAULT_IGNORE
        apps = []
        for proc in psutil.process_iter(["name", "memory_percent"]):
            try:
                name = proc.info["name"]
                mem = proc.info["memory_percent"]
                if name not in ignore and mem is not None and mem > mem_threshold:
                    apps.append(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return apps

    def get_system_vitals(self) -> dict:
        vitals = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_percent": psutil.virtual_memory().percent,
        }
        batt = psutil.sensors_battery()
        if batt:
            vitals["battery_percent"] = batt.percent
            vitals["is_plugged"] = batt.power_plugged
        return vitals
