"""
MeetYou — 仿生认知架构 LLM 智能体

入口文件：创建 App 实例并启动异步事件循环。
"""

import asyncio
import traceback

from core.app import App


if __name__ == "__main__":
    try:
        app = App()
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"你干啥了，我怎么被关了，你看看报错：{type(e).__name__}: {e}")
        print(traceback.format_exc())
    finally:
        exit()
