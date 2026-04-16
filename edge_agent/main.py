from __future__ import annotations

import asyncio
import sys

from core.logger import setup_logger
from edge_agent.config import load_edge_agent_config
from edge_agent.runtime import EdgeAgentRuntime


async def run_edge_agent() -> None:
    config = load_edge_agent_config()
    runtime = EdgeAgentRuntime(config)
    await runtime.run()


def _print_usage() -> None:
    print(
        "用法:\n"
        "  python main.py edge-agent\n"
        "  python -m edge_agent\n"
        "  python -m edge_agent.main\n"
    )


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        _print_usage()
        raise SystemExit(1)
    setup_logger(enable_console=True, component="edge-agent")
    try:
        asyncio.run(run_edge_agent())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
