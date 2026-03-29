"""
Windows 平台适配器（插头）。

使用 uiautomation + win32process + psutil 实现完整的 Windows 平台能力。
"""

import logging

import psutil

from platform_layer.base import PlatformAdapter

logger = logging.getLogger("meetyou.platform.windows")


class WindowsPlatformAdapter(PlatformAdapter):
    """Windows 平台适配器 — 完整实现"""

    _DEFAULT_IGNORE = [
        "svchost.exe", "system", "runtimebroker.exe", "conhost.exe",
        "taskhostw.exe", "explorer.exe", "taskmgr.exe",
    ]

    def get_ui_context(self) -> dict:
        try:
            import uiautomation as auto
            import win32process

            _thInit = auto.UIAutomationInitializerInThread()
            cx, cy = auto.GetCursorPos()
            hovered = auto.ControlFromPoint(cx, cy)

            if not hovered:
                return {"status": "no_control_detected"}

            context = {
                "ui_type": hovered.ControlTypeName,
                "ui_name": hovered.Name,
                "ui_value": "",
                "ui_rectangle": str(hovered.BoundingRectangle),
            }

            try:
                context["ui_value"] = hovered.GetValuePattern().Value
            except Exception:
                pass

            hwnd = hovered.NativeWindowHandle
            if hwnd:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    context["app_name"] = psutil.Process(pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    context["app_name"] = "unknown"

            return context
        except ImportError:
            return {"status": "ui_automation_unavailable"}
        except Exception as e:
            logger.debug(f"获取 UI 上下文失败: {e}")
            return {"status": f"error: {e}"}

    def get_running_apps(self, ignore_list=None, mem_threshold=0.5) -> list[str]:
        ignore = ignore_list or self._DEFAULT_IGNORE
        apps = []
        for proc in psutil.process_iter(["name", "memory_percent"]):
            try:
                name = proc.info["name"]
                mem = proc.info["memory_percent"]
                if name not in ignore and mem is not None and mem > mem_threshold:
                    apps.append(name.replace(".exe", ""))
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
        try:
            return raw_bytes.decode("gbk")
        except UnicodeDecodeError:
            return raw_bytes.decode("utf-8", errors="replace")

    def get_default_shell(self) -> str:
        return "cmd"
