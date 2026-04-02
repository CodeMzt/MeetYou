"""
飞书长连接客户端封装。
"""

import asyncio
import json
import logging

logger = logging.getLogger("meetyou.feishu_ws")

try:
    import lark_oapi as lark
except ImportError:
    lark = None


class FeishuWSClient:
    def __init__(self, app_id: str, app_secret: str, on_message):
        self._app_id = app_id
        self._app_secret = app_secret
        self._on_message = on_message
        self._loop = None
        self._task: asyncio.Task | None = None
        self._client = None

    def _build_client(self):
        if lark is None:
            raise RuntimeError("缺少 lark_oapi 依赖，无法启动飞书长连接客户端")

        def handle_message(data):
            payload = json.loads(lark.JSON.marshal(data))
            if self._loop is not None:
                future = asyncio.run_coroutine_threadsafe(self._on_message(payload), self._loop)

                def _log_async_failure(task_future):
                    try:
                        task_future.result()
                    except Exception:
                        logger.exception("Feishu 事件处理失败")

                future.add_done_callback(_log_async_failure)

        def handle_message_read(_data):
            return None

        def handle_bot_p2p_chat_entered(_data):
            return None

        builder = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(handle_message)
            .register_p2_im_message_message_read_v1(handle_message_read)
        )
        register_chat_entered = getattr(
            builder,
            "register_p2_im_chat_access_event_bot_p2p_chat_entered_v1",
            None,
        )
        if callable(register_chat_entered):
            builder = register_chat_entered(handle_bot_p2p_chat_entered)
        event_handler = builder.build()

        return lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

    async def start(self):
        if not self._app_id or not self._app_secret:
            logger.info("飞书配置不完整，跳过长连接启动")
            return
        self._loop = asyncio.get_running_loop()
        self._client = self._build_client()
        self._task = asyncio.create_task(asyncio.to_thread(self._client.start))

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass
            self._task = None
