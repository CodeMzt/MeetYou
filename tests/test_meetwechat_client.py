import unittest

from adapters.meetwechat_client import (
    MeetWeChatClient,
    MeetWeChatEvent,
    MeetWeChatHTTPError,
)


class _FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload if payload is not None else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, *args, **kwargs):
        return self.payload

    async def text(self):
        return str(self.payload)


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.closed = False

    def request(self, method, url, *, params=None, json=None):
        self.requests.append({"method": method, "url": url, "params": params, "json": json})
        if not self.responses:
            raise AssertionError("no fake response queued")
        return self.responses.pop(0)

    async def close(self):
        self.closed = True


class MeetWeChatClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_uses_v1_endpoint(self):
        session = _FakeSession([_FakeResponse(payload={"ok": True})])
        client = MeetWeChatClient(base_url="http://example.test/", session=session)

        payload = await client.health()

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(session.requests[0]["method"], "GET")
        self.assertEqual(session.requests[0]["url"], "http://example.test/v1/health")

    async def test_list_chats_parses_items_response(self):
        session = _FakeSession(
            [
                _FakeResponse(
                    payload={
                        "items": [
                            {
                                "chat_id": "aw:chat-1",
                                "chat_type": "private",
                                "display_name": "masked in tests",
                            }
                        ]
                    }
                )
            ]
        )
        client = MeetWeChatClient(base_url="http://example.test", session=session)

        chats = await client.list_chats()

        self.assertEqual(chats[0]["chat_id"], "aw:chat-1")
        self.assertEqual(session.requests[0]["method"], "GET")
        self.assertEqual(session.requests[0]["url"], "http://example.test/v1/chats")

    async def test_get_events_parses_events_and_cursor(self):
        session = _FakeSession(
            [
                _FakeResponse(
                    payload={
                        "items": [
                            {
                                "event_id": "evt-1",
                                "message_id": "msg-1",
                                "chat_id": "chat-1",
                                "chat_type": "group",
                                "sender_id": "sender-1",
                                "sender_name": "hidden in tests",
                                "is_group_mention": True,
                                "content_type": "text",
                                "text": "hello",
                            }
                        ],
                        "next_cursor": "cursor-2",
                    }
                )
            ]
        )
        client = MeetWeChatClient(base_url="http://example.test", session=session)

        events, cursor = await client.get_events(limit=20, cursor="cursor-1")

        self.assertEqual(cursor, "cursor-2")
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], MeetWeChatEvent)
        self.assertEqual(events[0].event_id, "evt-1")
        self.assertEqual(events[0].chat_type, "group")
        self.assertTrue(events[0].is_group_mention)
        self.assertEqual(session.requests[0]["params"], {"limit": 20, "cursor": "cursor-1"})

    async def test_ack_events_posts_event_ids(self):
        session = _FakeSession([_FakeResponse(payload={"ok": True, "acked": ["evt-1"]})])
        client = MeetWeChatClient(base_url="http://example.test", session=session)

        payload = await client.ack_events(["evt-1"])

        self.assertEqual(payload["acked"], ["evt-1"])
        self.assertEqual(session.requests[0]["method"], "POST")
        self.assertEqual(session.requests[0]["url"], "http://example.test/v1/events/ack")
        self.assertEqual(session.requests[0]["json"], {"event_ids": ["evt-1"]})

    async def test_send_text_posts_idempotency_and_group_flag(self):
        session = _FakeSession([_FakeResponse(payload={"ok": True, "status": "sent", "message_id": "msg-2"})])
        client = MeetWeChatClient(base_url="http://example.test", session=session)

        result = await client.send_text(
            chat_id="group-1",
            text="reply",
            idempotency_key="meetyou:evt-1:1",
            is_group_mention=True,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.message_id, "msg-2")
        self.assertEqual(
            session.requests[0]["json"],
            {
                "chat_id": "group-1",
                "text": "reply",
                "idempotency_key": "meetyou:evt-1:1",
                "is_group_mention": True,
            },
        )

    async def test_set_override_uses_chat_path(self):
        session = _FakeSession([_FakeResponse(payload={"ok": True})])
        client = MeetWeChatClient(base_url="http://example.test", session=session)

        await client.set_override("aw:chat/1", mode="manual_only", reason="handoff")

        self.assertEqual(session.requests[0]["method"], "PUT")
        self.assertEqual(session.requests[0]["url"], "http://example.test/v1/overrides/aw%3Achat%2F1")
        self.assertEqual(session.requests[0]["json"], {"mode": "manual_only", "reason": "handoff"})

    async def test_http_error_raises(self):
        session = _FakeSession([_FakeResponse(status=503, payload={"error": {"message": "down"}})])
        client = MeetWeChatClient(base_url="http://example.test", session=session)

        with self.assertRaises(MeetWeChatHTTPError) as captured:
            await client.health()

        self.assertEqual(captured.exception.status, 503)
        self.assertIn("down", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
