import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from core.app_lifecycle import build_runtime_processors, start_external_endpoint_providers
from core.heart import Heart


class _Config:
    def __init__(self, enabled: dict[str, bool]):
        self._enabled = enabled

    def get_bool(self, key: str, default: bool = False) -> bool:
        return self._enabled.get(key, default)


class AppLifecycleV4Tests(unittest.TestCase):
    def test_runtime_uses_app_scheduler_not_legacy_heart_scheduler_or_heartbeat_clocks(self):
        app = SimpleNamespace(
            brain_processor=lambda: "brain",
            scheduler_processor=lambda: "scheduler",
            heart=SimpleNamespace(
                housekeeping_processor=lambda: "housekeeping",
            ),
            proprioceptor=SimpleNamespace(run=lambda: "proprioceptor"),
        )

        self.assertEqual(
            build_runtime_processors(app),
            ("brain", "scheduler", "housekeeping", "proprioceptor"),
        )

    def test_heart_no_longer_exposes_scheduler_clock(self):
        self.assertFalse(hasattr(Heart, "scheduler_processor"))

    def test_external_endpoint_provider_failure_does_not_block_other_providers(self):
        async def failing_feishu(app):
            app.feishu_input = SimpleNamespace(close=AsyncMock())
            app.feishu_output = SimpleNamespace(close=AsyncMock())
            raise RuntimeError("adapter boot failed")

        async def started_meetwechat(app):
            app.meetwechat_started = True

        app = SimpleNamespace(
            config=_Config({"enable_feishu_bot": True, "enable_meetwechat_client": True}),
            feishu_input=None,
            feishu_output=None,
            wechat_input=None,
            wechat_output=None,
            meetwechat_started=False,
        )

        with (
            self.assertLogs("meetyou.app.lifecycle", level="ERROR"),
            patch("core.app_lifecycle._start_feishu_endpoint_provider", side_effect=failing_feishu),
            patch("core.app_lifecycle._start_meetwechat_endpoint_provider", side_effect=started_meetwechat),
        ):
            async def _run():
                await start_external_endpoint_providers(app)

            import asyncio

            asyncio.run(_run())

        self.assertTrue(app.meetwechat_started)
        self.assertIsNone(app.feishu_input)
        self.assertIsNone(app.feishu_output)


if __name__ == "__main__":
    unittest.main()
