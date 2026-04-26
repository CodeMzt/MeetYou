from __future__ import annotations

import asyncio
import logging
import sys

from core.logger import setup_logger
from service_runtime.models import RuntimeCommand, RuntimeError

ServiceRuntime = None


def _print_usage() -> None:
    print(
        "用法:\n"
        "  python main.py launcher\n"
        "  python main.py service\n"
        "  python main.py cil\n"
        "  python -m service_runtime\n"
        "  python -m service_runtime.main [service|cil|launcher]\n"
    )


def _build_runtime_command(mode: str) -> RuntimeCommand:
    if mode == "launcher":
        return RuntimeCommand.launcher()
    if mode == "service":
        return RuntimeCommand.service()
    if mode == "cil":
        return RuntimeCommand.cil()
    raise ValueError(f"unsupported mode: {mode}")


def run_runtime_entry(mode: str) -> None:
    enable_console = mode != "cil"
    component = "cil" if mode == "cil" else mode
    exit_label = "CIL" if mode == "cil" else mode

    setup_logger(enable_console=enable_console, component=component)
    logger = logging.getLogger("meetyou.main")
    try:
        global ServiceRuntime
        if ServiceRuntime is None:
            from service_runtime.service import ServiceRuntime as _ServiceRuntime

            ServiceRuntime = _ServiceRuntime

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
        raise SystemExit(1) from exc


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    mode = (args[0] if args else "service").lower()
    if len(args) > 1 or mode not in {"launcher", "service", "cil"}:
        _print_usage()
        raise SystemExit(1)
    run_runtime_entry(mode)


if __name__ == "__main__":
    main()
