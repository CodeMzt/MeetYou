import json
import unittest

from adapters.wechat_ilink_client import (
    WeChatIlinkClient,
    WeChatIlinkCredentials,
    WeChatIlinkSessionExpired,
    build_ilink_client_version,
    build_ilink_url,
    build_send_text_payload,
)


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return json.dumps(self._payload)


class _FakeSession:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.requests = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        payload = self.payloads.pop(0)
        if isinstance(payload, _FakeResponse):
            return payload
        return _FakeResponse(payload)

    async def close(self):
        self.closed = True


class WeChatIlinkClientTests(unittest.IsolatedAsyncioTestCase):
    def test_build_url_avoids_duplicate_ilink_prefix(self):
        self.assertEqual(
            build_ilink_url("https://example.com/ilink/bot", "/ilink/bot/getupdates"),
            "https://example.com/ilink/bot/getupdates",
        )
        self.assertEqual(
            build_ilink_url("https://example.com", "/ilink/bot/getupdates"),
            "https://example.com/ilink/bot/getupdates",
        )

    def test_build_client_version_matches_official_encoding(self):
        self.assertEqual(build_ilink_client_version("2.1.7"), 131335)

    def test_build_send_text_payload_contains_context_token(self):
        payload = build_send_text_payload(
            to_user_id="user-1",
            context_token="ctx-1",
            text="hello",
            client_id="client-1",
            channel_version="2.0.0",
        )

        self.assertEqual(payload["base_info"]["channel_version"], "2.0.0")
        self.assertEqual(payload["msg"]["to_user_id"], "user-1")
        self.assertEqual(payload["msg"]["context_token"], "ctx-1")
        self.assertEqual(payload["msg"]["message_type"], 2)
        self.assertEqual(payload["msg"]["message_state"], 2)
        self.assertEqual(payload["msg"]["item_list"][0]["text_item"]["text"], "hello")

    async def test_send_text_uses_official_headers_and_body(self):
        session = _FakeSession({"ret": 0})
        client = WeChatIlinkClient(base_url="https://example.com", channel_version="2.0.0", session=session)
        credentials = WeChatIlinkCredentials(
            bot_token="bot-token",
            ilink_bot_id="bot-1",
            baseurl="https://example.com",
        )

        await client.send_text(
            credentials,
            to_user_id="user-1",
            context_token="ctx-1",
            text="hello",
            client_id="client-1",
        )

        request = session.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://example.com/ilink/bot/sendmessage")
        self.assertEqual(request["headers"]["AuthorizationType"], "ilink_bot_token")
        self.assertEqual(request["headers"]["Authorization"], "Bearer bot-token")
        self.assertTrue(request["headers"]["X-WECHAT-UIN"])
        self.assertEqual(request["headers"]["iLink-App-Id"], "bot")
        self.assertEqual(request["headers"]["iLink-App-ClientVersion"], "131072")
        self.assertEqual(request["json"]["msg"]["context_token"], "ctx-1")

    async def test_get_bot_qrcode_accepts_official_img_content_field(self):
        session = _FakeSession({
            "qrcode": "qr-token",
            "qrcode_img_content": "https://example.com/qrcode",
        })
        client = WeChatIlinkClient(base_url="https://example.com", session=session)

        qr = await client.get_bot_qrcode()

        self.assertEqual(qr.qrcode, "qr-token")
        self.assertEqual(qr.qrcode_url, "https://example.com/qrcode")
        request = session.requests[0]
        self.assertEqual(request["headers"]["iLink-App-Id"], "bot")

    async def test_get_updates_raises_on_session_expiry(self):
        session = _FakeSession({"ret": -14, "errmsg": "session timeout"})
        client = WeChatIlinkClient(base_url="https://example.com", session=session)
        credentials = WeChatIlinkCredentials(bot_token="bot-token", baseurl="https://example.com")

        with self.assertRaises(WeChatIlinkSessionExpired):
            await client.get_updates(credentials, get_updates_buf="", timeout_ms=35000)


if __name__ == "__main__":
    unittest.main()
