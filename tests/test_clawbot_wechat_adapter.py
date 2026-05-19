import tempfile
import unittest

from adapters.clawbot_client import ClawBotAccount, ClawBotMessage
from sensors.clawbot_wechat_adapter import (
    ClawBotWechatOutputService,
    ClawBotWechatStateStore,
    conversation_ref,
    event_from_message,
)


class _Config:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeClient:
    def __init__(self):
        self.sent = []

    async def send_text(self, account, *, to_user_id, context_token, text, timeout_ms=None):
        self.sent.append(
            {
                "account_id": account.account_id,
                "to_user_id": to_user_id,
                "context_token": context_token,
                "text": text,
                "timeout_ms": timeout_ms,
            }
        )
        return {"ok": True}


class ClawBotWechatAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_event_from_message_accepts_direct_completed_user_text(self):
        account = ClawBotAccount(account_id="acc-1", token="token-1", user_id="bot-user")
        message = ClawBotMessage.from_payload(
            {
                "seq": 7,
                "message_id": "msg-1",
                "from_user_id": "peer-1",
                "to_user_id": "bot-user",
                "message_type": 1,
                "message_state": 2,
                "context_token": "ctx-1",
                "item_list": [{"type": 1, "text_item": {"text": "hello"}, "is_completed": True}],
            }
        )

        event = event_from_message(account, message)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.account_id, "acc-1")
        self.assertEqual(event.peer_id, "peer-1")
        self.assertEqual(event.text, "hello")
        self.assertEqual(event.context_token, "ctx-1")
        self.assertEqual(event.conversation_ref, "acc-1::peer-1")

    def test_event_from_message_rejects_group_or_bot_messages(self):
        account = ClawBotAccount(account_id="acc-1", token="token-1", user_id="bot-user")
        group_message = ClawBotMessage.from_payload(
            {
                "message_id": "msg-1",
                "from_user_id": "peer-1",
                "to_user_id": "bot-user",
                "group_id": "group-1",
                "message_type": 1,
                "message_state": 2,
                "context_token": "ctx-1",
                "item_list": [{"type": 1, "text_item": {"text": "hello"}, "is_completed": True}],
            }
        )
        bot_message = ClawBotMessage.from_payload(
            {
                "message_id": "msg-2",
                "from_user_id": "bot-user",
                "to_user_id": "peer-1",
                "message_type": 2,
                "message_state": 2,
                "context_token": "ctx-1",
                "item_list": [{"type": 1, "text_item": {"text": "hello"}, "is_completed": True}],
            }
        )

        self.assertIsNone(event_from_message(account, group_message))
        self.assertIsNone(event_from_message(account, bot_message))

    async def test_output_sends_delivery_message_with_stored_context_token(self):
        account = ClawBotAccount(account_id="acc-1", token="token-1", user_id="bot-user")
        message = ClawBotMessage.from_payload(
            {
                "seq": 7,
                "message_id": "msg-1",
                "from_user_id": "peer-1",
                "to_user_id": "bot-user",
                "message_type": 1,
                "message_state": 2,
                "context_token": "ctx-1",
                "item_list": [{"type": 1, "text_item": {"text": "hello"}, "is_completed": True}],
            }
        )
        event = event_from_message(account, message)
        assert event is not None
        fake_client = _FakeClient()
        delivery_results = []

        async def delivery_sender(**kwargs):
            delivery_results.append(kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            state = ClawBotWechatStateStore(f"{temp_dir}/state.json")
            await state.remember_context(event)
            output = ClawBotWechatOutputService(
                config=_Config({"clawbot_wechat_send_timeout_ms": 15000, "clawbot_wechat_outbound_min_interval_ms": 1}),
                client=fake_client,
                state_store=state,
                account_resolver=lambda account_id: account if account_id == "acc-1" else None,
                delivery_result_sender=delivery_sender,
                sleeper=lambda seconds: None,
            )

            await output.send_runtime_event(
                conversation_ref("acc-1", "peer-1"),
                {
                    "schema": "meetyou.endpoint.ws.v4",
                    "type": "delivery.message",
                    "payload": {
                        "delivery_id": "delivery-1",
                        "role": "assistant",
                        "content": "**hi**",
                        "message_id": "core-msg-1",
                    },
                },
            )

        self.assertEqual(fake_client.sent[0]["account_id"], "acc-1")
        self.assertEqual(fake_client.sent[0]["to_user_id"], "peer-1")
        self.assertEqual(fake_client.sent[0]["context_token"], "ctx-1")
        self.assertEqual(fake_client.sent[0]["text"], "hi")
        self.assertEqual(delivery_results[0]["delivery_id"], "delivery-1")
        self.assertEqual(delivery_results[0]["status"], "sent")


if __name__ == "__main__":
    unittest.main()
