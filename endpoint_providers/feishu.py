from __future__ import annotations

import asyncio
import logging

from core.config import ConfigManager
from core.logger import setup_logger
from endpoint_providers.common import ProviderEventBus, ProviderSessionManager, wait_until_stopped
from sensors.feishu_input_adapter import FeishuInputAdapter
from sensors.feishu_output_adapter import FeishuOutputAdapter


logger = logging.getLogger("meetyou.endpoint_provider.feishu")


async def run() -> None:
    setup_logger(enable_console=True, component="endpoint_feishu")
    config = ConfigManager()
    output = FeishuOutputAdapter(config)
    input_adapter: FeishuInputAdapter | None = None
    await output.init()
    try:
        input_adapter = FeishuInputAdapter(
            ProviderEventBus(),
            ProviderSessionManager(),
            config,
            output_adapter=output,
        )
        await input_adapter.run()
        logger.info("Feishu Endpoint Provider connected to Core through /endpoint/ws.")
        await wait_until_stopped()
    finally:
        if input_adapter is not None:
            await input_adapter.close()
        await output.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
