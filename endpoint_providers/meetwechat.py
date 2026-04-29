from __future__ import annotations

import asyncio
import logging

from adapters.meetwechat_client import DEFAULT_MEETWECHAT_BASE_URL, MeetWeChatClient
from core.config import ConfigManager
from core.logger import setup_logger
from endpoint_providers.common import ProviderEventBus, ProviderSessionManager, wait_until_stopped
from sensors.meetwechat_adapter import (
    DEFAULT_STATE_FILE,
    MeetWeChatInputAdapter,
    MeetWeChatOutputService,
    MeetWeChatStateStore,
)


logger = logging.getLogger("meetyou.endpoint_provider.meetwechat")


async def run() -> None:
    setup_logger(enable_console=True, component="endpoint_meetwechat")
    config = ConfigManager()
    if not config.get_bool("enable_meetwechat_client", False):
        logger.info("MeetWeChat Endpoint Provider disabled by config.")
        return
    client = MeetWeChatClient(
        base_url=str(config.get("meetwechat_base_url") or DEFAULT_MEETWECHAT_BASE_URL),
    )
    state_store = MeetWeChatStateStore(
        str(config.get("meetwechat_state_file") or DEFAULT_STATE_FILE),
        flush_interval_ms=int(config.get("meetwechat_state_flush_interval_ms") or 500),
    )
    output = MeetWeChatOutputService(
        config=config,
        client=client,
        state_store=state_store,
    )
    input_adapter = MeetWeChatInputAdapter(
        ProviderEventBus(),
        ProviderSessionManager(),
        config,
        client=client,
        state_store=state_store,
        output_adapter=output,
    )
    try:
        await input_adapter.run()
        logger.info("MeetWeChat Endpoint Provider connected to Core through /endpoint/ws.")
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
