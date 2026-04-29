import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from core.app_lifecycle import (
    _start_external_endpoint_provider,
    build_runtime_processors,
    start_external_endpoint_providers,
    stop_external_endpoint_providers,
)
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
                await stop_external_endpoint_providers(app)

            import asyncio

            asyncio.run(_run())

        self.assertTrue(app.meetwechat_started)
        self.assertIsNone(app.feishu_input)
        self.assertIsNone(app.feishu_output)

    def test_external_endpoint_provider_supervisor_recovers_transient_start_failure(self):
        async def _run():
            import asyncio

            recovered = asyncio.Event()
            calls = {"count": 0}

            async def flaky_starter(app):
                calls["count"] += 1
                if calls["count"] == 1:
                    app.feishu_input = SimpleNamespace(close=AsyncMock())
                    app.feishu_output = SimpleNamespace(close=AsyncMock())
                    raise RuntimeError("gateway not ready yet")
                app.feishu_started = True
                recovered.set()

            app = SimpleNamespace(
                config=_Config({"enable_feishu_bot": True}),
                event_bus=SimpleNamespace(shutdown_event=asyncio.Event()),
                feishu_input=None,
                feishu_output=None,
                wechat_input=None,
                wechat_output=None,
                feishu_started=False,
                _external_endpoint_provider_retry_initial_delay_seconds=0.01,
                _external_endpoint_provider_retry_max_delay_seconds=0.01,
            )

            with self.assertLogs("meetyou.app.lifecycle", level="ERROR"):
                await _start_external_endpoint_provider(
                    app,
                    provider_name="feishu",
                    enabled_key="enable_feishu_bot",
                    starter=flaky_starter,
                )
            await asyncio.wait_for(recovered.wait(), timeout=1)
            await stop_external_endpoint_providers(app)
            return calls["count"], app.feishu_started

        import asyncio

        calls, started = asyncio.run(_run())
        self.assertEqual(calls, 2)
        self.assertTrue(started)


if __name__ == "__main__":
    unittest.main()
