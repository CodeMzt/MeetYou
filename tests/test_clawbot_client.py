import unittest

from adapters.clawbot_client import ClawBotClient


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        del content_type
        return self._payload

    async def text(self):
        return str(self._payload)


class _FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        payload = self.payloads.pop(0)
        return _FakeResponse(payload)


class ClawBotClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_qr_login_uses_native_ilink_endpoints(self):
        session = _FakeSession(
            [
                {
                    "data": {
                        "qrcode": "qr-1",
                        "qrcode_img_content": "https://qr.example.test/1",
                    }
                },
                {
                    "data": {
                        "status": "confirmed",
                        "bot_token": "token-1",
                        "ilink_bot_id": "bot-1",
                        "ilink_user_id": "user-1",
                        "baseurl": "https://ilink-returned.example.test",
                    }
                },
            ]
        )
        client = ClawBotClient(base_url="https://ilink.example.test", route_tag="rt", session=session)

        qrcode = await client.get_bot_qrcode()
        status = await client.get_qrcode_status(qrcode.qrcode)

        self.assertEqual(qrcode.qrcode, "qr-1")
        self.assertEqual(qrcode.display_url, "https://qr.example.test/1")
        self.assertTrue(status.confirmed)
        self.assertEqual(status.bot_token, "token-1")
        self.assertEqual(status.ilink_bot_id, "bot-1")
        self.assertEqual(status.ilink_user_id, "user-1")
        self.assertEqual(status.base_url, "https://ilink-returned.example.test")
        self.assertEqual(session.requests[0]["method"], "GET")
        self.assertEqual(session.requests[0]["url"], "https://ilink.example.test/ilink/bot/get_bot_qrcode?bot_type=3")
        self.assertEqual(session.requests[0]["headers"]["SKRouteTag"], "rt")
        self.assertEqual(session.requests[1]["url"], "https://ilink.example.test/ilink/bot/get_qrcode_status?qrcode=qr-1")

    async def test_get_updates_uses_token_headers_and_cursor(self):
        session = _FakeSession(
            [
                {
                    "ret": 0,
                    "get_updates_buf": "next-buf",
                    "longpolling_timeout_ms": 35000,
                    "msgs": [
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
                    ],
                }
            ]
        )
        client = ClawBotClient(base_url="https://ilink.example.test", bot_token="token-1", session=session)

        result = await client.get_updates(get_updates_buf="old-buf")

        request = session.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://ilink.example.test/ilink/bot/getupdates")
        self.assertEqual(request["headers"]["AuthorizationType"], "ilink_bot_token")
        self.assertEqual(request["headers"]["Authorization"], "Bearer token-1")
        self.assertIn("X-WECHAT-UIN", request["headers"])
        self.assertEqual(request["json"]["get_updates_buf"], "old-buf")
        self.assertEqual(request["json"]["base_info"]["channel_version"], "2.0.0")
        self.assertEqual(result.get_updates_buf, "next-buf")
        self.assertEqual(result.messages[0].text_content(), "hello")

    async def test_send_text_includes_required_ilink_routing_fields(self):
        session = _FakeSession([{}])
        client = ClawBotClient(base_url="https://ilink.example.test", bot_token="token-1", session=session)

        await client.send_text(to_user_id="peer-1", context_token="ctx-1", text="hello")

        request = session.requests[0]
        self.assertEqual(request["url"], "https://ilink.example.test/ilink/bot/sendmessage")
        body = request["json"]
        self.assertEqual(body["base_info"]["channel_version"], "2.0.0")
        self.assertEqual(body["msg"]["from_user_id"], "")
        self.assertTrue(body["msg"]["client_id"].startswith("meetyou:"))
        self.assertEqual(body["msg"]["to_user_id"], "peer-1")
        self.assertEqual(body["msg"]["context_token"], "ctx-1")
        self.assertEqual(body["msg"]["message_type"], 2)
        self.assertEqual(body["msg"]["message_state"], 2)
        self.assertEqual(body["msg"]["item_list"][0]["text_item"]["text"], "hello")


if __name__ == "__main__":
    unittest.main()
