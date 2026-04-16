from __future__ import annotations

import asyncio
import sys

from core.logger import setup_logger
from desktop_agent.config import load_desktop_agent_config
from desktop_agent.runtime import DesktopAgentRuntime


async def run_desktop_agent() -> None:
    config = load_desktop_agent_config()
    runtime = DesktopAgentRuntime(config)
    await runtime.run()


def _print_usage() -> None:
    print(
        "用法:\n"
        "  python main.py desktop-agent\n"
        "  python -m desktop_agent\n"
        "  python -m desktop_agent.main\n"
    )


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        _print_usage()
        raise SystemExit(1)
    setup_logger(enable_console=True, component="desktop-agent")
    try:
        asyncio.run(run_desktop_agent())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
