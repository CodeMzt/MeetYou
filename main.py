"""MeetYou 开发态统一入口。"""

from __future__ import annotations

import sys


def _print_usage() -> None:
    print(
        "用法:\n"
        "  python main.py\n"
        "  python main.py launcher\n"
        "  python main.py service\n"
        "  python main.py cil\n"
        "  python main.py desktop-client\n"
        "  python main.py edge-client\n"
        "\n生产可分离入口:\n"
        "  python -m service_runtime\n"
        "  python -m desktop_client\n"
        "  python -m edge_client\n"
    )


def _run_service_mode(mode: str) -> None:
    from service_runtime.main import main as service_runtime_main

    service_runtime_main([mode])


def _run_desktop_client_mode() -> None:
    from desktop_client.main import main as desktop_client_main

    desktop_client_main([])


def _run_edge_client_mode() -> None:
    from edge_client.main import main as edge_client_main

    edge_client_main([])


def main() -> None:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "launcher").lower()

    if mode == "launcher":
        _run_service_mode("launcher")
        return

    if mode == "service":
        _run_service_mode("service")
        return

    if mode == "cil":
        _run_service_mode("cil")
        return

    if mode == "desktop-client":
        _run_desktop_client_mode()
        return

    if mode == "edge-client":
        _run_edge_client_mode()
        return

    _print_usage()
    raise SystemExit(1)


if __name__ == "__main__":
    main()
