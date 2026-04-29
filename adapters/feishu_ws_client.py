"""
飞书长连接客户端封装。
"""

import asyncio
import contextlib
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
        self._closed = False
        self._reconnect_base_delay_seconds = 1.0
        self._reconnect_max_delay_seconds = 60.0

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
        if self._task is not None and not self._task.done():
            return
        self._loop = asyncio.get_running_loop()
        self._closed = False
        self._task = asyncio.create_task(self._run_forever())

    async def _run_forever(self):
        delay = float(self._reconnect_base_delay_seconds)
        while not self._closed:
            client = None
            try:
                client = self._build_client()
                self._client = client
                await asyncio.to_thread(client.start)
                if not self._closed:
                    logger.warning("飞书长连接已停止，将在 %.1f 秒后重连", delay)
            except asyncio.CancelledError:
                raise
            except Exception:
                if not self._closed:
                    logger.exception("飞书长连接异常退出，将在 %.1f 秒后重连", delay)
            finally:
                if self._client is client:
                    self._client = None
            if self._closed:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, float(self._reconnect_max_delay_seconds))

    async def stop(self):
        self._closed = True
        client = self._client
        stop = getattr(client, "stop", None)
        if callable(stop):
            with contextlib.suppress(Exception):
                await asyncio.to_thread(stop)
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        self._client = None
