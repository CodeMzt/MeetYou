from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from .config import (
    DEFAULT_CONFIG_PATH,
    RpiConfigError,
    load_rpi_endpoint_config,
)
from .connection import RpiEndpointRuntime
from .logging import setup_logging
from .registry import build_default_registry
from .runtime.operation_runner import OperationRunner
from .runtime.result_models import OperationRequest


async def run_endpoint(*, config_path: str | None, fake_gpio: bool) -> None:
    config = load_rpi_endpoint_config(config_path)
    config.require_token()
    runtime = RpiEndpointRuntime(config, force_fake_gpio=fake_gpio)
    await runtime.run()


async def run_simulation(*, config_path: str | None, fake_gpio: bool) -> dict[str, Any]:
    config = load_rpi_endpoint_config(config_path)
    registry = build_default_registry(config, force_fake_gpio=fake_gpio)
    runner = OperationRunner(
        registry,
        default_timeout_seconds=config.operation.default_timeout_seconds,
        max_timeout_seconds=config.operation.max_timeout_seconds,
    )
    events = []

    async def emit(event):
        events.append(event.to_payload(endpoint_id=config.executor_endpoint_id))

    echo = await runner.run(
        OperationRequest(
            operation_id="sim.echo",
            call_id="sim.call.echo",
            capability_name="rpi.echo",
            arguments={"text": "ok"},
            timeout_seconds=5,
        ),
        emit=emit,
    )
    system_info = await runner.run(
        OperationRequest(
            operation_id="sim.system_info",
            call_id="sim.call.system_info",
            capability_name="rpi.system.info",
            arguments={},
            timeout_seconds=5,
        ),
        emit=emit,
    )
    return {
        "ok": echo.succeeded and system_info.succeeded,
        "endpoint_id": config.executor_endpoint_id,
        "token": config.token_status(),
        "capabilities": registry.names(),
        "results": [echo.to_summary(), system_info.to_summary()],
        "events": events,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MeetYou Raspberry Pi Endpoint Provider")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to rpi endpoint JSON config")
    parser.add_argument("--simulate", action="store_true", help="Run local capability simulation without connecting to Core")
    parser.add_argument("--fake-gpio", action="store_true", help="Use fake GPIO backend for local development/testing")
    parser.add_argument("--log-level", default="INFO", help="Python logging level")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    setup_logging(level=args.log_level)
    try:
        if args.simulate:
            result = asyncio.run(run_simulation(config_path=args.config, fake_gpio=args.fake_gpio))
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            raise SystemExit(0 if result.get("ok") else 1)
        asyncio.run(run_endpoint(config_path=args.config, fake_gpio=args.fake_gpio))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except RpiConfigError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
