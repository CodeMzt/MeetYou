from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from adapters.clawbot_client import (
    DEFAULT_CLAWBOT_ILINK_BASE_URL,
    ClawBotClient,
)
from core.config import ConfigManager
from core.logger import setup_logger
from core.persistence import atomic_write_text
from endpoint_providers.common import ProviderEventBus, ProviderSessionManager, wait_until_stopped
from sensors.clawbot_wechat_adapter import (
    DEFAULT_STATE_FILE,
    ClawBotWechatInputAdapter,
    ClawBotWechatOutputService,
    ClawBotWechatStateStore,
)


logger = logging.getLogger("meetyou.endpoint_provider.clawbot")


def _build_client(config: ConfigManager) -> ClawBotClient:
    return ClawBotClient(
        base_url=str(config.get("clawbot_ilink_base_url") or DEFAULT_CLAWBOT_ILINK_BASE_URL),
        bot_token=str(config.get("clawbot_ilink_bot_token") or ""),
        bot_id=str(config.get("clawbot_ilink_bot_id") or ""),
        ilink_user_id=str(config.get("clawbot_ilink_user_id") or ""),
        channel_version=str(config.get("clawbot_ilink_channel_version") or ""),
        ilink_app_client_version=str(config.get("clawbot_ilink_app_client_version") or ""),
        route_tag=str(config.get("clawbot_ilink_route_tag") or ""),
        request_timeout_ms=int(config.get("clawbot_ilink_send_timeout_ms") or 15000),
        long_poll_timeout_ms=int(config.get("clawbot_ilink_poll_timeout_ms") or 35000),
    )


async def login(args: argparse.Namespace) -> int:
    setup_logger(enable_console=True, component="endpoint_clawbot_login")
    config = ConfigManager()
    client = _build_client(config)
    try:
        qrcode = await client.get_bot_qrcode()
        output_path = Path(args.qr_output or "user/clawbot-ilink-login-qr.txt")
        text = (
            "ClawBot iLink login QR\n"
            f"qrcode={qrcode.qrcode}\n"
            f"url={qrcode.display_url}\n"
            "Open this URL or scan the QR in WeChat, then keep this command running until confirmation.\n"
        )
        atomic_write_text(str(output_path), text)
        print(text.strip())
        deadline = asyncio.get_running_loop().time() + float(args.timeout_seconds)
        poll_interval_seconds = max(float(args.poll_interval_seconds), 0.1)
        status_timeout_ms = max(int(float(args.status_timeout_seconds) * 1000), 1000)
        while asyncio.get_running_loop().time() < deadline:
            try:
                status = await client.get_qrcode_status(qrcode.qrcode, timeout_ms=status_timeout_ms)
            except asyncio.TimeoutError:
                logger.info(
                    "ClawBot iLink QR status poll timed out after %.1fs; retrying.",
                    status_timeout_ms / 1000,
                )
                await asyncio.sleep(poll_interval_seconds)
                continue
            status_text = status.status or "unknown"
            logger.info("ClawBot iLink QR status: %s", status_text)
            if status.expired:
                print("二维码已过期，请重新运行 `python -m endpoint_providers.clawbot login`。")
                return 2
            if status.confirmed:
                updates: dict[str, object] = {
                    "clawbot_ilink_bot_token": status.bot_token,
                    "clawbot_ilink_base_url": status.base_url or client.base_url,
                    "clawbot_ilink_bot_id": status.ilink_bot_id,
                    "clawbot_ilink_user_id": status.ilink_user_id,
                }
                if args.enable:
                    updates["enable_clawbot_wechat_client"] = True
                applied, _ = config.apply_updates({key: value for key, value in updates.items() if str(value or "").strip()})
                state_store = ClawBotWechatStateStore(str(config.get("clawbot_ilink_state_file") or DEFAULT_STATE_FILE))
                await state_store.clear_cursor(reason="login")
                await state_store.close()
                print("ClawBot iLink 登录成功，已写入 MeetYou 配置。")
                print("更新配置项: " + ", ".join(applied))
                return 0
            await asyncio.sleep(poll_interval_seconds)
        print("等待扫码确认超时，请重新运行登录命令。")
        return 3
    finally:
        await client.close()


async def run() -> None:
    setup_logger(enable_console=True, component="endpoint_clawbot_wechat")
    config = ConfigManager()
    if not config.get_bool("enable_clawbot_wechat_client", False):
        logger.info("ClawBot iLink WeChat Endpoint Provider disabled by config.")
        return
    client = _build_client(config)
    logger.info(
        "ClawBot iLink provider config token_present=%s base_url=%s bot_id_present=%s user_id_present=%s state_file=%s core_base_url=%s",
        bool(config.get("clawbot_ilink_bot_token")),
        str(config.get("clawbot_ilink_base_url") or DEFAULT_CLAWBOT_ILINK_BASE_URL),
        bool(config.get("clawbot_ilink_bot_id")),
        bool(config.get("clawbot_ilink_user_id")),
        str(config.get("clawbot_ilink_state_file") or DEFAULT_STATE_FILE),
        str(config.get("core_base_url") or ""),
    )
    state_store = ClawBotWechatStateStore(
        str(config.get("clawbot_ilink_state_file") or DEFAULT_STATE_FILE),
        flush_interval_ms=int(config.get("clawbot_ilink_state_flush_interval_ms") or 500),
    )
    output = ClawBotWechatOutputService(
        config=config,
        client=client,
        state_store=state_store,
    )
    input_adapter = ClawBotWechatInputAdapter(
        ProviderEventBus(),
        ProviderSessionManager(),
        config,
        client=client,
        state_store=state_store,
        output_adapter=output,
    )
    try:
        await input_adapter.run()
        logger.info("ClawBot iLink WeChat Endpoint Provider connected to Core through /endpoint/ws.")
        await wait_until_stopped()
    finally:
        await input_adapter.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m endpoint_providers.clawbot")
    subparsers = parser.add_subparsers(dest="command")
    login_parser = subparsers.add_parser("login", help="Authorize ClawBot iLink by QR code and store MeetYou credentials")
    login_parser.add_argument("--qr-output", default="user/clawbot-ilink-login-qr.txt")
    login_parser.add_argument("--timeout-seconds", type=float, default=480)
    login_parser.add_argument("--poll-interval-seconds", type=float, default=2)
    login_parser.add_argument("--status-timeout-seconds", type=float, default=30)
    login_parser.add_argument("--enable", action="store_true", help="also set enable_clawbot_wechat_client=true")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "login":
            raise SystemExit(asyncio.run(login(args)))
        asyncio.run(run())
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main(sys.argv[1:])
