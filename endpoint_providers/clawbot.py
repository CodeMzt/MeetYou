from __future__ import annotations

import asyncio
import logging

from adapters.clawbot_client import ClawBotClient
from core.config import ConfigManager
from core.logger import setup_logger
from endpoint_providers.common import ProviderEventBus, ProviderSessionManager, wait_until_stopped
from sensors.clawbot_wechat_adapter import (
    DEFAULT_STATE_FILE,
    ClawBotWechatInputAdapter,
    ClawBotWechatOutputService,
    ClawBotWechatStateStore,
)


logger = logging.getLogger("meetyou.endpoint_provider.clawbot")


async def run() -> None:
    setup_logger(enable_console=True, component="endpoint_clawbot_wechat")
    config = ConfigManager()
    if not config.get_bool("enable_clawbot_wechat_client", False):
        logger.info("ClawBot WeChat Endpoint Provider disabled by config.")
        return
    client = ClawBotClient(
        state_dir=str(config.get("clawbot_wechat_state_dir") or ""),
        base_url=str(config.get("clawbot_wechat_base_url") or ""),
        bot_agent=str(config.get("clawbot_wechat_bot_agent") or ""),
        channel_version=str(config.get("clawbot_wechat_channel_version") or ""),
        ilink_app_id=str(config.get("clawbot_wechat_ilink_app_id") or ""),
        ilink_app_client_version=str(config.get("clawbot_wechat_ilink_app_client_version") or ""),
        request_timeout_ms=int(config.get("clawbot_wechat_send_timeout_ms") or 15000),
        long_poll_timeout_ms=int(config.get("clawbot_wechat_poll_timeout_ms") or 35000),
    )
    state_store = ClawBotWechatStateStore(
        str(config.get("clawbot_wechat_state_file") or DEFAULT_STATE_FILE),
        flush_interval_ms=int(config.get("clawbot_wechat_state_flush_interval_ms") or 500),
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
        logger.info("ClawBot WeChat Endpoint Provider connected to Core through /endpoint/ws.")
        await wait_until_stopped()
    finally:
        await input_adapter.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
