"""
MeetYou 多入口启动文件。

支持：
- 默认 launcher
- gateway 后端
- CIL 客户端
"""

import asyncio
import logging
import sys

from cil.client import CILClient
from core.app import App
from core.logger import setup_logger
from launcher import run_launcher


def _print_usage():
    print(
        "用法:\n"
        "  python main.py\n"
        "  python main.py launcher\n"
        "  python main.py gateway\n"
        "  python main.py cil\n"
    )


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "launcher").lower()

    if mode == "launcher":
        run_launcher()
        return

    if mode == "gateway":
        setup_logger(enable_console=True, component="gateway")
        logger = logging.getLogger("meetyou.main")
        try:
            app = App()
            asyncio.run(app.run())
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.exception("gateway 异常退出: %s: %s", type(e).__name__, e)
        return

    if mode == "cil":
        setup_logger(enable_console=False, component="cil")
        logger = logging.getLogger("meetyou.main")
        try:
            asyncio.run(CILClient().run())
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.exception("CIL 异常退出: %s: %s", type(e).__name__, e)
        return

    _print_usage()
    raise SystemExit(1)


if __name__ == "__main__":
    main()
