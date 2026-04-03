import json
import os
import tempfile
import unittest
from pathlib import Path

from core.config import ConfigManager


class ConfigManagerTests(unittest.TestCase):
    def setUp(self):
        self._old_cwd = os.getcwd()
        self._old_env = {
            "MEETYOU_API_KEY": os.environ.get("MEETYOU_API_KEY"),
            "MEETYOU_HEARTBEAT_API_KEY": os.environ.get("MEETYOU_HEARTBEAT_API_KEY"),
            "MEETYOU_EMBEDDING_API_KEY": os.environ.get("MEETYOU_EMBEDDING_API_KEY"),
            "MEETYOU_FEISHU_APP_ID": os.environ.get("MEETYOU_FEISHU_APP_ID"),
            "MEETYOU_FEISHU_APP_SECRET": os.environ.get("MEETYOU_FEISHU_APP_SECRET"),
        }
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self._temp_dir.name)
        os.chdir(self.temp_root)
        (self.temp_root / "user").mkdir()
        (self.temp_root / "user" / "config.json").write_text(
            json.dumps(
                {
                    "api_provider": "openai",
                    "gateway_port": 8000,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.temp_root / "user" / "mcp_servers.json").write_text(
            json.dumps({"mcpServers": {}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.temp_root / ".env").write_text(
            "MEETYOU_API_KEY=test-secret\n",
            encoding="utf-8",
        )

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._temp_dir.cleanup()
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_snapshot_masks_secret_values(self):
        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        snapshot = config.snapshot()
        self.assertTrue(snapshot["api_key"]["is_secret"])
        self.assertTrue(snapshot["api_key"]["has_value"])
        self.assertNotEqual(snapshot["api_key"]["value"], "test-secret")
        self.assertEqual(config.get("api_key"), "test-secret")

    def test_apply_updates_persists_json_and_env(self):
        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        applied_keys, warnings = config.apply_updates(
            {
                "api_provider": "anthropic",
                "api_key": "new-secret",
            }
        )
        config.reload()

        self.assertEqual(warnings, [])
        self.assertEqual(set(applied_keys), {"api_provider", "api_key"})
        self.assertEqual(config.get("api_provider"), "anthropic")
        self.assertEqual(config.get("api_key"), "new-secret")

        config_data = json.loads((self.temp_root / "user" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config_data["api_provider"], "anthropic")
        self.assertIn("MEETYOU_API_KEY='new-secret'", (self.temp_root / ".env").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
