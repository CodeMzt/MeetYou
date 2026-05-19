from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ExternalProviderDecouplingTests(unittest.TestCase):
    def test_core_lifecycle_does_not_import_external_provider_adapters(self):
        lifecycle = (ROOT / "core" / "app_lifecycle.py").read_text(encoding="utf-8")
        app = (ROOT / "core" / "app.py").read_text(encoding="utf-8")

        forbidden = [
            "from sensors.feishu_input_adapter",
            "from sensors.feishu_output_adapter",
            "from sensors.meetwechat_adapter",
            "from sensors.clawbot_wechat_adapter",
            "from adapters.meetwechat_client",
            "from adapters.clawbot_client",
            "_start_feishu_endpoint_provider",
            "_start_meetwechat_endpoint_provider",
            "_register_feishu_broadcast_targets",
        ]
        combined = f"{lifecycle}\n{app}"
        for token in forbidden:
            self.assertNotIn(token, combined)

    def test_standalone_external_provider_entrypoints_exist(self):
        self.assertTrue((ROOT / "endpoint_providers" / "feishu.py").exists())
        self.assertTrue((ROOT / "endpoint_providers" / "clawbot.py").exists())
        self.assertTrue((ROOT / "endpoint_providers" / "meetwechat.py").exists())

    def test_clawbot_provider_does_not_depend_on_openclaw(self):
        paths = [
            ROOT / "adapters" / "clawbot_client.py",
            ROOT / "sensors" / "clawbot_wechat_adapter.py",
            ROOT / "endpoint_providers" / "clawbot.py",
            ROOT / "docs" / "ClawBot_Wechat.md",
        ]
        forbidden = [
            "openclaw",
            "openclaw_state_dir",
            "openclaw-weixin",
            "accounts.json",
            "channels login",
        ]

        for path in paths:
            text = path.read_text(encoding="utf-8").lower()
            for token in forbidden:
                self.assertNotIn(token, text, f"{token!r} leaked into {path}")


if __name__ == "__main__":
    unittest.main()
