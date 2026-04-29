"""
飞书长连接客户端封装。
"""

import asyncio
import contextlib
import importlib
import json
import logging
import threading
from typing import Any

logger = logging.getLogger("meetyou.feishu_ws")

# Intentionally lazy. lark_oapi captures an asyncio loop at import time; importing
# it inside Core's running event loop breaks the SDK when it is started from a
# worker thread.
lark = None


class FeishuWSClient:
    def __init__(self, app_id: str, app_secret: str, on_message):
        self._app_id = app_id
        self._app_secret = app_secret
        self._on_message = on_message
        self._loop = None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None
        self._client_exception: BaseException | None = None
        self._client = None
        self._closed = False
        self._reconnect_base_delay_seconds = 1.0
        self._reconnect_max_delay_seconds = 60.0

    def _load_lark(self):
        if lark is not None:
            return lark
        try:
            return importlib.import_module("lark_oapi")
        except ImportError as exc:
            raise RuntimeError("缺少 lark_oapi 依赖，无法启动飞书长连接客户端") from exc

    @staticmethod
    def _bind_lark_sdk_loop(lark_module: Any, loop: asyncio.AbstractEventLoop) -> None:
        if getattr(lark_module, "__name__", "") != "lark_oapi":
            return
        with contextlib.suppress(Exception):
            ws_client_module = importlib.import_module("lark_oapi.ws.client")
            setattr(ws_client_module, "loop", loop)

    def _build_client(self, lark_module):
        if lark_module is None:
            raise RuntimeError("缺少 lark_oapi 依赖，无法启动飞书长连接客户端")

        def handle_message(data):
            payload = json.loads(lark_module.JSON.marshal(data))
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
            lark_module.EventDispatcherHandler.builder("", "")
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

        log_level = getattr(lark_module.LogLevel, "WARNING", lark_module.LogLevel.INFO)
        return lark_module.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=log_level,
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
            try:
                self._client_exception = None
                thread = threading.Thread(
                    target=self._run_client_thread,
                    name="meetyou-feishu-ws",
                    daemon=True,
                )
                self._thread = thread
                thread.start()
                while not self._closed and thread.is_alive():
                    await asyncio.sleep(0.2)
                if self._client_exception is not None:
                    raise self._client_exception
                if not self._closed:
                    logger.warning("飞书长连接已停止，将在 %.1f 秒后重连", delay)
            except asyncio.CancelledError:
                raise
            except Exception:
                if not self._closed:
                    logger.exception("飞书长连接异常退出，将在 %.1f 秒后重连", delay)
            if self._closed:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, float(self._reconnect_max_delay_seconds))

    def _run_client_thread(self):
        try:
            self._run_client_once()
        except BaseException as exc:
            self._client_exception = exc

    def _run_client_once(self):
        client_loop = asyncio.new_event_loop()
        client = None
        self._client_loop = client_loop
        try:
            asyncio.set_event_loop(client_loop)
            client_loop.set_exception_handler(self._handle_lark_loop_exception)
            lark_module = self._load_lark()
            self._bind_lark_sdk_loop(lark_module, client_loop)
            client = self._build_client(lark_module)
            self._client = client
            client.start()
        finally:
            if self._client is client:
                self._client = None
            if self._client_loop is client_loop:
                self._client_loop = None
            with contextlib.suppress(Exception):
                tasks = list(asyncio.all_tasks(client_loop))
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks and not client_loop.is_closed():
                    client_loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            with contextlib.suppress(Exception):
                asyncio.set_event_loop(None)
            with contextlib.suppress(Exception):
                client_loop.close()

    def _handle_lark_loop_exception(self, loop, context):
        del loop
        if self._closed:
            return
        exception = context.get("exception")
        if exception is not None:
            logger.warning("Feishu long connection loop task failed: %s", exception)
            return
        logger.warning("Feishu long connection loop warning: %s", context.get("message", "unknown"))

    async def stop(self):
        self._closed = True
        client = self._client
        client_loop = self._client_loop
        if client is not None:
            with contextlib.suppress(Exception):
                setattr(client, "_auto_reconnect", False)
        stop = getattr(client, "stop", None)
        if callable(stop):
            with contextlib.suppress(Exception):
                await asyncio.to_thread(stop)
        elif client_loop is not None:
            disconnect = getattr(client, "_disconnect", None)
            if callable(disconnect):
                with contextlib.suppress(Exception):
                    future = asyncio.run_coroutine_threadsafe(disconnect(), client_loop)
                    await asyncio.wait_for(asyncio.wrap_future(future), timeout=2)
            with contextlib.suppress(Exception):
                client_loop.call_soon_threadsafe(client_loop.stop)
        thread = self._thread
        if thread is not None and thread.is_alive():
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.to_thread(thread.join, 3), timeout=4)
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=3)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._task
            self._task = None
        self._client = None
        self._client_loop = None
        self._thread = None
