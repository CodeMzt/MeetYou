import json
import tempfile
import unittest
from pathlib import Path

from core.event_bus import EventBus
from core.session_manager import SessionManager
from sensors.feishu_input_adapter import FeishuInputAdapter


class FakeConfig:
    def __init__(self, values):
        self._values = values

    def get(self, key):
        return self._values.get(key)


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

    async def asyncTearDown(self):
        self.tmpdir.cleanup()

    async def test_handle_event_enqueues_message(self):
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

        event = self.event_bus.inbound_queue.get_nowait()
        self.assertEqual(event.session_id, "feishu:chat:oc_test")
        self.assertEqual(event.content, "hello from feishu")
        self.assertEqual(event.source.kind, "feishu")
        self.assertEqual(event.source.id, "oc_test")
        self.assertEqual(event.target.kind, "current_session")
        self.assertTrue(self.registry_path.exists())

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

        event = self.event_bus.inbound_queue.get_nowait()
        self.assertEqual(event.content, "hello twice")
        self.assertTrue(self.event_bus.inbound_queue.empty())


if __name__ == "__main__":
    unittest.main()
