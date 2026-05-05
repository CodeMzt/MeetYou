import asyncio
import json
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


def _run_event(event: dict) -> dict:
    return {
        "schema": "meetyou.endpoint.ws.v4",
        "type": "delivery.run_event",
        "payload": {
            "type": event.get("type"),
            "stream_id": event.get("stream_id", ""),
            "turn_id": event.get("turn_id", ""),
            "payload": dict(event),
        },
    }


def _notice(content: str) -> dict:
    return {
        "schema": "meetyou.endpoint.ws.v4",
        "type": "delivery.notice",
        "payload": {"content": content},
    }


def _message(content: str, *, message_id: str = "msg-1") -> dict:
    return {
        "schema": "meetyou.endpoint.ws.v4",
        "type": "delivery.message",
        "payload": {
            "message_id": message_id,
            "role": "assistant",
            "content": content,
        },
    }


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


class _FakeEndpointConnection:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.event_handler = kwargs.get("event_handler")
        self.thread_id = kwargs.get("thread_id") or "thread-1"
        self.session_id = "session-1"
        self.messages = []
        self.confirm_responses = []
        self.human_input_responses = []
        self.commands = []
        self.message_response = kwargs.get("message_response") or {"ok": True, "message_id": "core-msg-1"}
        self.thread_after_send = kwargs.get("thread_after_send") or ""
        self.reply_payload = kwargs.get("reply_payload") or _run_event(
            {
                "type": "message.completed",
                "stream_id": "stream-1",
                "message": {"content": "assistant reply"},
            }
        )

    async def start(self):
        return None

    async def send_message(self, content, **kwargs):
        self.messages.append({"content": content, **kwargs})
        if self.event_handler and self.reply_payload is not None:
            await self.event_handler(self.reply_payload)
        if self.thread_after_send:
            self.thread_id = self.thread_after_send
        return dict(self.message_response)

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

    def _build_adapter(
        self,
        *,
        config=None,
        meetwechat_client=None,
        reply_payload=None,
        endpoint_connections=None,
        message_response=None,
        thread_after_send=None,
    ):
        config = config or _Config(meetwechat_state_file=self.state_path)
        state = MeetWeChatStateStore(self.state_path)
        meetwechat_client = meetwechat_client or _FakeMeetWeChatClient()
        output = MeetWeChatOutputService(
            config=config,
            client=meetwechat_client,
            state_store=state,
        )
        endpoint_connections = endpoint_connections if endpoint_connections is not None else []

        def factory(**kwargs):
            client = _FakeEndpointConnection(
                **{
                    **kwargs,
                    "reply_payload": reply_payload,
                    "message_response": message_response,
                    "thread_after_send": thread_after_send,
                }
            )
            endpoint_connections.append(client)
            return client

        adapter = MeetWeChatInputAdapter(
            None,
            None,
            config,
            client=meetwechat_client,
            state_store=state,
            output_adapter=output,
            endpoint_connection_factory=factory,
        )
        return adapter, output, meetwechat_client, endpoint_connections, state

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
        adapter, _, meetwechat_client, endpoint_connections, state = self._build_adapter()

        await adapter.handle_events([self._event()])

        self.assertEqual(len(endpoint_connections), 1)
        self.assertEqual(endpoint_connections[0].kwargs["conversation_key"], "wechat:meetwechat:chat:chat-1")
        self.assertEqual(endpoint_connections[0].kwargs["thread_strategy"], "per_conversation")
        self.assertEqual(endpoint_connections[0].kwargs["address_id"], "addr.wechat.direct.chat-1")
        self.assertEqual(endpoint_connections[0].messages[0]["content"], "hello")
        self.assertEqual(endpoint_connections[0].messages[0]["metadata"]["transport"], "meetwechat")
        self.assertEqual(endpoint_connections[0].messages[0]["metadata"]["response_transport"], "non_streaming_endpoint_provider")
        self.assertFalse(endpoint_connections[0].messages[0]["metadata"]["supports_streaming_reply"])
        self.assertEqual(endpoint_connections[0].messages[0]["metadata"]["progress_notice_policy"], "prefer_before_nontrivial_final")
        self.assertEqual(endpoint_connections[0].messages[0]["metadata"]["tool_scope"], "basic")
        self.assertIn("search_web", endpoint_connections[0].messages[0]["metadata"]["allowed_tool_bundle"])
        self.assertIn("danxi_list_posts", endpoint_connections[0].messages[0]["metadata"]["allowed_tool_bundle"])
        self.assertIn("manage_schedule", endpoint_connections[0].messages[0]["metadata"]["allowed_tool_bundle"])
        self.assertIn("manage_tasks", endpoint_connections[0].messages[0]["metadata"]["allowed_tool_bundle"])
        self.assertEqual(
            endpoint_connections[0].messages[0]["metadata"]["allowed_tool_bundle"],
            MEETWECHAT_BASIC_TOOL_BUNDLE,
        )
        self.assertIn("emit_progress_notice", endpoint_connections[0].messages[0]["metadata"]["allowed_tool_bundle"])
        self.assertNotIn("send_endpoint_message", endpoint_connections[0].messages[0]["metadata"]["allowed_tool_bundle"])
        self.assertEqual(meetwechat_client.sent[0]["chat_id"], "chat-1")
        self.assertEqual(meetwechat_client.sent[0]["text"], "assistant reply")
        self.assertEqual(meetwechat_client.sent[0]["idempotency_key"], "meetyou:evt-1:1")
        self.assertEqual(meetwechat_client.acked, ["evt-1"])
        self.assertEqual(state.get_event_status("evt-1"), "sent")
        with open(self.state_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertTrue(payload["events"]["evt-1"]["acked"])

    async def test_provider_endpoint_connection_registers_without_thread_binding(self):
        adapter, _, _, endpoint_connections, _ = self._build_adapter()

        await adapter._get_provider_endpoint_connection()  # noqa: SLF001

        self.assertEqual(len(endpoint_connections), 1)
        self.assertEqual(endpoint_connections[0].kwargs["endpoint_id"], "wechat.provider.ui")
        self.assertFalse(endpoint_connections[0].kwargs["bind_thread"])

    async def test_updates_cached_thread_after_endpoint_rebind(self):
        adapter, _, _, _, state = self._build_adapter(thread_after_send="thread-rebound")

        await adapter.handle_events([self._event()])

        self.assertEqual(state.get_thread_id("wechat:meetwechat:chat:chat-1"), "thread-rebound")

    async def test_guarded_auto_event_still_sends_after_bridge(self):
        adapter, _, meetwechat_client, endpoint_connections, state = self._build_adapter()
        event = self._event(mode="guarded_auto")

        await adapter.handle_events([event])

        self.assertEqual(len(endpoint_connections), 1)
        self.assertEqual(endpoint_connections[0].messages[0]["content"], "hello")
        self.assertEqual(meetwechat_client.sent[0]["chat_id"], "chat-1")
        self.assertEqual(meetwechat_client.sent[0]["text"], "assistant reply")
        self.assertEqual(state.get_event_status("evt-1"), "sent")

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

        await output.send_runtime_event(
            "chat-1",
            _run_event({"type": "message.completed", "stream_id": "stream-1", "message": {"content": "assistant reply"}}),
        )

        await asyncio.wait_for(meetwechat_client.send_started.wait(), timeout=1)
        self.assertFalse(future.done())

        meetwechat_client.release_send.set()
        result = await asyncio.wait_for(future, timeout=1)

        self.assertTrue(result["ok"])
        self.assertEqual(meetwechat_client.sent[0]["text"], "assistant reply")
        await output.close()

    async def test_non_streaming_external_does_not_duplicate_delta_and_completed_answer(self):
        meetwechat_client = _FakeMeetWeChatClient()
        config = _Config(meetwechat_state_file=self.state_path)
        state = MeetWeChatStateStore(self.state_path)
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)
        future = output.begin_event(self._event(), allow_send=True)

        await output.send_runtime_event(
            "chat-1",
            _run_event({"type": "message.delta", "stream_id": "stream-1", "channel": "answer", "delta": "你好"}),
        )
        await output.send_runtime_event(
            "chat-1",
            _run_event({"type": "message.completed", "stream_id": "stream-1", "message": {"content": "你好"}}),
        )

        result = await asyncio.wait_for(future, timeout=1)
        await asyncio.wait_for(output._outbound_queue.join(), timeout=1)  # noqa: SLF001

        self.assertTrue(result["ok"])
        self.assertEqual([item["text"] for item in meetwechat_client.sent], ["你好"])
        await output.close()

    async def test_delivery_message_is_final_reply_fallback(self):
        meetwechat_client = _FakeMeetWeChatClient()
        config = _Config(meetwechat_state_file=self.state_path)
        state = MeetWeChatStateStore(self.state_path)
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)
        future = output.begin_event(self._event(), allow_send=True)

        await output.send_runtime_event("chat-1", _message("OK", message_id="msg-final-1"))

        result = await asyncio.wait_for(future, timeout=1)
        await asyncio.wait_for(output._outbound_queue.join(), timeout=1)  # noqa: SLF001

        self.assertTrue(result["ok"])
        self.assertEqual([item["text"] for item in meetwechat_client.sent], ["OK"])
        await output.close()

    async def test_delivery_message_strips_markdown_for_wechat_text(self):
        meetwechat_client = _FakeMeetWeChatClient()
        config = _Config(meetwechat_state_file=self.state_path)
        state = MeetWeChatStateStore(self.state_path)
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)
        future = output.begin_event(self._event(), allow_send=True)

        await output.send_runtime_event(
            "chat-1",
            _message("**bold** and [Docs](https://example.test)", message_id="msg-markdown"),
        )

        result = await asyncio.wait_for(future, timeout=1)
        await asyncio.wait_for(output._outbound_queue.join(), timeout=1)  # noqa: SLF001

        self.assertTrue(result["ok"])
        self.assertEqual([item["text"] for item in meetwechat_client.sent], ["bold and Docs (https://example.test)"])
        await output.close()

    async def test_chat_scoped_connection_handles_matching_address_targeted_delivery(self):
        meetwechat_client = _FakeMeetWeChatClient()
        config = _Config(meetwechat_state_file=self.state_path)
        state = MeetWeChatStateStore(self.state_path)
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)
        future = output.begin_event(self._event(), allow_send=True)
        payload = _message("OK", message_id="msg-final-address")
        payload["payload"]["target_external_ref"] = "chat-1"

        await output.send_runtime_event("chat-1", payload)
        result = await asyncio.wait_for(future, timeout=1)
        await asyncio.wait_for(output._outbound_queue.join(), timeout=1)  # noqa: SLF001

        self.assertTrue(result["ok"])
        self.assertEqual([item["text"] for item in meetwechat_client.sent], ["OK"])
        await output.close()

    async def test_chat_scoped_connection_ignores_other_address_targeted_delivery(self):
        meetwechat_client = _FakeMeetWeChatClient()
        config = _Config(meetwechat_state_file=self.state_path)
        state = MeetWeChatStateStore(self.state_path)
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)
        payload = _message("OK", message_id="msg-final-address")
        payload["payload"]["target_external_ref"] = "chat-2"

        await output.send_runtime_event("chat-1", payload)

        self.assertEqual(meetwechat_client.sent, [])
        await output.close()

    async def test_provider_connection_handles_address_targeted_delivery(self):
        meetwechat_client = _FakeMeetWeChatClient()
        config = _Config(meetwechat_state_file=self.state_path)
        state = MeetWeChatStateStore(self.state_path)
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)
        payload = _message("OK", message_id="msg-final-address")
        payload["payload"]["target_external_ref"] = "chat-1"

        await output.send_runtime_event("", payload)

        self.assertEqual([item["text"] for item in meetwechat_client.sent], ["OK"])
        await output.close()

    async def test_run_event_and_delivery_message_do_not_duplicate_final_reply(self):
        meetwechat_client = _FakeMeetWeChatClient()
        config = _Config(meetwechat_state_file=self.state_path)
        state = MeetWeChatStateStore(self.state_path)
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)
        future = output.begin_event(self._event(), allow_send=True)

        await output.send_runtime_event(
            "chat-1",
            _run_event(
                {
                    "type": "message.completed",
                    "stream_id": "stream-1",
                    "message": {"message_id": "msg-final-1", "content": "OK"},
                }
            ),
        )
        await output.send_runtime_event("chat-1", _message("OK", message_id="msg-final-1"))

        result = await asyncio.wait_for(future, timeout=1)
        await asyncio.wait_for(output._outbound_queue.join(), timeout=1)  # noqa: SLF001

        self.assertTrue(result["ok"])
        self.assertEqual([item["text"] for item in meetwechat_client.sent], ["OK"])
        await output.close()

    async def test_progress_notice_run_event_sends_without_completing_pending_reply(self):
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

        await output.send_runtime_event(
            "chat-1",
            _run_event({"type": "assistant.progress_notice", "content": "I will check.", "text": "I will check."}),
        )

        for _ in range(20):
            if meetwechat_client.sent:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(meetwechat_client.sent[0]["text"], "I will check.")
        self.assertFalse(future.done())

        await output.send_runtime_event(
            "chat-1",
            _run_event({"type": "message.completed", "stream_id": "stream-1", "message": {"content": "assistant reply"}}),
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

    async def test_delivery_notice_sends_without_pending_reply(self):
        meetwechat_client = _FakeMeetWeChatClient()
        config = _Config(
            meetwechat_state_file=self.state_path,
            meetwechat_outbound_min_interval_ms=1,
        )
        state = MeetWeChatStateStore(self.state_path)
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)

        await output.send_runtime_event(
            "chat-1",
            _notice("direct notice"),
        )

        self.assertEqual(meetwechat_client.sent[0]["chat_id"], "chat-1")
        self.assertEqual(meetwechat_client.sent[0]["text"], "direct notice")
        self.assertTrue(meetwechat_client.sent[0]["idempotency_key"].startswith("meetyou:direct:"))
        await output.close()

    async def test_group_message_without_mention_is_acked_without_reply(self):
        adapter, _, meetwechat_client, endpoint_connections, _ = self._build_adapter()
        event = self._event(chat_type="group", chat_id="group-1", is_group_mention=False)

        await adapter.handle_events([event])

        self.assertEqual(endpoint_connections, [])
        self.assertEqual(meetwechat_client.sent, [])
        self.assertEqual(meetwechat_client.acked, ["evt-1"])

    async def test_group_mention_keeps_sender_alias_and_sends_group_flag(self):
        adapter, _, meetwechat_client, endpoint_connections, _ = self._build_adapter()
        event = self._event(
            chat_type="group",
            chat_id="group-1",
            sender_id="sender-a",
            is_group_mention=True,
            text="@bot summarize",
        )

        await adapter.handle_events([event])

        message = endpoint_connections[0].messages[0]
        self.assertIn("member#", message["content"])
        self.assertEqual(message["metadata"]["sender_id"], "sender-a")
        self.assertTrue(message["metadata"]["sender_alias"].startswith("member#"))
        self.assertTrue(meetwechat_client.sent[0]["is_group_mention"])

    async def test_group_sender_aliases_are_distinct(self):
        adapter, _, _, endpoint_connections, _ = self._build_adapter()

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

        aliases = [message["metadata"]["sender_alias"] for message in endpoint_connections[0].messages]
        self.assertEqual(len(set(aliases)), 2)

    async def test_inbound_workers_process_different_chats_concurrently(self):
        config = _Config(meetwechat_state_file=self.state_path, meetwechat_inbound_worker_count=2)
        state = MeetWeChatStateStore(self.state_path)
        meetwechat_client = _FakeMeetWeChatClient()
        output = MeetWeChatOutputService(config=config, client=meetwechat_client, state_store=state)
        started_contents = []
        all_started = asyncio.Event()
        release = asyncio.Event()

        class _BlockingEndpointConnection(_FakeEndpointConnection):
            async def send_message(self, content, **kwargs):
                started_contents.append(content)
                if len(started_contents) >= 2:
                    all_started.set()
                await release.wait()
                return await super().send_message(content, **kwargs)

        def factory(**kwargs):
            return _BlockingEndpointConnection(**kwargs)

        adapter = MeetWeChatInputAdapter(
            None,
            None,
            config,
            client=meetwechat_client,
            state_store=state,
            output_adapter=output,
            endpoint_connection_factory=factory,
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
        confirm_payload = _run_event(
            {
                "type": "confirm.requested",
                "request_id": "confirm-1",
                "content": "Approve action?",
            }
        )
        adapter, _, meetwechat_client, endpoint_connections, _ = self._build_adapter(reply_payload=confirm_payload)

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
        self.assertEqual(len(endpoint_connections[0].confirm_responses), 0)

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

        self.assertEqual(endpoint_connections[0].confirm_responses, [{"request_id": "confirm-1", "accepted": True}])
        self.assertIn("evt-confirm", meetwechat_client.acked)

    async def test_human_input_response_is_bound_to_group_sender(self):
        human_input_payload = _run_event(
            {
                "type": "human_input.requested",
                "request_id": "input-1",
                "question": "Pick one",
                "options": ["alpha", "beta"],
            }
        )
        adapter, _, _, endpoint_connections, _ = self._build_adapter(reply_payload=human_input_payload)

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
            endpoint_connections[0].human_input_responses,
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

    async def test_send_blocked_marks_terminal_blocked_and_acks(self):
        class _BlockedSendClient(_FakeMeetWeChatClient):
            async def send_text(self, **kwargs):
                self.sent.append(dict(kwargs))
                return MeetWeChatSendResult(
                    ok=False,
                    status="blocked",
                    detail="chat override active: manual_only",
                )

        meetwechat_client = _BlockedSendClient()
        adapter, output, _, endpoint_connections, state = self._build_adapter(meetwechat_client=meetwechat_client)

        await adapter.handle_events([self._event()])

        self.assertEqual(len(endpoint_connections[0].messages), 1)
        self.assertEqual(len(meetwechat_client.sent), 1)
        self.assertEqual(meetwechat_client.acked, ["evt-1"])
        self.assertEqual(state.get_event_status("evt-1"), "blocked")
        with open(self.state_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertIn("send blocked", payload["events"]["evt-1"]["reason"])
        self.assertTrue(payload["events"]["evt-1"]["acked"])
        await output.close()

    async def test_uncertain_send_failure_does_not_resubmit_core_message(self):
        class _UncertainSendClient(_FakeMeetWeChatClient):
            async def send_text(self, **kwargs):
                self.sent.append(dict(kwargs))
                return MeetWeChatSendResult(
                    ok=False,
                    status="failed",
                    detail="agent-wechat sidecar is unreachable",
                )

        meetwechat_client = _UncertainSendClient()
        config = _Config(
            meetwechat_state_file=self.state_path,
            meetwechat_proxy_policy={
                "mode": "guarded_auto",
                "private_default": "auto",
                "group_default": "mention_only",
                "merge_window_seconds": 0,
                "reply_delay_seconds": 0,
                "fragment_pause_seconds": 0,
                "reply_timeout_seconds": 5,
            },
        )
        adapter, output, _, endpoint_connections, state = self._build_adapter(
            config=config,
            meetwechat_client=meetwechat_client,
        )

        await adapter.handle_events([self._event()])

        self.assertEqual(len(endpoint_connections[0].messages), 1)
        self.assertEqual(len(meetwechat_client.sent), 3)
        self.assertEqual(
            {item["idempotency_key"] for item in meetwechat_client.sent},
            {"meetyou:evt-1:1"},
        )
        self.assertEqual(meetwechat_client.acked, ["evt-1"])
        self.assertEqual(state.get_event_status("evt-1"), "submitted")
        with open(self.state_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertIn("sidecar is unreachable", payload["events"]["evt-1"]["reason"])
        await output.close()

    async def test_reply_timeout_does_not_resubmit_core_message(self):
        config = _Config(
            meetwechat_state_file=self.state_path,
            meetwechat_proxy_policy={
                "mode": "guarded_auto",
                "private_default": "auto",
                "group_default": "mention_only",
                "merge_window_seconds": 0,
                "reply_delay_seconds": 0,
                "fragment_pause_seconds": 0,
                "reply_timeout_seconds": 0.01,
            },
        )
        adapter, output, meetwechat_client, endpoint_connections, state = self._build_adapter(
            config=config,
            reply_payload=_run_event({"type": "activity.status", "content": "thinking"}),
        )

        await adapter.handle_events([self._event()])

        self.assertEqual(len(endpoint_connections[0].messages), 1)
        self.assertEqual(meetwechat_client.sent, [])
        self.assertEqual(meetwechat_client.acked, ["evt-1"])
        self.assertEqual(state.get_event_status("evt-1"), "submitted")
        self.assertEqual(output._pending_replies, {})  # noqa: SLF001
        with open(self.state_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["events"]["evt-1"]["reason"], "reply:TimeoutError")
        await output.close()

    async def test_cursor_does_not_advance_for_failed_events(self):
        adapter, _, _, _, state = self._build_adapter()
        event = self._event()

        await state.mark_event_status("evt-1", "failed", chat_id="chat-1", reason="bridge:TimeoutError")
        self.assertFalse(adapter._events_are_complete_for_cursor_advance([event]))  # noqa: SLF001

        await state.mark_event_status("evt-1", "sent", chat_id="chat-1")
        self.assertTrue(adapter._events_are_complete_for_cursor_advance([event]))  # noqa: SLF001

        await state.mark_event_status("evt-1", "submitted", chat_id="chat-1")
        self.assertTrue(adapter._events_are_complete_for_cursor_advance([event]))  # noqa: SLF001

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
        adapter, _, _, endpoint_connections, state = self._build_adapter(meetwechat_client=meetwechat_client)
        event = self._event()

        await adapter.handle_events([event])
        self.assertEqual(len(endpoint_connections), 1)
        self.assertEqual(state.list_ack_pending(), ["evt-1"])

        await adapter.handle_events([event])

        self.assertEqual(len(endpoint_connections[0].messages), 1)
        self.assertEqual(meetwechat_client.acked, ["evt-1"])

    async def test_redelivered_event_with_new_event_id_uses_stable_identity(self):
        adapter, _, meetwechat_client, endpoint_connections, state = self._build_adapter()
        first = self._event(event_id="evt-1", message_id="msg-stable", dedup_key="mid:stable")
        redelivered = self._event(event_id="evt-2", message_id="msg-stable", dedup_key="mid:stable")

        await adapter.handle_events([first])
        await adapter.handle_events([redelivered])

        self.assertEqual(len(endpoint_connections[0].messages), 1)
        self.assertEqual(meetwechat_client.acked, ["evt-1", "evt-2"])
        self.assertEqual(state.get_event_status("evt-2"), "acked")

    async def test_runtime_idempotent_replay_is_acked_without_waiting_for_reply(self):
        adapter, output, meetwechat_client, endpoint_connections, state = self._build_adapter(
            reply_payload=_run_event({"type": "activity.status", "content": "already running"}),
            message_response={"ok": True, "message_id": "core-existing", "idempotent_replay": True},
        )

        await adapter.handle_events([self._event()])

        self.assertEqual(len(endpoint_connections[0].messages), 1)
        self.assertEqual(meetwechat_client.sent, [])
        self.assertEqual(meetwechat_client.acked, ["evt-1"])
        self.assertEqual(state.get_event_status("evt-1"), "submitted")
        self.assertEqual(output._pending_replies, {})  # noqa: SLF001

    def test_split_text_prefers_natural_boundaries(self):
        self.assertEqual(split_text_naturally("hello world again", limit=8), ["hello", "world", "again"])


if __name__ == "__main__":
    unittest.main()

