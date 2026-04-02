"""
配置管理器。

从 config.json 加载普通配置，从 .env/环境变量加载密钥配置，
并提供统一的读取、写入、快照与热更新辅助能力。
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from core.exceptions import ConfigError

logger = logging.getLogger("meetyou.config")

_CONFIG_FILE_PATH = "user/config.json"
_ENV_FILE_PATH = ".env"
_MCP_SERVER_CONFIG_PATH = "user/mcp_servers.json"

_ENV_KEY_MAP = {
    "api_key": "MEETYOU_API_KEY",
    "heartbeat_api_key": "MEETYOU_HEARTBEAT_API_KEY",
    "embedding_api_key": "MEETYOU_EMBEDDING_API_KEY",
    "feishu_app_id": "MEETYOU_FEISHU_APP_ID",
    "feishu_app_secret": "MEETYOU_FEISHU_APP_SECRET",
    "notion_token": "NOTION_TOKEN",
    "tavily_api_key": "TAVILY_API_KEY",
}

_KNOWN_CONFIG_KEYS = {
    "api_provider",
    "api_url",
    "cmd_policy_path",
    "embedding_api_url",
    "embedding_model",
    "enable_feishu_bot",
    "enable_gateway",
    "feishu_broadcast_chat_ids",
    "feishu_default_chat_id",
    "feishu_chat_registry_path",
    "gateway_host",
    "gateway_port",
    "heartbeat_api_provider",
    "heartbeat_api_url",
    "heartbeat_interval",
    "heartbeat_path",
    "heart_model",
    "mcp_registry_url",
    "memory_file_path",
    "model",
    "soul_path",
    "start_path",
    "thinking_budget_tokens",
    "thinking_effort",
    "thinking_enabled",
    "tools_schema_path",
}


class ConfigManager:
    """
    配置管理器。

    - 非敏感配置从 config.json 加载
    - 密钥配置优先从环境变量/`.env` 读取
    - MCP 服务器配置单独加载
    """

    def __init__(
        self,
        config_file_path: str = _CONFIG_FILE_PATH,
        env_file_path: str = _ENV_FILE_PATH,
    ):
        self._config_file_path = config_file_path
        self._env_file_path = env_file_path
        self._mcp_server_config_path = _MCP_SERVER_CONFIG_PATH
        self._config: dict[str, Any] = {}
        self._mcp_server_config: dict[str, Any] = {}
        self.reload()

    @property
    def config_file_path(self) -> str:
        return self._config_file_path

    @property
    def env_file_path(self) -> str:
        return self._env_file_path

    def reload(self):
        self._load_env()
        self._load_config()
        self._load_mcp_config()

    def _load_env(self):
        try:
            from dotenv import load_dotenv

            load_dotenv(self._env_file_path, override=True)
        except ImportError:
            logger.info("python-dotenv 未安装，仅使用系统环境变量")

    def _load_config(self):
        try:
            with open(self._config_file_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            logger.info("配置文件已加载: %s", self._config_file_path)
        except FileNotFoundError:
            raise ConfigError(f"配置文件不存在: {self._config_file_path}")
        except json.JSONDecodeError as e:
            raise ConfigError(f"配置文件格式错误: {e}")

    def _load_mcp_config(self):
        try:
            with open(self._mcp_server_config_path, "r", encoding="utf-8") as f:
                self._mcp_server_config = json.load(f)
        except FileNotFoundError:
            logger.info("MCP 服务器配置文件不存在，跳过")
            self._mcp_server_config = {}
        except json.JSONDecodeError as e:
            logger.warning("MCP 配置文件格式错误: %s", e)
            self._mcp_server_config = {}

    def _write_config(self):
        with open(self._config_file_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=4, ensure_ascii=False)

    def _write_env_value(self, env_key: str, value: Any):
        try:
            from dotenv import set_key

            env_path = Path(self._env_file_path)
            if not env_path.exists():
                env_path.touch()
            serialized = "" if value is None else str(value)
            set_key(self._env_file_path, env_key, serialized)
            os.environ[env_key] = serialized
        except Exception as e:
            logger.error("写入 .env 失败 [%s]: %s", env_key, e)
            raise

    @staticmethod
    def is_secret_key(key: str) -> bool:
        return key in _ENV_KEY_MAP

    def is_manageable_key(self, key: str) -> bool:
        return key in _ENV_KEY_MAP or key in _KNOWN_CONFIG_KEYS or key in self._config

    @staticmethod
    def _mask_secret(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 4:
            return "*" * len(value)
        return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"

    def get(self, key: str, default=None):
        if key in _ENV_KEY_MAP:
            env_val = os.environ.get(_ENV_KEY_MAP[key])
            if env_val:
                return env_val
        return self._config.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def get_prompt(self, prompt_name: str) -> str:
        path = self.get(f"{prompt_name}_path")
        if not path:
            raise ConfigError(f"未配置提示词路径: {prompt_name}_path")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            raise ConfigError(f"提示词文件不存在: {path}")

    def update(self, key: str, value):
        self.apply_updates({key: value})

    def apply_updates(self, updates: dict[str, Any]) -> tuple[list[str], list[str]]:
        applied_keys: list[str] = []
        warnings: list[str] = []
        json_changed = False

        for key, value in updates.items():
            if not self.is_manageable_key(key):
                warnings.append(f"未知配置项，已跳过: {key}")
                continue

            if self.is_secret_key(key):
                env_key = _ENV_KEY_MAP[key]
                self._write_env_value(env_key, value)
                applied_keys.append(key)
                continue

            self._config[key] = value
            applied_keys.append(key)
            json_changed = True

        if json_changed:
            try:
                self._write_config()
            except Exception as e:
                logger.error("配置持久化失败: %s", e)
                raise

        return applied_keys, warnings

    def describe_key(self, key: str) -> dict[str, Any]:
        if not self.is_manageable_key(key):
            raise ConfigError(f"未知配置项: {key}")

        secret = self.is_secret_key(key)
        if secret:
            env_key = _ENV_KEY_MAP[key]
            value = os.environ.get(env_key, "")
            source = "env" if value else "default"
            return {
                "key": key,
                "value": self._mask_secret(value),
                "raw_value": None,
                "is_secret": True,
                "has_value": bool(value),
                "source": source,
                "env_key": env_key,
            }

        exists = key in self._config
        return {
            "key": key,
            "value": self._config.get(key),
            "raw_value": self._config.get(key),
            "is_secret": False,
            "has_value": exists and self._config.get(key) not in (None, ""),
            "source": "config" if exists else "default",
            "env_key": None,
        }

    def snapshot(self) -> dict[str, dict[str, Any]]:
        keys = sorted(set(self._config) | _KNOWN_CONFIG_KEYS | set(_ENV_KEY_MAP))
        return {key: self.describe_key(key) for key in keys if self.is_manageable_key(key)}

    def get_mcp_servers(self) -> dict:
        return self._mcp_server_config.get("mcpServers", {})
