from __future__ import annotations

import asyncio
import sys

from core.logger import setup_logger
from edge_client.config import load_edge_client_config


async def run_edge_client() -> None:
    from edge_client.runtime import EdgeClientRuntime

    config = load_edge_client_config()
    runtime = EdgeClientRuntime(config)
    await runtime.run()


def _print_usage() -> None:
    print(
        "用法:\n"
        "  python main.py edge-client\n"
        "  python -m edge_client\n"
        "  python -m edge_client.main\n"
    )


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        _print_usage()
        raise SystemExit(1)
    setup_logger(enable_console=True, component="edge-client")
    try:
        asyncio.run(run_edge_client())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
