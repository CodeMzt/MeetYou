import asyncio
import tempfile
import unittest
from pathlib import Path

from adapters.meetwechat_client import MeetWeChatEvent, MeetWeChatSendResult
from sensors.meetwechat_adapter import (
    MEETWECHAT_BASIC_TOOL_BUNDLE,
    MeetWeChatInputAdapter,
    MeetWeChatOutputService,
    MeetWeChatStateStore,
    split_text_naturally,
)


class _Config:
    def __init__(self, **values):
        defaults = {
            "gateway_host": "127.0.0.1",
            "gateway_port": 8000,
            "gateway_access_token": "",
            "meetwechat_max_text_chars": 1800,
            "meetwechat_proxy_policy": {
                "mode": "guarded_auto",
                "private_default": "auto",
                "group_default": "mention_only",
                "merge_window_seconds": 0,
                "reply_delay_seconds": 0,
                "fragment_pause_seconds": 0,
                "reply_timeout_seconds": 1,
            },
        }
        defaults.update(values)
        self.values = defaults

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeMeetWeChatClient:
    def __init__(self):
        self.sent = []
        self.acked = []
        self.closed = False

    async def init(self):
        return None

    async def close(self):
        self.closed = True

    async def ack_events(self, event_ids):
        self.acked.extend(event_ids)
        return {"ok": True, "acked": list(event_ids)}

    async def send_text(self, **kwargs):
        self.sent.append(dict(kwargs))
        return MeetWeChatSendResult(ok=True, status="sent")


class _FakeGatewayClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.event_handler = kwargs.get("event_handler")
        self.thread_id = kwargs.get("thread_id") or "thread-1"
        self.session_id = "session-1"
        self.messages = []
        self.confirm_responses = []
        self.human_input_responses = []
        self.commands = []
        self.reply_payload = kwargs.get("reply_payload") or {
            "schema": "meetyou.client.ws.v1",
            "kind": "event",
            "event": {
                "type": "message.completed",
                "stream_id": "stream-1",
                "message": {"content": "assistant reply"},
            },
        }

    async def start(self):
        return None

    async def send_message(self, content, **kwargs):
        self.messages.append({"content": content, **kwargs})
        if self.event_handler and self.reply_payload is not None:
            await self.event_handler(self.reply_payload)
        return {"ok": True}

    async def submit_confirm_response(self, **kwargs):
        self.confirm_responses.append(kwargs)
        return {"ok": True}

    async def submit_human_input_response(self, **kwargs):
        self.human_input_responses.append(kwargs)
        return {"ok": True}

    async def send_command(self, action, **payload):
        self.commands.append({"action": action, **payload})

    async def close(self):
        return None


class MeetWeChatAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.state_path = str(Path(self._temp_dir.name) / "meetwechat_state.json")

    def tearDown(self):
        self._temp_dir.cleanup()

    def _event(self, **overrides):
        payload = {
            "event_id": "evt-1",
            "message_id": "msg-1",
            "chat_id": "chat-1",
            "chat_type": "private",
            "sender_id": "sender-1",
            "content_type": "text",
            "text": "hello",
        }
        payload.update(overrides)
        return MeetWeChatEvent.from_payload(payload)

    def _build_adapter(self, *, config=None, meetwechat_client=None, reply_payload=None, gateway_clients=None):
        config = config or _Config(meetwechat_state_file=self.state_path)
        state = MeetWeChatStateStore(self.state_path)
        meetwechat_client = meetwechat_client or _FakeMeetWeChatClient()
        output = MeetWeChatOutputService(
            config=config,
            client=meetwechat_client,
            state_store=state,
        )
        gateway_clients = gateway_clients if gateway_clients is not None else []

        def factory(**kwargs):
            client = _FakeGatewayClient(**{**kwargs, "reply_payload": reply_payload})
            gateway_clients.append(client)
            return client

        adapter = MeetWeChatInputAdapter(
            None,
            None,
            config,
            client=meetwechat_client,
            state_store=state,
            output_adapter=output,
            gateway_client_factory=factory,
        )
        return adapter, output, meetwechat_client, gateway_clients, state

    async def test_state_store_persists_ack_and_thread_state(self):
        store = MeetWeChatStateStore(self.state_path)
        await store.mark_event_status("evt-1", "sent", chat_id="chat-1")
        await store.mark_ack_pending(["evt-1"])
        await store.set_thread_id("wechat:meetwechat:chat:chat-1", "thread-1")

        reloaded = MeetWeChatStateStore(self.state_path)

        self.assertEqual(reloaded.get_event_status("evt-1"), "sent")
        self.assertEqual(reloaded.list_ack_pending(), ["evt-1"])
        self.assertEqual(reloaded.get_thread_id("wechat:meetwechat:chat:chat-1"), "thread-1")

    async def test_state_store_debounces_and_flushes_state_writes(self):
        store = MeetWeChatStateStore(self.state_path, flush_interval_ms=10000)

        await store.mark_event_status("evt-1", "sent", chat_id="chat-1")
        self.assertFalse(Path(self.state_path).exists())

        await store.flush()
        reloaded = MeetWeChatStateStore(self.state_path)

        self.assertEqual(reloaded.get_event_status("evt-1"), "sent")

    async def test_private_text_bridges_to_core_sends_reply_and_acks(self):
        adapter, _, meetwechat_client, gateway_clients, state = self._build_adapter()

        await adapter.handle_events([self._event()])

        self.assertEqual(len(gateway_clients), 1)
        self.assertEqual(gateway_clients[0].messages[0]["content"], "hello")
        self.assertEqual(gateway_clients[0].messages[0]["metadata"]["transport"], "meetwechat")
        self.assertEqual(gateway_clients[0].messages[0]["metadata"]["tool_scope"], "basic")
        self.assertIn("search_web", gateway_clients[0].messages[0]["metadata"]["allowed_tool_bundle"])
        self.assertEqual(
            gateway_clients[0].messages[0]["metadata"]["allowed_tool_bundle"],
            MEETWECHAT_BASIC_TOOL_BUNDLE,
        )
        self.assertIn("emit_short_reply", gateway_clients[0].messages[0]["metadata"]["allowed_tool_bundle"])
        self.assertIn("send_endpoint_message", gateway_clients[0].messages[0]["metadata"]["allowed_tool_bundle"])
        self.assertEqual(meetwechat_client.sent[0]["chat_id"], "chat-1")
        self.assertEqual(meetwechat_client.sent[0]["text"], "assistant reply")
        self.assertEqual(meetwechat_client.sent[0]["idempotency_key"], "meetyou:evt-1:1")
        self.assertEqual(meetwechat_client.acked, ["evt-1"])
        self.assertEqual(state.get_event_status("evt-1"), "acked")

    async def test_outbound_send_is_queued_from_ws_callback(self):
        class _SlowSendClient(_FakeMeetWeChatClient):
            def __init__(self):
                super().__init__()
                self.send_started = asyncio.Event()
                self.release_send = asyncio.Event()

            async def send_text(self, **kwargs):
                self.send_started.set()
                await self.release_send.wait()
                return await super().send_text(**kwargs)

        meetwechat_client = _SlowSendClient()
        config = _Config(meetwechat_state_file=self.state_path)
        state = MeetWeChatStateStore(self.state_path)
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)
        future = output.begin_event(self._event(), allow_send=True)

        await output.send_client_event(
            "chat-1",
            {
                "schema": "meetyou.client.ws.v1",
                "kind": "event",
                "event": {
                    "type": "message.completed",
                    "stream_id": "stream-1",
                    "message": {"content": "assistant reply"},
                },
            },
        )

        await asyncio.wait_for(meetwechat_client.send_started.wait(), timeout=1)
        self.assertFalse(future.done())

        meetwechat_client.release_send.set()
        result = await asyncio.wait_for(future, timeout=1)

        self.assertTrue(result["ok"])
        self.assertEqual(meetwechat_client.sent[0]["text"], "assistant reply")
        await output.close()

    async def test_short_reply_created_event_sends_without_completing_pending_reply(self):
        meetwechat_client = _FakeMeetWeChatClient()
        config = _Config(
            meetwechat_state_file=self.state_path,
            meetwechat_outbound_min_interval_ms=1,
            meetwechat_proxy_policy={
                "mode": "guarded_auto",
                "private_default": "auto",
                "group_default": "mention_only",
                "merge_window_seconds": 0,
                "reply_delay_seconds": 0,
                "fragment_pause_seconds": 0,
                "reply_timeout_seconds": 1,
            },
        )
        state = MeetWeChatStateStore(self.state_path)
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)
        future = output.begin_event(self._event(), allow_send=True)

        await output.send_client_event(
            "chat-1",
            {
                "schema": "meetyou.client.ws.v1",
                "kind": "event",
                "event": {
                    "type": "message.created",
                    "message": {
                        "role": "assistant",
                        "channel": "short_reply",
                        "content": "I will check.",
                    },
                },
            },
        )

        for _ in range(20):
            if meetwechat_client.sent:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(meetwechat_client.sent[0]["text"], "I will check.")
        self.assertFalse(future.done())

        await output.send_client_event(
            "chat-1",
            {
                "schema": "meetyou.client.ws.v1",
                "kind": "event",
                "event": {
                    "type": "message.completed",
                    "stream_id": "stream-1",
                    "message": {"content": "assistant reply"},
                },
            },
        )

        result = await asyncio.wait_for(future, timeout=1)
        await asyncio.wait_for(output._outbound_queue.join(), timeout=1)  # noqa: SLF001

        self.assertTrue(result["ok"])
        self.assertEqual([item["text"] for item in meetwechat_client.sent], ["I will check.", "assistant reply"])
        self.assertEqual(
            [item["idempotency_key"] for item in meetwechat_client.sent],
            ["meetyou:evt-1:1", "meetyou:evt-1:2:1"],
        )
        await output.close()

    async def test_notice_created_event_sends_without_pending_reply(self):
        meetwechat_client = _FakeMeetWeChatClient()
        config = _Config(
            meetwechat_state_file=self.state_path,
            meetwechat_outbound_min_interval_ms=1,
        )
        state = MeetWeChatStateStore(self.state_path)
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)

        await output.send_client_event(
            "chat-1",
            {
                "schema": "meetyou.client.ws.v1",
                "kind": "event",
                "event": {
                    "type": "message.created",
                    "message": {
                        "role": "assistant",
                        "channel": "notice",
                        "content": "direct notice",
                    },
                },
            },
        )

        self.assertEqual(meetwechat_client.sent[0]["chat_id"], "chat-1")
        self.assertEqual(meetwechat_client.sent[0]["text"], "direct notice")
        self.assertTrue(meetwechat_client.sent[0]["idempotency_key"].startswith("meetyou:direct:"))
        await output.close()

    async def test_group_message_without_mention_is_acked_without_reply(self):
        adapter, _, meetwechat_client, gateway_clients, _ = self._build_adapter()
        event = self._event(chat_type="group", chat_id="group-1", is_group_mention=False)

        await adapter.handle_events([event])

        self.assertEqual(gateway_clients, [])
        self.assertEqual(meetwechat_client.sent, [])
        self.assertEqual(meetwechat_client.acked, ["evt-1"])

    async def test_group_mention_keeps_sender_alias_and_sends_group_flag(self):
        adapter, _, meetwechat_client, gateway_clients, _ = self._build_adapter()
        event = self._event(
            chat_type="group",
            chat_id="group-1",
            sender_id="sender-a",
            is_group_mention=True,
            text="@bot summarize",
        )

        await adapter.handle_events([event])

        message = gateway_clients[0].messages[0]
        self.assertIn("member#", message["content"])
        self.assertEqual(message["metadata"]["sender_id"], "sender-a")
        self.assertTrue(message["metadata"]["sender_alias"].startswith("member#"))
        self.assertTrue(meetwechat_client.sent[0]["is_group_mention"])

    async def test_group_sender_aliases_are_distinct(self):
        adapter, _, _, gateway_clients, _ = self._build_adapter()

        await adapter.handle_events(
            [
                self._event(
                    event_id="evt-a",
                    message_id="msg-a",
                    chat_type="group",
                    chat_id="group-1",
                    sender_id="sender-a",
                    is_group_mention=True,
                    text="@bot first",
                ),
                self._event(
                    event_id="evt-b",
                    message_id="msg-b",
                    chat_type="group",
                    chat_id="group-1",
                    sender_id="sender-b",
                    is_group_mention=True,
                    text="@bot second",
                ),
            ]
        )

        aliases = [message["metadata"]["sender_alias"] for message in gateway_clients[0].messages]
        self.assertEqual(len(set(aliases)), 2)

    async def test_inbound_workers_process_different_chats_concurrently(self):
        config = _Config(meetwechat_state_file=self.state_path, meetwechat_inbound_worker_count=2)
        state = MeetWeChatStateStore(self.state_path)
        meetwechat_client = _FakeMeetWeChatClient()
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)
        started_contents = []
        all_started = asyncio.Event()
        release = asyncio.Event()

        class _BlockingGatewayClient(_FakeGatewayClient):
            async def send_message(self, content, **kwargs):
                started_contents.append(content)
                if len(started_contents) >= 2:
                    all_started.set()
                await release.wait()
                return await super().send_message(content, **kwargs)

        def factory(**kwargs):
            return _BlockingGatewayClient(**kwargs)

        adapter = MeetWeChatInputAdapter(
            None,
            None,
            config,
            client=meetwechat_client,
            state_store=state,
            output_adapter=output,
            gateway_client_factory=factory,
        )

        task = asyncio.create_task(
            adapter.handle_events(
                [
                    self._event(event_id="evt-a", message_id="msg-a", chat_id="chat-a", text="first"),
                    self._event(event_id="evt-b", message_id="msg-b", chat_id="chat-b", text="second"),
                ]
            )
        )

        await asyncio.wait_for(all_started.wait(), timeout=1)
        release.set()
        await asyncio.wait_for(task, timeout=1)

        self.assertEqual(set(started_contents), {"first", "second"})

    async def test_confirm_response_is_bound_to_group_sender(self):
        confirm_payload = {
            "schema": "meetyou.client.ws.v1",
            "kind": "event",
            "event": {
                "type": "confirm.requested",
                "request_id": "confirm-1",
                "content": "Approve action?",
            },
        }
        adapter, _, meetwechat_client, gateway_clients, _ = self._build_adapter(reply_payload=confirm_payload)

        await adapter.handle_events(
            [
                self._event(
                    event_id="evt-start",
                    message_id="msg-start",
                    chat_type="group",
                    chat_id="group-1",
                    sender_id="sender-a",
                    is_group_mention=True,
                    text="@bot do it",
                )
            ]
        )
        self.assertEqual(len(meetwechat_client.sent), 1)

        await adapter.handle_events(
            [
                self._event(
                    event_id="evt-other",
                    message_id="msg-other",
                    chat_type="group",
                    chat_id="group-1",
                    sender_id="sender-b",
                    is_group_mention=False,
                    text="yes",
                )
            ]
        )
        self.assertEqual(len(gateway_clients[0].confirm_responses), 0)

        await adapter.handle_events(
            [
                self._event(
                    event_id="evt-confirm",
                    message_id="msg-confirm",
                    chat_type="group",
                    chat_id="group-1",
                    sender_id="sender-a",
                    is_group_mention=False,
                    text="yes",
                )
            ]
        )

        self.assertEqual(gateway_clients[0].confirm_responses, [{"request_id": "confirm-1", "accepted": True}])
        self.assertIn("evt-confirm", meetwechat_client.acked)

    async def test_human_input_response_is_bound_to_group_sender(self):
        human_input_payload = {
            "schema": "meetyou.client.ws.v1",
            "kind": "event",
            "event": {
                "type": "human_input.requested",
                "request_id": "input-1",
                "question": "Pick one",
                "options": ["alpha", "beta"],
            },
        }
        adapter, _, _, gateway_clients, _ = self._build_adapter(reply_payload=human_input_payload)

        await adapter.handle_events(
            [
                self._event(
                    event_id="evt-start",
                    message_id="msg-start",
                    chat_type="group",
                    chat_id="group-1",
                    sender_id="sender-a",
                    is_group_mention=True,
                    text="@bot choose",
                ),
                self._event(
                    event_id="evt-input",
                    message_id="msg-input",
                    chat_type="group",
                    chat_id="group-1",
                    sender_id="sender-a",
                    is_group_mention=False,
                    text="2",
                ),
            ]
        )

        self.assertEqual(
            gateway_clients[0].human_input_responses,
            [{"request_id": "input-1", "answer_text": "beta", "selected_option": "beta"}],
        )

    async def test_reply_sends_natural_chunks_with_stable_idempotency(self):
        config = _Config(
            meetwechat_state_file=self.state_path,
            meetwechat_max_text_chars=5,
        )
        adapter, _, meetwechat_client, _, _ = self._build_adapter(config=config)

        await adapter.handle_events([self._event(text="chunk")])

        self.assertEqual([item["text"] for item in meetwechat_client.sent], ["assis", "tant", "reply"])
        self.assertEqual(
            [item["idempotency_key"] for item in meetwechat_client.sent],
            ["meetyou:evt-1:1", "meetyou:evt-1:2", "meetyou:evt-1:3"],
        )

    async def test_ack_failure_leaves_pending_for_retry_without_duplicate_core_send(self):
        class _AckFailOnceClient(_FakeMeetWeChatClient):
            def __init__(self):
                super().__init__()
                self.fail_next_ack = True

            async def ack_events(self, event_ids):
                if self.fail_next_ack:
                    self.fail_next_ack = False
                    raise RuntimeError("ack failed")
                return await super().ack_events(event_ids)

        meetwechat_client = _AckFailOnceClient()
        adapter, _, _, gateway_clients, state = self._build_adapter(meetwechat_client=meetwechat_client)
        event = self._event()

        await adapter.handle_events([event])
        self.assertEqual(len(gateway_clients), 1)
        self.assertEqual(state.list_ack_pending(), ["evt-1"])

        await adapter.handle_events([event])

        self.assertEqual(len(gateway_clients[0].messages), 1)
        self.assertEqual(meetwechat_client.acked, ["evt-1"])

    def test_split_text_prefers_natural_boundaries(self):
        self.assertEqual(split_text_naturally("hello world again", limit=8), ["hello", "world", "again"])


if __name__ == "__main__":
    unittest.main()
