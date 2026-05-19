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
            "MEETYOU_CLIENT_ACCESS_TOKEN": os.environ.get("MEETYOU_CLIENT_ACCESS_TOKEN"),
            "MEETYOU_API_KEY": os.environ.get("MEETYOU_API_KEY"),
            "MEETYOU_HEARTBEAT_API_KEY": os.environ.get("MEETYOU_HEARTBEAT_API_KEY"),
            "MEETYOU_EMBEDDING_API_KEY": os.environ.get("MEETYOU_EMBEDDING_API_KEY"),
            "MEETYOU_DATABASE_URL": os.environ.get("MEETYOU_DATABASE_URL"),
            "MEETYOU_CORE_BASE_URL": os.environ.get("MEETYOU_CORE_BASE_URL"),
            "MEETYOU_CORE_SHELL_EXEC_ENABLED": os.environ.get("MEETYOU_CORE_SHELL_EXEC_ENABLED"),
            "MEETYOU_CORE_CMD_POLICY_PATH": os.environ.get("MEETYOU_CORE_CMD_POLICY_PATH"),
            "MEETYOU_CORE_COMMAND_TIMEOUT_SECONDS": os.environ.get("MEETYOU_CORE_COMMAND_TIMEOUT_SECONDS"),
            "MEETYOU_CORE_COMMAND_OUTPUT_MAX_CHARS": os.environ.get("MEETYOU_CORE_COMMAND_OUTPUT_MAX_CHARS"),
            "MEETYOU_FEISHU_ENABLE": os.environ.get("MEETYOU_FEISHU_ENABLE"),
            "MEETYOU_FEISHU_APP_ID": os.environ.get("MEETYOU_FEISHU_APP_ID"),
            "MEETYOU_FEISHU_APP_SECRET": os.environ.get("MEETYOU_FEISHU_APP_SECRET"),
            "MEETYOU_CLAWBOT_WECHAT_ENABLE": os.environ.get("MEETYOU_CLAWBOT_WECHAT_ENABLE"),
            "MEETYOU_CLAWBOT_ILINK_BOT_TOKEN": os.environ.get("MEETYOU_CLAWBOT_ILINK_BOT_TOKEN"),
            "MEETYOU_CLAWBOT_ILINK_BASE_URL": os.environ.get("MEETYOU_CLAWBOT_ILINK_BASE_URL"),
            "MEETYOU_CLAWBOT_ILINK_STATE_FILE": os.environ.get("MEETYOU_CLAWBOT_ILINK_STATE_FILE"),
            "MEETYOU_CLAWBOT_ILINK_BOT_ID": os.environ.get("MEETYOU_CLAWBOT_ILINK_BOT_ID"),
            "MEETYOU_CLAWBOT_ILINK_USER_ID": os.environ.get("MEETYOU_CLAWBOT_ILINK_USER_ID"),
            "MEETYOU_CLAWBOT_ILINK_CHANNEL_VERSION": os.environ.get("MEETYOU_CLAWBOT_ILINK_CHANNEL_VERSION"),
            "MEETYOU_CLAWBOT_ILINK_APP_CLIENT_VERSION": os.environ.get("MEETYOU_CLAWBOT_ILINK_APP_CLIENT_VERSION"),
            "MEETYOU_CLAWBOT_ILINK_ROUTE_TAG": os.environ.get("MEETYOU_CLAWBOT_ILINK_ROUTE_TAG"),
            "MEETYOU_CLAWBOT_ILINK_POLL_TIMEOUT_MS": os.environ.get("MEETYOU_CLAWBOT_ILINK_POLL_TIMEOUT_MS"),
            "MEETYOU_CLAWBOT_ILINK_MAX_TEXT_CHARS": os.environ.get("MEETYOU_CLAWBOT_ILINK_MAX_TEXT_CHARS"),
            "MEETYOU_CLAWBOT_ILINK_INBOUND_WORKERS": os.environ.get("MEETYOU_CLAWBOT_ILINK_INBOUND_WORKERS"),
            "MEETYOU_CLAWBOT_ILINK_INBOUND_QUEUE_SIZE": os.environ.get("MEETYOU_CLAWBOT_ILINK_INBOUND_QUEUE_SIZE"),
            "MEETYOU_CLAWBOT_ILINK_OUTBOUND_MIN_INTERVAL_MS": os.environ.get("MEETYOU_CLAWBOT_ILINK_OUTBOUND_MIN_INTERVAL_MS"),
            "MEETYOU_CLAWBOT_ILINK_SEND_TIMEOUT_MS": os.environ.get("MEETYOU_CLAWBOT_ILINK_SEND_TIMEOUT_MS"),
            "MEETYOU_CLAWBOT_ILINK_STATE_FLUSH_INTERVAL_MS": os.environ.get("MEETYOU_CLAWBOT_ILINK_STATE_FLUSH_INTERVAL_MS"),
            "MEETYOU_CLAWBOT_ILINK_GATEWAY_ENDPOINT_IDLE_TTL_SECONDS": os.environ.get("MEETYOU_CLAWBOT_ILINK_GATEWAY_ENDPOINT_IDLE_TTL_SECONDS"),
            "MEETYOU_CLAWBOT_ILINK_REPLY_TIMEOUT_SECONDS": os.environ.get("MEETYOU_CLAWBOT_ILINK_REPLY_TIMEOUT_SECONDS"),
            "MEETYOU_MEETWECHAT_ENABLE": os.environ.get("MEETYOU_MEETWECHAT_ENABLE"),
            "MEETYOU_MEETWECHAT_BASE_URL": os.environ.get("MEETYOU_MEETWECHAT_BASE_URL"),
            "MEETYOU_MEETWECHAT_POLL_INTERVAL_SECONDS": os.environ.get("MEETYOU_MEETWECHAT_POLL_INTERVAL_SECONDS"),
            "MEETYOU_MEETWECHAT_ERROR_BACKOFF_SECONDS": os.environ.get("MEETYOU_MEETWECHAT_ERROR_BACKOFF_SECONDS"),
            "MEETYOU_MEETWECHAT_MAX_TEXT_CHARS": os.environ.get("MEETYOU_MEETWECHAT_MAX_TEXT_CHARS"),
            "MEETYOU_MEETWECHAT_STATE_FILE": os.environ.get("MEETYOU_MEETWECHAT_STATE_FILE"),
            "NOTION_TOKEN": os.environ.get("NOTION_TOKEN"),
            "TAVILY_API_KEY": os.environ.get("TAVILY_API_KEY"),
        }
        for key in self._old_env:
            os.environ.pop(key, None)
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

    def test_disabling_thinking_clears_effort_and_budget(self):
        (self.temp_root / "user" / "config.json").write_text(
            json.dumps(
                {
                    "api_provider": "openai",
                    "model": "gpt-4o",
                    "thinking_enabled": True,
                    "thinking_effort": "high",
                    "thinking_budget_tokens": 2048,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        applied, _ = config.apply_updates({"thinking_enabled": False, "thinking_effort": "未设置"})

        self.assertEqual(applied, ["thinking_budget_tokens", "thinking_effort", "thinking_enabled"])
        self.assertFalse(config.get_bool("thinking_enabled"))
        self.assertEqual(config.get("thinking_effort"), "")
        self.assertEqual(config.get("thinking_budget_tokens"), 0)

    def test_client_access_token_prefers_client_env_over_gateway_and_config(self):
        (self.temp_root / "user" / "config.json").write_text(
            json.dumps(
                {
                    "api_provider": "openai",
                    "model": "gpt-4o",
                    "client_access_token": "client-from-config",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.temp_root / ".env").write_text(
            "MEETYOU_CLIENT_ACCESS_TOKEN=client-from-env\n"
            "MEETYOU_GATEWAY_ACCESS_TOKEN=gateway-from-env\n",
            encoding="utf-8",
        )

        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        self.assertEqual(config.get("client_access_token"), "client-from-env")
        entry = config.describe_key("client_access_token")
        self.assertEqual(entry["source"], "env")
        self.assertEqual(entry["env_key"], "MEETYOU_CLIENT_ACCESS_TOKEN")
        self.assertTrue(entry["has_value"])

    def test_process_env_overrides_dotenv_file(self):
        (self.temp_root / ".env").write_text(
            "MEETYOU_DATABASE_URL=postgresql+psycopg://from-dotenv\n",
            encoding="utf-8",
        )
        os.environ["MEETYOU_DATABASE_URL"] = "postgresql+psycopg://from-process-env"

        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        self.assertEqual(config.get("database_url"), "postgresql+psycopg://from-process-env")

    def test_feishu_enable_can_be_overridden_by_process_env_for_local_acceptance(self):
        (self.temp_root / "user" / "config.json").write_text(
            json.dumps({"enable_feishu_bot": True}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.environ["MEETYOU_FEISHU_ENABLE"] = "false"

        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        self.assertFalse(config.get_bool("enable_feishu_bot"))

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
        self.assertIn("Desktop Endpoint Provider", diagnostic["message"])
        self.assertTrue(
            any("Core MCP 配置文件不存在" in message for message in captured.output),
            captured.output,
        )

    def test_core_mcp_config_is_loaded_separately_from_desktop_client_mcp(self):
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
        old_enable_key = "enable_" + "wechat_bot"
        old_base_url_key = "wechat_" + "i" + "link_" + "base_url"
        old_token_file_key = "wechat_" + "i" + "link_" + "token_file"
        (self.temp_root / "user" / "config.json").write_text(
            json.dumps(
                {
                    "api_provider": "openai",
                    "model": "gpt-4o",
                    "enable_gateway": True,
                    "source_profiles": {"legacy": {}},
                    old_enable_key: True,
                    old_base_url_key: "https://legacy-wechat.example.test",
                    old_token_file_key: "user/wechat_state.json",
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
        self.assertNotIn(old_enable_key, snapshot)
        self.assertNotIn(old_base_url_key, snapshot)
        self.assertNotIn(old_token_file_key, snapshot)
        self.assertFalse(config.is_manageable_key("enable_gateway"))
        self.assertFalse(config.is_manageable_key("source_profiles"))
        self.assertFalse(config.is_manageable_key(old_enable_key))
        self.assertFalse(config.is_manageable_key(old_base_url_key))

    def test_meetwechat_settings_are_manageable_and_typed(self):
        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        applied_keys, warnings = config.apply_updates(
            {
                "enable_meetwechat_client": "true",
                "meetwechat_base_url": "http://127.0.0.1:38961",
                "meetwechat_poll_interval_seconds": "2",
                "meetwechat_error_backoff_seconds": 3,
                "meetwechat_max_text_chars": "1800",
                "meetwechat_state_file": "user/meetwechat_client_state.json",
                "meetwechat_proxy_policy": {
                    "mode": "guarded_auto",
                    "private_default": "auto",
                    "group_default": "mention_only",
                },
                "meetwechat_inbound_worker_count": "4",
                "meetwechat_inbound_queue_size": "500",
                "meetwechat_outbound_worker_count": "2",
                "meetwechat_outbound_queue_size": "500",
                "meetwechat_outbound_min_interval_ms": "250",
                "meetwechat_send_timeout_ms": "10000",
                "meetwechat_state_flush_interval_ms": "500",
                "meetwechat_gateway_endpoint_idle_ttl_seconds": "600",
            }
        )
        config.reload()

        self.assertEqual(warnings, [])
        self.assertEqual(
            set(applied_keys),
            {
                "enable_meetwechat_client",
                "meetwechat_base_url",
                "meetwechat_poll_interval_seconds",
                "meetwechat_error_backoff_seconds",
                "meetwechat_max_text_chars",
                "meetwechat_state_file",
                "meetwechat_proxy_policy",
                "meetwechat_inbound_worker_count",
                "meetwechat_inbound_queue_size",
                "meetwechat_outbound_worker_count",
                "meetwechat_outbound_queue_size",
                "meetwechat_outbound_min_interval_ms",
                "meetwechat_send_timeout_ms",
                "meetwechat_state_flush_interval_ms",
                "meetwechat_gateway_endpoint_idle_ttl_seconds",
            },
        )
        self.assertIs(config.get("enable_meetwechat_client"), True)
        self.assertEqual(config.get("meetwechat_poll_interval_seconds"), 2)
        self.assertEqual(config.get("meetwechat_error_backoff_seconds"), 3)
        self.assertEqual(config.get("meetwechat_max_text_chars"), 1800)
        self.assertEqual(config.get("meetwechat_proxy_policy")["mode"], "guarded_auto")
        self.assertEqual(config.get("meetwechat_inbound_worker_count"), 4)
        self.assertEqual(config.get("meetwechat_outbound_worker_count"), 2)
        self.assertEqual(config.get("meetwechat_send_timeout_ms"), 10000)

    def test_clawbot_wechat_settings_are_manageable_and_typed(self):
        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        applied_keys, warnings = config.apply_updates(
            {
                "enable_clawbot_wechat_client": "true",
                "clawbot_ilink_bot_token": "token-1",
                "clawbot_ilink_base_url": "https://ilinkai.weixin.qq.com",
                "clawbot_ilink_state_file": "user/clawbot_ilink_state.json",
                "clawbot_ilink_bot_id": "bot-1",
                "clawbot_ilink_user_id": "user-1",
                "clawbot_ilink_channel_version": "2.0.0",
                "clawbot_ilink_app_client_version": "1",
                "clawbot_ilink_route_tag": "route-1",
                "clawbot_ilink_poll_timeout_ms": "35000",
                "clawbot_ilink_max_text_chars": "1800",
                "clawbot_ilink_inbound_worker_count": "4",
                "clawbot_ilink_inbound_queue_size": "500",
                "clawbot_ilink_outbound_min_interval_ms": "250",
                "clawbot_ilink_send_timeout_ms": "15000",
                "clawbot_ilink_state_flush_interval_ms": "500",
                "clawbot_ilink_gateway_endpoint_idle_ttl_seconds": "600",
                "clawbot_ilink_reply_timeout_seconds": "120",
            }
        )
        config.reload()

        self.assertEqual(warnings, [])
        self.assertEqual(
            set(applied_keys),
            {
                "enable_clawbot_wechat_client",
                "clawbot_ilink_bot_token",
                "clawbot_ilink_base_url",
                "clawbot_ilink_state_file",
                "clawbot_ilink_bot_id",
                "clawbot_ilink_user_id",
                "clawbot_ilink_channel_version",
                "clawbot_ilink_app_client_version",
                "clawbot_ilink_route_tag",
                "clawbot_ilink_poll_timeout_ms",
                "clawbot_ilink_max_text_chars",
                "clawbot_ilink_inbound_worker_count",
                "clawbot_ilink_inbound_queue_size",
                "clawbot_ilink_outbound_min_interval_ms",
                "clawbot_ilink_send_timeout_ms",
                "clawbot_ilink_state_flush_interval_ms",
                "clawbot_ilink_gateway_endpoint_idle_ttl_seconds",
                "clawbot_ilink_reply_timeout_seconds",
            },
        )
        self.assertIs(config.get("enable_clawbot_wechat_client"), True)
        self.assertEqual(config.get("clawbot_ilink_bot_token"), "token-1")
        self.assertEqual(config.get("clawbot_ilink_poll_timeout_ms"), 35000)
        self.assertEqual(config.get("clawbot_ilink_max_text_chars"), 1800)
        self.assertEqual(config.get("clawbot_ilink_send_timeout_ms"), 15000)
        self.assertEqual(config.get("clawbot_ilink_reply_timeout_seconds"), 120)
        config_data = json.loads((self.temp_root / "user" / "config.json").read_text(encoding="utf-8"))
        self.assertNotIn("clawbot_ilink_bot_token", config_data)
        self.assertIn(
            "MEETYOU_CLAWBOT_ILINK_BOT_TOKEN='token-1'",
            (self.temp_root / ".env").read_text(encoding="utf-8"),
        )

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

    def test_env_file_non_empty_value_overrides_blank_process_env(self):
        os.environ["MEETYOU_CLAWBOT_ILINK_BOT_TOKEN"] = ""
        (self.temp_root / ".env").write_text(
            "MEETYOU_CLAWBOT_ILINK_BOT_TOKEN=token-from-env-file\n",
            encoding="utf-8",
        )

        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        self.assertEqual(config.get("clawbot_ilink_bot_token"), "token-from-env-file")

    def test_heartbeat_idle_settings_are_manageable_and_typed(self):
        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        applied_keys, warnings = config.apply_updates(
            {
                "heartbeat_idle_poke_enabled": "false",
                "heartbeat_idle_poke_after_seconds": "1800",
                "heartbeat_idle_poke_cooldown_seconds": 900,
                "heartbeat_idle_context_compaction_enabled": "true",
            }
        )
        config.reload()

        self.assertEqual(warnings, [])
        self.assertEqual(
            set(applied_keys),
            {
                "heartbeat_idle_poke_enabled",
                "heartbeat_idle_poke_after_seconds",
                "heartbeat_idle_poke_cooldown_seconds",
                "heartbeat_idle_context_compaction_enabled",
            },
        )
        self.assertIs(config.get("heartbeat_idle_poke_enabled"), False)
        self.assertEqual(config.get("heartbeat_idle_poke_after_seconds"), 1800)
        self.assertEqual(config.get("heartbeat_idle_poke_cooldown_seconds"), 900)
        self.assertIs(config.get("heartbeat_idle_context_compaction_enabled"), True)

    def test_core_base_url_is_manageable_and_can_come_from_env(self):
        os.environ["MEETYOU_CORE_BASE_URL"] = "https://core.example.test"
        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        snapshot = config.snapshot()

        self.assertEqual(config.get("core_base_url"), "https://core.example.test")
        self.assertIn("core_base_url", snapshot)
        self.assertEqual(snapshot["core_base_url"]["env_key"], "MEETYOU_CORE_BASE_URL")

    def test_core_command_settings_are_manageable_typed_and_env_overridable(self):
        os.environ["MEETYOU_CORE_SHELL_EXEC_ENABLED"] = "false"
        os.environ["MEETYOU_CORE_CMD_POLICY_PATH"] = "user/override_core_cmd_policy.json"
        os.environ["MEETYOU_CORE_COMMAND_TIMEOUT_SECONDS"] = "9"
        os.environ["MEETYOU_CORE_COMMAND_OUTPUT_MAX_CHARS"] = "9000"
        config = ConfigManager(
            config_file_path=str(self.temp_root / "user" / "config.json"),
            env_file_path=str(self.temp_root / ".env"),
        )

        snapshot = config.snapshot()

        self.assertFalse(config.get_bool("core_shell_exec_enabled"))
        self.assertEqual(config.get("core_cmd_policy_path"), "user/override_core_cmd_policy.json")
        self.assertEqual(config.get("core_command_timeout_seconds"), "9")
        self.assertEqual(config.get("core_command_output_max_chars"), "9000")
        self.assertEqual(snapshot["core_shell_exec_enabled"]["env_key"], "MEETYOU_CORE_SHELL_EXEC_ENABLED")
        self.assertEqual(snapshot["core_cmd_policy_path"]["env_key"], "MEETYOU_CORE_CMD_POLICY_PATH")

        os.environ.pop("MEETYOU_CORE_SHELL_EXEC_ENABLED", None)
        os.environ.pop("MEETYOU_CORE_CMD_POLICY_PATH", None)
        os.environ.pop("MEETYOU_CORE_COMMAND_TIMEOUT_SECONDS", None)
        os.environ.pop("MEETYOU_CORE_COMMAND_OUTPUT_MAX_CHARS", None)
        applied, warnings = config.apply_updates(
            {
                "core_shell_exec_enabled": "true",
                "core_cmd_policy_path": "user/core_cmd_policy.json",
                "core_command_timeout_seconds": "120",
                "core_command_output_max_chars": 20000,
            }
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            set(applied),
            {
                "core_shell_exec_enabled",
                "core_cmd_policy_path",
                "core_command_timeout_seconds",
                "core_command_output_max_chars",
            },
        )
        self.assertIs(config.get("core_shell_exec_enabled"), True)
        self.assertEqual(config.get("core_command_timeout_seconds"), 120)
        self.assertEqual(config.get("core_command_output_max_chars"), 20000)

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
