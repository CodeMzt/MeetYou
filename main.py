"""
MeetYou — 仿生认知架构 LLM 智能体

入口文件：创建 App 实例并启动异步事件循环。
"""

import asyncio
import logging

from core.app import App
from core.logger import setup_logger


if __name__ == "__main__":
    setup_logger()
    logger = logging.getLogger("meetyou.main")
    try:
        app = App()
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.exception("应用异常退出: %s: %s", type(e).__name__, e)
    finally:
        exit()
