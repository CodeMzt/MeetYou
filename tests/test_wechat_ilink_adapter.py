import tempfile
import unittest
from pathlib import Path

from adapters.wechat_ilink_client import WeChatIlinkCredentials
from core.event_bus import EventBus
from core.session_manager import SessionManager
from sensors.wechat_ilink_adapter import (
    WeChatIlinkStateStore,
    WeChatInputAdapter,
    WeChatOutputService,
    split_text_naturally,
)


class _Config:
    def __init__(self, **values):
        self.values = {
            "gateway_host": "127.0.0.1",
            "gateway_port": 8000,
            "gateway_access_token": "",
            "wechat_ilink_max_text_chars": 2000,
            **values,
        }

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeGatewayClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.messages = []
        self.confirm_responses = []
        self.input_responses = []
        self.commands = []
        self.closed = False

    async def start(self):
        self.started = True

    async def send_message(self, content, **kwargs):
        self.messages.append({"content": content, **kwargs})
        return {"message_id": "msg-core"}

    async def submit_confirm_response(self, **kwargs):
        self.confirm_responses.append(kwargs)
        return {}

    async def submit_human_input_response(self, **kwargs):
        self.input_responses.append(kwargs)
        return {}

    async def send_command(self, action, **payload):
        self.commands.append({"action": action, **payload})

    async def close(self):
        self.closed = True


class _FakeOutput:
    def __init__(self):
        self.events = []

    def get_pending_confirm_request(self, user_id):
        return None

    def resolve_human_input(self, user_id, raw_text):
        return None

    async def send_client_event(self, user_id, payload):
        self.events.append((user_id, payload))


class _FakeSessionManager:
    def __init__(self, credentials):
        self.credentials = credentials
        self.invalidated = False

    async def ensure_credentials(self):
        return self.credentials

    async def invalidate(self):
        self.invalidated = True


class _FakeIlinkClient:
    def __init__(self):
        self.sent = []
        self.inited = False
        self.closed = False

    async def init(self):
        self.inited = True

    async def close(self):
        self.closed = True

    async def send_text(self, credentials, **kwargs):
        self.sent.append({"credentials": credentials, **kwargs})
        return {"ret": 0}


class WeChatIlinkAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self._temp_dir.name)

    def tearDown(self):
        self._temp_dir.cleanup()

    async def test_state_store_persists_credentials_cursor_and_context_token(self):
        path = self.temp_root / "wechat_state.json"
        store = WeChatIlinkStateStore(str(path))
        credentials = WeChatIlinkCredentials(
            bot_token="bot-token",
            ilink_bot_id="bot-1",
            ilink_user_id="user-1",
            baseurl="https://example.com",
        )

        await store.set_credentials(credentials)
        await store.set_update_buf("cursor-1")
        await store.set_context_token("bot-1", "wx-user", "ctx-1")

        reloaded = WeChatIlinkStateStore(str(path))
        self.assertEqual(reloaded.get_credentials().bot_token, "bot-token")
        self.assertEqual(reloaded.get_update_buf(), "cursor-1")
        self.assertEqual(reloaded.get_context_token("bot-1", "wx-user"), "ctx-1")

    async def test_input_adapter_bridges_text_message_to_gateway_client(self):
        path = self.temp_root / "wechat_state.json"
        store = WeChatIlinkStateStore(str(path))
        await store.set_credentials(
            WeChatIlinkCredentials(bot_token="bot-token", ilink_bot_id="bot-1", ilink_user_id="wx-user")
        )
        output = _FakeOutput()
        created_clients = []

        def factory(**kwargs):
            client = _FakeGatewayClient(**kwargs)
            created_clients.append(client)
            return client

        adapter = WeChatInputAdapter(
            EventBus(),
            SessionManager(),
            _Config(wechat_ilink_token_file=str(path)),
            state_store=store,
            output_adapter=output,
            gateway_client_factory=factory,
        )
        message = {
            "from_user_id": "wx-user",
            "message_id": "wechat-msg-1",
            "session_id": "conv-1",
            "context_token": "ctx-1",
            "item_list": [{"type": 1, "text_item": {"text": "你好"}}],
        }

        await adapter.handle_messages([message])
        await adapter.handle_messages([message])

        self.assertEqual(store.get_context_token("bot-1", "wx-user"), "ctx-1")
        self.assertEqual(len(created_clients), 1)
        self.assertTrue(created_clients[0].started)
        self.assertEqual(len(created_clients[0].messages), 1)
        sent = created_clients[0].messages[0]
        self.assertEqual(sent["content"], "你好")
        self.assertEqual(sent["metadata"]["source"], "wechat")
        self.assertEqual(sent["metadata"]["transport"], "ilink")
        self.assertTrue(sent["metadata"]["context_token_present"])
        self.assertEqual(sent["client_message_id"], "wechat-msg-1")
        self.assertEqual(created_clients[0].kwargs["client_type"], "wechat")

    async def test_output_service_sends_chunks_with_cached_context_token(self):
        path = self.temp_root / "wechat_state.json"
        store = WeChatIlinkStateStore(str(path))
        credentials = WeChatIlinkCredentials(bot_token="bot-token", ilink_bot_id="bot-1")
        await store.set_credentials(credentials)
        await store.set_context_token("bot-1", "wx-user", "ctx-1")
        client = _FakeIlinkClient()
        output = WeChatOutputService(
            config=_Config(wechat_ilink_max_text_chars=5),
            client=client,
            session_manager=_FakeSessionManager(credentials),
            state_store=store,
        )

        await output.send_client_event(
            "wx-user",
            {
                "schema": "meetyou.client.ws.v1",
                "kind": "event",
                "event": {
                    "type": "message.completed",
                    "message": {"content": "hello world"},
                },
            },
        )

        self.assertEqual([item["text"] for item in client.sent], ["hello", "world"])
        self.assertTrue(all(item["context_token"] == "ctx-1" for item in client.sent))
        self.assertTrue(all(item["to_user_id"] == "wx-user" for item in client.sent))

    def test_split_text_prefers_natural_boundaries(self):
        self.assertEqual(split_text_naturally("hello world", limit=7), ["hello", "world"])


if __name__ == "__main__":
    unittest.main()
