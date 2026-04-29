import unittest
from types import SimpleNamespace

from core.app_lifecycle import (
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

    def test_external_endpoint_providers_are_not_started_inside_core(self):
        app = SimpleNamespace(
            config=_Config({"enable_feishu_bot": True, "enable_meetwechat_client": True}),
            feishu_input=None,
            feishu_output=None,
            wechat_input=None,
            wechat_output=None,
            meetwechat_started=False,
        )

        with self.assertLogs("meetyou.app.lifecycle", level="INFO") as logs:
            async def _run():
                await start_external_endpoint_providers(app)
                await stop_external_endpoint_providers(app)

            import asyncio

            asyncio.run(_run())

        self.assertFalse(app.meetwechat_started)
        self.assertIsNone(app.feishu_input)
        self.assertIsNone(app.feishu_output)
        self.assertIn("python -m endpoint_providers.feishu", "\n".join(logs.output))
        self.assertIn("python -m endpoint_providers.meetwechat", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
