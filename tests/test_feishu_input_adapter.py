import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.event_bus import EventBus
from core.session_manager import SessionManager
from sensors.feishu_input_adapter import FeishuInputAdapter


class FakeConfig:
    def __init__(self, values):
        self._values = values

    def get(self, key):
        return self._values.get(key)


class FakeGatewayClient:
    def __init__(self):
        self.messages = []
        self.commands = []

    async def start(self):
        return None

    async def send_message(self, text: str, **kwargs):
        self.messages.append((text, kwargs))

    async def send_command(self, action: str, **kwargs):
        self.commands.append((action, kwargs))


class FeishuInputAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.tmpdir.name) / "feishu_chat_ids.json"
        self.event_bus = EventBus()
        self.session_manager = SessionManager()
        self.adapter = FeishuInputAdapter(
            self.event_bus,
            self.session_manager,
            FakeConfig(
                {
                    "feishu_chat_registry_path": str(self.registry_path),
                    "feishu_app_id": "",
                    "feishu_app_secret": "",
                }
            ),
        )
        self.fake_client = FakeGatewayClient()

        async def _fake_get_client(chat_id: str):
            return self.fake_client

        self.adapter._get_gateway_client = _fake_get_client  # type: ignore[assignment]

    async def asyncTearDown(self):
        self.tmpdir.cleanup()

    async def test_handle_event_sends_message_over_endpoint_chain(self):
        payload = {
            "event": {
                "message": {
                    "chat_id": "oc_test",
                    "content": json.dumps({"text": "hello from feishu"}, ensure_ascii=False),
                    "message_id": "msg-1",
                    "chat_type": "p2p",
                },
                "sender": {
                    "sender_id": {
                        "user_id": "user-1",
                    }
                },
            }
        }

        await self.adapter.handle_event(payload)

        self.assertEqual(self.fake_client.messages[0][0], "hello from feishu")
        self.assertEqual(self.fake_client.messages[0][1]["metadata"]["transport"], "feishu")
        self.assertEqual(self.fake_client.messages[0][1]["metadata"]["chat_id"], "oc_test")
        self.assertTrue(self.event_bus.inbound_queue.empty())
        self.assertTrue(self.registry_path.exists())

    async def test_gateway_client_uses_endpoint_owned_conversation_strategy(self):
        class _FakeGatewayConversationClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def start(self):
                return None

        adapter = FeishuInputAdapter(
            self.event_bus,
            self.session_manager,
            FakeConfig(
                {
                    "feishu_chat_registry_path": str(self.registry_path),
                    "feishu_app_id": "",
                    "feishu_app_secret": "",
                }
            ),
        )

        with patch("sensors.feishu_input_adapter.GatewayConversationClient", _FakeGatewayConversationClient):
            client = await adapter._get_gateway_client("oc_test")  # noqa: SLF001

        self.assertEqual(client.kwargs["conversation_key"], "feishu:chat:oc_test")
        self.assertEqual(client.kwargs["thread_strategy"], "per_conversation")
        self.assertEqual(client.kwargs["address_id"], "addr.feishu.direct.oc_test")

    async def test_ignores_self_message_from_bot_sender(self):
        payload = {
            "event": {
                "message": {
                    "chat_id": "oc_test",
                    "content": json.dumps({"text": "looped reply"}, ensure_ascii=False),
                    "message_id": "msg-self",
                    "chat_type": "p2p",
                },
                "sender": {
                    "sender_type": "app",
                    "sender_id": {
                        "app_id": "self-app",
                    },
                },
            }
        }

        await self.adapter.handle_event(payload)

        self.assertTrue(self.event_bus.inbound_queue.empty())
        self.assertEqual(self.fake_client.messages, [])

    async def test_ignores_duplicate_message_id(self):
        payload = {
            "event": {
                "message": {
                    "chat_id": "oc_test",
                    "content": json.dumps({"text": "hello twice"}, ensure_ascii=False),
                    "message_id": "msg-dup",
                    "chat_type": "p2p",
                },
                "sender": {
                    "sender_id": {
                        "user_id": "user-1",
                    }
                },
            }
        }

        await self.adapter.handle_event(payload)
        await self.adapter.handle_event(payload)

        self.assertEqual(len(self.fake_client.messages), 1)
        self.assertEqual(self.fake_client.messages[0][0], "hello twice")
        self.assertTrue(self.event_bus.inbound_queue.empty())

    async def test_handle_event_uses_gateway_client_when_output_adapter_present(self):
        class _FakeOutput:
            def get_pending_confirm_request(self, chat_id: str):
                return None

            def resolve_human_input(self, chat_id: str, raw_text: str):
                return None

            async def send_runtime_event(self, chat_id: str, payload: dict):
                return None

        class _FakeGatewayClient:
            def __init__(self):
                self.messages = []
                self.commands = []

            async def start(self):
                return None

            async def send_message(self, text: str, **kwargs):
                self.messages.append((text, kwargs))

            async def send_command(self, action: str, **kwargs):
                self.commands.append((action, kwargs))

        fake_output = _FakeOutput()
        adapter = FeishuInputAdapter(
            self.event_bus,
            self.session_manager,
            FakeConfig(
                {
                    "feishu_chat_registry_path": str(self.registry_path),
                    "feishu_app_id": "",
                    "feishu_app_secret": "",
                }
            ),
            output_adapter=fake_output,
        )
        fake_client = _FakeGatewayClient()

        async def _fake_get_client(chat_id: str):
            return fake_client

        adapter._get_gateway_client = _fake_get_client  # type: ignore[assignment]

        payload = {
            "event": {
                "message": {
                    "chat_id": "oc_test",
                    "content": json.dumps({"text": "hello from feishu"}, ensure_ascii=False),
                    "message_id": "msg-bridge-1",
                    "chat_type": "p2p",
                },
                "sender": {
                    "sender_id": {
                        "user_id": "user-1",
                    }
                },
            }
        }

        await adapter.handle_event(payload)

        self.assertEqual(fake_client.messages[0][0], "hello from feishu")
        self.assertEqual(fake_client.messages[0][1]["metadata"]["chat_id"], "oc_test")
        self.assertEqual(fake_client.messages[0][1]["metadata"]["transport"], "feishu")
        self.assertEqual(fake_client.messages[0][1]["metadata"]["response_transport"], "non_streaming_external_client")
        self.assertFalse(fake_client.messages[0][1]["metadata"]["supports_streaming_reply"])
        self.assertEqual(fake_client.messages[0][1]["metadata"]["progress_notice_policy"], "prefer_before_nontrivial_final")
        self.assertEqual(fake_client.messages[0][1]["metadata"]["tool_scope"], "basic")
        self.assertIn("emit_progress_notice", fake_client.messages[0][1]["metadata"]["allowed_tool_bundle"])
        self.assertNotIn("send_endpoint_message", fake_client.messages[0][1]["metadata"]["allowed_tool_bundle"])
        self.assertIsNone(fake_client.messages[0][1]["preferred_mode"])
        self.assertTrue(self.event_bus.inbound_queue.empty())

    async def test_handle_event_prefers_danxi_mode_for_danxi_keywords(self):
        class _FakeOutput:
            def get_pending_confirm_request(self, chat_id: str):
                return None

            def resolve_human_input(self, chat_id: str, raw_text: str):
                return None

            async def send_runtime_event(self, chat_id: str, payload: dict):
                return None

        class _FakeGatewayClient:
            def __init__(self):
                self.messages = []

            async def start(self):
                return None

            async def send_message(self, text: str, **kwargs):
                self.messages.append((text, kwargs))

        adapter = FeishuInputAdapter(
            self.event_bus,
            self.session_manager,
            FakeConfig(
                {
                    "feishu_chat_registry_path": str(self.registry_path),
                    "feishu_app_id": "",
                    "feishu_app_secret": "",
                }
            ),
            output_adapter=_FakeOutput(),
        )
        fake_client = _FakeGatewayClient()

        async def _fake_get_client(chat_id: str):
            return fake_client

        adapter._get_gateway_client = _fake_get_client  # type: ignore[assignment]

        payload = {
            "event": {
                "message": {
                    "chat_id": "oc_test",
                    "content": json.dumps({"text": "请帮我看一下旦夕论坛这个帖子"}, ensure_ascii=False),
                    "message_id": "msg-danxi-1",
                    "chat_type": "p2p",
                },
                "sender": {
                    "sender_id": {
                        "user_id": "user-1",
                    }
                },
            }
        }

        await adapter.handle_event(payload)

        self.assertEqual(fake_client.messages[0][1]["preferred_mode"], "danxi")

    async def test_handle_event_sends_confirm_over_gateway_client(self):
        class _FakeOutput:
            def get_pending_confirm_request(self, chat_id: str):
                return "req-1"

            def resolve_human_input(self, chat_id: str, raw_text: str):
                return None

            async def send_runtime_event(self, chat_id: str, payload: dict):
                return None

        class _FakeGatewayClient:
            def __init__(self):
                self.commands = []
                self.confirm_calls = []

            async def start(self):
                return None

            async def send_message(self, text: str, **kwargs):
                raise AssertionError("send_message should not be called")

            async def submit_confirm_response(self, *, request_id: str, accepted: bool, reason: str = ""):
                self.confirm_calls.append({"request_id": request_id, "accepted": accepted, "reason": reason})
                return {"request_id": request_id, "accepted": accepted}

            async def send_command(self, action: str, **kwargs):
                self.commands.append((action, kwargs))

        adapter = FeishuInputAdapter(
            self.event_bus,
            self.session_manager,
            FakeConfig(
                {
                    "feishu_chat_registry_path": str(self.registry_path),
                    "feishu_app_id": "",
                    "feishu_app_secret": "",
                }
            ),
            output_adapter=_FakeOutput(),
        )
        fake_client = _FakeGatewayClient()

        async def _fake_get_client(chat_id: str):
            return fake_client

        adapter._get_gateway_client = _fake_get_client  # type: ignore[assignment]

        payload = {
            "event": {
                "message": {
                    "chat_id": "oc_test",
                    "content": json.dumps({"text": "确认"}, ensure_ascii=False),
                    "message_id": "msg-confirm-1",
                    "chat_type": "p2p",
                },
                "sender": {
                    "sender_id": {
                        "user_id": "user-1",
                    }
                },
            }
        }

        await adapter.handle_event(payload)

        self.assertEqual(fake_client.confirm_calls, [{"request_id": "req-1", "accepted": True, "reason": ""}])
        self.assertEqual(fake_client.commands, [])

    async def test_handle_event_sends_human_input_over_gateway_client(self):
        class _FakeOutput:
            def get_pending_confirm_request(self, chat_id: str):
                return None

            def resolve_human_input(self, chat_id: str, raw_text: str):
                return {
                    "request_id": "req-human-1",
                    "answer_text": "B",
                    "selected_option": "B",
                }

            async def send_runtime_event(self, chat_id: str, payload: dict):
                return None

        class _FakeGatewayClient:
            def __init__(self):
                self.commands = []
                self.input_calls = []

            async def start(self):
                return None

            async def send_message(self, text: str, **kwargs):
                raise AssertionError("send_message should not be called")

            async def submit_human_input_response(self, *, request_id: str, answer_text: str, selected_option: str | None = None):
                self.input_calls.append(
                    {"request_id": request_id, "answer_text": answer_text, "selected_option": selected_option}
                )
                return {"request_id": request_id, "answer_text": answer_text, "selected_option": selected_option}

            async def send_command(self, action: str, **kwargs):
                self.commands.append((action, kwargs))

        adapter = FeishuInputAdapter(
            self.event_bus,
            self.session_manager,
            FakeConfig(
                {
                    "feishu_chat_registry_path": str(self.registry_path),
                    "feishu_app_id": "",
                    "feishu_app_secret": "",
                }
            ),
            output_adapter=_FakeOutput(),
        )
        fake_client = _FakeGatewayClient()

        async def _fake_get_client(chat_id: str):
            return fake_client

        adapter._get_gateway_client = _fake_get_client  # type: ignore[assignment]

        payload = {
            "event": {
                "message": {
                    "chat_id": "oc_test",
                    "content": json.dumps({"text": "2"}, ensure_ascii=False),
                    "message_id": "msg-human-1",
                    "chat_type": "p2p",
                },
                "sender": {
                    "sender_id": {
                        "user_id": "user-1",
                    }
                },
            }
        }

        await adapter.handle_event(payload)

        self.assertEqual(
            fake_client.input_calls,
            [{"request_id": "req-human-1", "answer_text": "B", "selected_option": "B"}],
        )
        self.assertEqual(fake_client.commands, [])
        self.assertTrue(self.event_bus.inbound_queue.empty())

    async def test_handle_event_falls_back_to_gateway_command_when_confirm_resource_fails(self):
        class _FakeOutput:
            def get_pending_confirm_request(self, chat_id: str):
                return "req-confirm-2"

            def resolve_human_input(self, chat_id: str, raw_text: str):
                return None

            async def send_runtime_event(self, chat_id: str, payload: dict):
                return None

        class _FakeGatewayClient:
            def __init__(self):
                self.commands = []

            async def start(self):
                return None

            async def send_message(self, text: str, **kwargs):
                raise AssertionError("send_message should not be called")

            async def submit_confirm_response(self, *, request_id: str, accepted: bool, reason: str = ""):
                raise RuntimeError("resource endpoint unavailable")

            async def send_command(self, action: str, **kwargs):
                self.commands.append((action, kwargs))

        adapter = FeishuInputAdapter(
            self.event_bus,
            self.session_manager,
            FakeConfig(
                {
                    "feishu_chat_registry_path": str(self.registry_path),
                    "feishu_app_id": "",
                    "feishu_app_secret": "",
                }
            ),
            output_adapter=_FakeOutput(),
        )
        fake_client = _FakeGatewayClient()

        async def _fake_get_client(chat_id: str):
            return fake_client

        adapter._get_gateway_client = _fake_get_client  # type: ignore[assignment]

        payload = {
            "event": {
                "message": {
                    "chat_id": "oc_test",
                    "content": json.dumps({"text": "确认"}, ensure_ascii=False),
                    "message_id": "msg-confirm-2",
                    "chat_type": "p2p",
                },
                "sender": {
                    "sender_id": {
                        "user_id": "user-1",
                    }
                },
            }
        }

        await adapter.handle_event(payload)

        self.assertEqual(fake_client.commands[0][0], "confirm_response")
        self.assertTrue(fake_client.commands[0][1]["accepted"])


if __name__ == "__main__":
    unittest.main()

