import asyncio
import contextlib
import io
import unittest
from unittest.mock import patch

from adapters.clawbot_client import ClawBotLoginQRCode, ClawBotLoginStatus
from endpoint_providers import clawbot


class _Args:
    qr_output = "user/test-clawbot-login.txt"
    timeout_seconds = 30
    poll_interval_seconds = 0
    status_timeout_seconds = 30
    enable = True


class _FakeConfig:
    def __init__(self):
        self.applied = {}

    def get(self, key, default=None):
        values = {"clawbot_ilink_state_file": "user/test-clawbot-state.json"}
        return values.get(key, default)

    def apply_updates(self, updates):
        self.applied.update(updates)
        return list(updates), []


class _FakeLoginClient:
    def __init__(self):
        self.status_timeouts = []
        self.closed = False

    async def get_bot_qrcode(self):
        return ClawBotLoginQRCode(qrcode="qr-1", qrcode_img_content="https://qr.example.test")

    async def get_qrcode_status(self, qrcode, *, timeout_ms=None):
        self.status_timeouts.append(timeout_ms)
        if len(self.status_timeouts) == 1:
            raise asyncio.TimeoutError()
        return ClawBotLoginStatus(
            status="confirmed",
            bot_token="token-1",
            base_url="https://ilink.example.test",
            ilink_bot_id="bot-1",
            ilink_user_id="user-1",
        )

    async def close(self):
        self.closed = True


class _FakeStateStore:
    def __init__(self, path):
        self.path = path
        self.cleared = False

    async def clear_cursor(self, *, reason=""):
        self.cleared = reason == "login"

    async def close(self):
        pass


async def _sleep_noop(seconds):
    del seconds


class ClawBotProviderLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_retries_qr_status_timeout_without_crashing(self):
        config = _FakeConfig()
        client = _FakeLoginClient()

        with (
            patch("endpoint_providers.clawbot.ConfigManager", return_value=config),
            patch("endpoint_providers.clawbot._build_client", return_value=client),
            patch("endpoint_providers.clawbot.atomic_write_text"),
            patch("endpoint_providers.clawbot.ClawBotWechatStateStore", _FakeStateStore),
            patch("endpoint_providers.clawbot.asyncio.sleep", new=_sleep_noop),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                result = await clawbot.login(_Args())

        self.assertEqual(result, 0)
        self.assertEqual(client.status_timeouts, [30000, 30000])
        self.assertTrue(client.closed)
        self.assertEqual(config.applied["clawbot_ilink_bot_token"], "token-1")
        self.assertIs(config.applied["enable_clawbot_wechat_client"], True)


if __name__ == "__main__":
    unittest.main()
