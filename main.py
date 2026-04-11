"""
MeetYou 多入口启动文件。

支持：
- 默认 launcher
- service 后端
- CIL 客户端
- desktop-agent 本地执行器
- edge-agent 边缘执行器
"""

import asyncio
import logging
import sys

from core.logger import setup_logger
from desktop_agent.main import run_desktop_agent
from edge_agent.main import run_edge_agent
from service_runtime.models import RuntimeCommand, RuntimeError
from service_runtime.service import ServiceRuntime


def _print_usage():
    print(
        "用法:\n"
        "  python main.py\n"
        "  python main.py launcher\n"
        "  python main.py service\n"
        "  python main.py cil\n"
        "  python main.py desktop-agent\n"
        "  python main.py edge-agent\n"
    )


def _build_runtime_command(mode: str) -> RuntimeCommand:
    if mode == "launcher":
        return RuntimeCommand.launcher()
    if mode == "service":
        return RuntimeCommand.service()
    if mode == "cil":
        return RuntimeCommand.cil()
    raise ValueError(f"unsupported mode: {mode}")


def _run_runtime(mode: str, *, enable_console: bool, component: str, exit_label: str) -> None:
    setup_logger(enable_console=enable_console, component=component)
    logger = logging.getLogger("meetyou.main")
    try:
        asyncio.run(ServiceRuntime(_build_runtime_command(mode)).run())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        runtime_error = RuntimeError.from_exception(exc, code="runtime_entry_failed")
        logger.exception(
            "%s 异常退出: %s: %s",
            exit_label,
            runtime_error.code,
            runtime_error.message,
        )


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "launcher").lower()

    if mode == "launcher":
        _run_runtime("launcher", enable_console=True, component="launcher", exit_label="launcher")
        return

    if mode == "service":
        _run_runtime("service", enable_console=True, component="service", exit_label="service")
        return

    if mode == "cil":
        _run_runtime("cil", enable_console=False, component="cil", exit_label="CIL")
        return

    if mode == "desktop-agent":
        setup_logger(enable_console=True, component="desktop-agent")
        try:
            asyncio.run(run_desktop_agent())
        except KeyboardInterrupt:
            pass
        return

    if mode == "edge-agent":
        setup_logger(enable_console=True, component="edge-agent")
        try:
            asyncio.run(run_edge_agent())
        except KeyboardInterrupt:
            pass
        return

    _print_usage()
    raise SystemExit(1)


if __name__ == "__main__":
    main()
