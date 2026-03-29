"""
Linux 平台适配器（插头）— 基础实现。

UI 感知标记为不支持，其余使用 psutil 跨平台能力。
"""

import logging

import psutil

from platform_layer.base import PlatformAdapter

logger = logging.getLogger("meetyou.platform.linux")


class LinuxPlatformAdapter(PlatformAdapter):
    """Linux 平台适配器 — 基础实现"""

    _DEFAULT_IGNORE = ["systemd", "kthreadd", "init", "snapd"]

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

    def decode_command_output(self, raw_bytes: bytes) -> str:
        return raw_bytes.decode("utf-8", errors="replace")

    def get_default_shell(self) -> str:
        return "bash"
