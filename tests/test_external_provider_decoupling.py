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
            "from adapters.meetwechat_client",
            "_start_feishu_endpoint_provider",
            "_start_meetwechat_endpoint_provider",
            "_register_feishu_broadcast_targets",
        ]
        combined = f"{lifecycle}\n{app}"
        for token in forbidden:
            self.assertNotIn(token, combined)

    def test_standalone_external_provider_entrypoints_exist(self):
        self.assertTrue((ROOT / "endpoint_providers" / "feishu.py").exists())
        self.assertTrue((ROOT / "endpoint_providers" / "meetwechat.py").exists())


if __name__ == "__main__":
    unittest.main()
