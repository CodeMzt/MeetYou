from __future__ import annotations

import asyncio
import sys

from core.logger import setup_logger
from desktop_client.config import load_desktop_client_config


async def run_desktop_client() -> None:
    from desktop_client.backend import DesktopClientBackend

    config = load_desktop_client_config()
    backend = DesktopClientBackend(config)
    await backend.run()


def _print_usage() -> None:
    print(
        "用法:\n"
        "  python main.py desktop-client\n"
        "  python -m desktop_client\n"
        "  python -m desktop_client.main\n"
    )


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        _print_usage()
        raise SystemExit(1)
    setup_logger(enable_console=True, component="desktop-client")
    try:
        asyncio.run(run_desktop_client())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
