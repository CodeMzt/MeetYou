"""
轻量启动控制台。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from core.config import ConfigManager
from core.logger import setup_logger


class Launcher:
    def __init__(self):
        setup_logger(enable_console=True, component="launcher")
        self.project_root = Path(__file__).resolve().parent
        self.main_py = self.project_root / "main.py"
        self.python_executable = Path(sys.executable)
        self.config = ConfigManager()
        host = self.config.get("gateway_host") or "127.0.0.1"
        port = int(self.config.get("gateway_port") or 8000)
        self.service_base_url = f"http://{host}:{port}"

    @staticmethod
    def _escape_ps(value: str) -> str:
        return value.replace("'", "''")

    def _spawn_powershell(self, command: str):
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(
            ["powershell.exe", "-NoExit", "-Command", command],
            cwd=str(self.project_root),
            creationflags=creationflags,
        )

    def _build_python_command(self, subcommand: str) -> str:
        project_root = self._escape_ps(str(self.project_root))
        python_path = self._escape_ps(str(self.python_executable))
        main_path = self._escape_ps(str(self.main_py))
        return (
            f"Set-Location -LiteralPath '{project_root}'; "
            f"& '{python_path}' '{main_path}' {subcommand}"
        )

    def service_running(self) -> bool:
        try:
            with urlopen(f"{self.service_base_url}/health", timeout=1.5) as response:
                return response.status == 200
        except URLError:
            return False
        except Exception:
            return False

    def wait_for_service(self, timeout_seconds: float = 20.0) -> bool:
        time.sleep(1.0)
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self.service_running():
                return True
            time.sleep(0.5)
        return self.service_running()

    def start_service(self):
        if self.service_running():
            print(f"service 已在运行: {self.service_base_url}")
            return
        self._spawn_powershell(self._build_python_command("service"))
        if self.wait_for_service(timeout_seconds=45.0):
            print(f"service 已启动: {self.service_base_url}")
        else:
            print("service 已拉起新窗口，但健康检查尚未通过，请查看 service 窗口日志。")

    def ensure_service(self):
        if self.service_running():
            return
        print("service 未运行，正在自动拉起...")
        self.start_service()

    def start_cil(self):
        self.ensure_service()
        self._spawn_powershell(self._build_python_command("cil"))
        print("CIL 已在新窗口启动。")

    def start_ui(self):
        self.ensure_service()
        ui_root = self._escape_ps(str(self.project_root / "meetyou-ui"))
        command = f"Set-Location -LiteralPath '{ui_root}'; npm.cmd run dev"
        self._spawn_powershell(command)
        print("前端开发态 Electron 已在新窗口启动。")

    def print_help(self):
        print(
            "\n可用命令:\n"
            "  help\n"
            "  start service\n"
            "  start cil\n"
            "  start ui\n"
            "  status\n"
            "  exit\n"
        )

    def print_status(self):
        service_status = "running" if self.service_running() else "stopped"
        print(
            f"service: {service_status} ({self.service_base_url})\n"
            "CIL/UI 由独立窗口运行，launcher 不跟踪其 PID。"
        )

    def run(self):
        print("MeetYou Launcher")
        self.print_help()
        while True:
            try:
                command = input("launcher> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return

            if not command:
                continue
            if command in {"exit", "quit"}:
                return
            if command == "help":
                self.print_help()
                continue
            if command == "status":
                self.print_status()
                continue
            if command == "start service":
                self.start_service()
                continue
            if command == "start cil":
                self.start_cil()
                continue
            if command == "start ui":
                self.start_ui()
                continue
            print("未知命令，输入 help 查看帮助。")


def run_launcher():
    Launcher().run()
