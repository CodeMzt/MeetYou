import asyncio
import json
import threading
import types
import unittest
from unittest.mock import patch

from adapters import feishu_ws_client


class _FakeBuilder:
    def register_p2_im_message_receive_v1(self, handler):
        self.message_handler = handler
        return self

    def register_p2_im_message_message_read_v1(self, handler):
        self.read_handler = handler
        return self

    def register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(self, handler):
        self.chat_entered_handler = handler
        return self

    def build(self):
        return self


class _FakeDispatcherHandler:
    @staticmethod
    def builder(_encrypt_key, _verification_token):
        return _FakeBuilder()


class _FakeJSON:
    @staticmethod
    def marshal(data):
        return json.dumps(data)


class FeishuWSClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_restarts_when_lark_client_start_returns(self):
        started = []

        class _FakeLarkClient:
            def __init__(self, *_args, **_kwargs):
                self.stopped = False

            def start(self):
                started.append(self)

            def stop(self):
                self.stopped = True

        fake_lark = types.SimpleNamespace(
            JSON=_FakeJSON,
            LogLevel=types.SimpleNamespace(INFO="INFO"),
            EventDispatcherHandler=_FakeDispatcherHandler,
            ws=types.SimpleNamespace(Client=_FakeLarkClient),
        )

        client = feishu_ws_client.FeishuWSClient("app-id", "secret", lambda payload: None)
        client._reconnect_base_delay_seconds = 0.01  # noqa: SLF001
        client._reconnect_max_delay_seconds = 0.01  # noqa: SLF001

        with patch.object(feishu_ws_client, "lark", fake_lark):
            await client.start()
            for _ in range(100):
                if len(started) >= 2:
                    break
                await asyncio.sleep(0.01)
            await client.stop()

        self.assertGreaterEqual(len(started), 2)

    async def test_stop_signals_current_lark_client(self):
        started = threading.Event()
        stopped = threading.Event()
        clients = []

        class _BlockingLarkClient:
            def __init__(self, *_args, **_kwargs):
                self.stop_called = False
                clients.append(self)

            def start(self):
                started.set()
                for _ in range(100):
                    if self.stop_called:
                        stopped.set()
                        return
                    import time

                    time.sleep(0.01)

            def stop(self):
                self.stop_called = True

        fake_lark = types.SimpleNamespace(
            JSON=_FakeJSON,
            LogLevel=types.SimpleNamespace(INFO="INFO"),
            EventDispatcherHandler=_FakeDispatcherHandler,
            ws=types.SimpleNamespace(Client=_BlockingLarkClient),
        )

        client = feishu_ws_client.FeishuWSClient("app-id", "secret", lambda payload: None)
        client._reconnect_base_delay_seconds = 0.01  # noqa: SLF001

        with patch.object(feishu_ws_client, "lark", fake_lark):
            await client.start()
            await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=1)
            await client.stop()
            await asyncio.wait_for(asyncio.to_thread(stopped.wait, 1), timeout=1)

        self.assertTrue(clients)
        self.assertTrue(clients[0].stop_called)

    async def test_lark_sdk_loop_is_rebound_to_worker_thread(self):
        import lark_oapi
        import lark_oapi.ws.client as lark_ws_client

        observed = []
        main_loop = asyncio.get_running_loop()
        main_thread_id = threading.get_ident()
        lark_ws_client.loop = main_loop

        class _LoopInspectingLarkClient:
            def __init__(self, *_args, **_kwargs):
                pass

            def start(self):
                sdk_loop = lark_ws_client.loop
                observed.append(
                    {
                        "worker_thread": threading.get_ident() != main_thread_id,
                        "rebound": sdk_loop is not main_loop,
                        "loop_running": sdk_loop.is_running(),
                    }
                )

        client = feishu_ws_client.FeishuWSClient("app-id", "secret", lambda payload: None)
        client._reconnect_base_delay_seconds = 0.01  # noqa: SLF001
        client._reconnect_max_delay_seconds = 0.01  # noqa: SLF001

        with patch.object(feishu_ws_client, "lark", lark_oapi), patch.object(lark_oapi.ws, "Client", _LoopInspectingLarkClient):
            await client.start()
            for _ in range(100):
                if observed:
                    break
                await asyncio.sleep(0.01)
            await client.stop()

        self.assertTrue(observed)
        self.assertTrue(observed[0]["worker_thread"])
        self.assertTrue(observed[0]["rebound"])
        self.assertFalse(observed[0]["loop_running"])


if __name__ == "__main__":
    unittest.main()
