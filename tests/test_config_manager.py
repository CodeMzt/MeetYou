import json
import os
import tempfile
import unittest
from pathlib import Path

from core.config import ConfigManager
from core.exceptions import ConfigError


class ConfigManagerTests(unittest.TestCase):
    def setUp(self):
        self._old_cwd = os.getcwd()
        self._old_env = {
            "MEETYOU_API_KEY": os.environ.get("MEETYOU_API_KEY"),
            "MEETYOU_HEARTBEAT_API_KEY": os.environ.get("MEETYOU_HEARTBEAT_API_KEY"),
            "MEETYOU_EMBEDDING_API_KEY": os.environ.get("MEETYOU_EMBEDDING_API_KEY"),
            "MEETYOU_DATABASE_URL": os.environ.get("MEETYOU_DATABASE_URL"),
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
                    "model": "gpt-4o",
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

    def test_missing_core_mcp_config_logs_boundary_message(self):
        with self.assertLogs("meetyou.config", level="INFO") as captured:
            config = ConfigManager(
                config_file_path=str(self.temp_root / "user" / "config.json"),
                env_file_path=str(self.temp_root / ".env"),
            )

        diagnostic = config.get_mcp_server_config_diagnostic()
        self.assertEqual(config.get_mcp_servers(), {})
        self.assertEqual(diagnostic["status"], "missing")
        self.assertIn("core_mcp_servers.json", diagnostic["path"])
        self.assertIn("Desktop Agent", diagnostic["message"])
        self.assertTrue(
            any("Core MCP 配置文件不存在" in message for message in captured.output),
            captured.output,
        )

    def test_core_mcp_config_is_loaded_separately_from_desktop_agent_mcp(self):
        (self.temp_root / "user" / "core_mcp_servers.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "tavily_web": {
                            "command": "npx.cmd",
                            "args": ["-y", "tavily-mcp@0.1.3"],
                            "enabled": True,
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        diagnostic = config.get_mcp_server_config_diagnostic()
        self.assertEqual(sorted(config.get_mcp_servers()), ["tavily_web"])
        self.assertEqual(diagnostic["status"], "loaded")
        self.assertEqual(diagnostic["server_count"], 1)
        self.assertIn("1 个服务端 MCP", diagnostic["message"])

    def test_load_config_strips_removed_legacy_keys(self):
        (self.temp_root / "user" / "config.json").write_text(
            json.dumps(
                {
                    "api_provider": "openai",
                    "model": "gpt-4o",
                    "enable_gateway": True,
                    "source_profiles": {"legacy": {}},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        snapshot = json.loads((self.temp_root / "user" / "config.json").read_text(encoding="utf-8"))
        self.assertNotIn("enable_gateway", snapshot)
        self.assertNotIn("source_profiles", snapshot)
        self.assertFalse(config.is_manageable_key("enable_gateway"))
        self.assertFalse(config.is_manageable_key("source_profiles"))

    def test_apply_updates_persists_json_and_env(self):
        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        applied_keys, warnings = config.apply_updates(
            {
                "api_provider": "anthropic",
                "api_key": "new-secret",
                "task_file_path": "user/custom_tasks.json",
            }
        )
        config.reload()

        self.assertEqual(warnings, [])
        self.assertEqual(set(applied_keys), {"api_provider", "api_key", "task_file_path"})
        self.assertEqual(config.get("api_provider"), "anthropic")
        self.assertEqual(config.get("api_key"), "new-secret")
        self.assertEqual(config.get("task_file_path"), "user/custom_tasks.json")

        config_data = json.loads((self.temp_root / "user" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config_data["_meta"]["schema_version"], "2")
        self.assertEqual(config_data["_meta"]["revision"], 1)
        self.assertEqual(config_data["api_provider"], "anthropic")
        self.assertEqual(config_data["task_file_path"], "user/custom_tasks.json")
        self.assertIn("MEETYOU_API_KEY='new-secret'", (self.temp_root / ".env").read_text(encoding="utf-8"))
        self.assertTrue((self.temp_root / "user" / "config.json.bak").exists())
        self.assertTrue((self.temp_root / ".env.bak").exists())

    def test_apply_updates_rejects_invalid_values_without_polluting_files(self):
        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )
        before_config = (self.temp_root / "user" / "config.json").read_text(encoding="utf-8")
        before_env = (self.temp_root / ".env").read_text(encoding="utf-8")

        with self.assertRaisesRegex(ConfigError, "gateway_port"):
            config.apply_updates({"gateway_port": 70000})

        self.assertEqual((self.temp_root / "user" / "config.json").read_text(encoding="utf-8"), before_config)
        self.assertEqual((self.temp_root / ".env").read_text(encoding="utf-8"), before_env)

    def test_rollback_transaction_restores_previous_state(self):
        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )
        snapshot = config.begin_transaction()

        config.apply_updates({"api_provider": "anthropic", "api_key": "rolled-secret"})
        config.rollback_transaction(snapshot)
        config.reload()

        self.assertEqual(config.get("api_provider"), "openai")
        self.assertEqual(config.get("api_key"), "test-secret")


if __name__ == "__main__":
    unittest.main()
