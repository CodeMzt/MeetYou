import json
import tempfile
import unittest
from pathlib import Path

from adapters.clawbot_client import ClawBotAccount, ClawBotClient, sanitize_bot_agent


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
        return json.dumps(self._payload)


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        return _FakeResponse(self.payload)


class ClawBotClientTests(unittest.IsolatedAsyncioTestCase):
    def test_loads_official_openclaw_account_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            accounts_dir = root / "openclaw-weixin" / "accounts"
            accounts_dir.mkdir(parents=True)
            (root / "openclaw-weixin" / "accounts.json").write_text(
                json.dumps(["acc-1"]),
                encoding="utf-8",
            )
            (accounts_dir / "acc-1.json").write_text(
                json.dumps(
                    {
                        "token": "token-1",
                        "baseUrl": "https://ilink.example.test",
                        "userId": "bot-user",
                        "name": "main",
                    }
                ),
                encoding="utf-8",
            )

            client = ClawBotClient(state_dir=str(root))

            accounts = client.list_accounts()
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0].account_id, "acc-1")
            self.assertEqual(accounts[0].token, "token-1")
            self.assertEqual(accounts[0].base_url, "https://ilink.example.test")
            self.assertEqual(accounts[0].user_id, "bot-user")

    async def test_send_text_uses_official_ilink_headers_and_body(self):
        session = _FakeSession({"ret": 0})
        client = ClawBotClient(
            bot_agent="MeetYou/1.0",
            channel_version="meetyou",
            ilink_app_id="appid",
            ilink_app_client_version="0",
            session=session,
        )
        account = ClawBotAccount(
            account_id="acc-1",
            token="token-1",
            base_url="https://ilink.example.test",
            user_id="bot-user",
        )

        await client.send_text(account, to_user_id="peer-1", context_token="ctx-1", text="hello")

        request = session.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://ilink.example.test/ilink/bot/sendmessage")
        self.assertEqual(request["headers"]["AuthorizationType"], "ilink_bot_token")
        self.assertEqual(request["headers"]["Authorization"], "Bearer token-1")
        self.assertIn("X-WECHAT-UIN", request["headers"])
        self.assertEqual(request["headers"]["iLink-App-Id"], "appid")
        self.assertEqual(request["json"]["base_info"]["bot_agent"], "MeetYou/1.0")
        self.assertEqual(request["json"]["base_info"]["channel_version"], "meetyou")
        self.assertEqual(request["json"]["msg"]["to_user_id"], "peer-1")
        self.assertEqual(request["json"]["msg"]["context_token"], "ctx-1")
        self.assertEqual(request["json"]["msg"]["item_list"][0]["text_item"]["text"], "hello")

    async def test_get_updates_parses_text_messages_and_cursor(self):
        session = _FakeSession(
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
        )
        client = ClawBotClient(session=session)
        account = ClawBotAccount(account_id="acc-1", token="token-1", base_url="https://ilink.example.test")

        result = await client.get_updates(account, get_updates_buf="old-buf", timeout_ms=35000)

        self.assertEqual(result.ret, 0)
        self.assertEqual(result.get_updates_buf, "next-buf")
        self.assertEqual(result.longpolling_timeout_ms, 35000)
        self.assertEqual(result.messages[0].text_content(), "hello")
        self.assertEqual(session.requests[0]["url"], "https://ilink.example.test/ilink/bot/getupdates")
        self.assertEqual(session.requests[0]["json"]["get_updates_buf"], "old-buf")

    def test_sanitize_bot_agent_keeps_official_shape(self):
        self.assertEqual(sanitize_bot_agent("MeetYou/1.0 (desktop)"), "MeetYou/1.0 (desktop)")
        self.assertEqual(sanitize_bot_agent("bad token with spaces"), "MeetYou/1.0")


if __name__ == "__main__":
    unittest.main()
