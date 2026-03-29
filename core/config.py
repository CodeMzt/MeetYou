"""
配置管理器。

从 config.json 加载非敏感配置，从 .env/环境变量加载 API 密钥。
原 manager.py 中 ConfigManager 部分的独立重构。
"""

import json
import os
import logging

from core.exceptions import ConfigError

logger = logging.getLogger("meetyou.config")

_CONFIG_FILE_PATH = "user/config.json"
_MCP_SERVER_CONFIG_PATH = "user/mcp_servers.json"

# 环境变量名 ↔ config key 的映射
_ENV_KEY_MAP = {
    "api_key": "MEETYOU_API_KEY",
    "heartbeat_api_key": "MEETYOU_HEARTBEAT_API_KEY",
    "embedding_api_key": "MEETYOU_EMBEDDING_API_KEY",
    "feishu_app_id": "MEETYOU_FEISHU_APP_ID",
    "feishu_app_secret": "MEETYOU_FEISHU_APP_SECRET",
}


class ConfigManager:
    """
    配置管理器。

    - 非敏感配置从 config.json 加载
    - API 密钥优先从环境变量读取（支持 .env 文件）
    - MCP 服务器配置单独加载
    """

    def __init__(self, config_file_path: str = _CONFIG_FILE_PATH):
        self._config_file_path = config_file_path
        self._mcp_server_config_path = _MCP_SERVER_CONFIG_PATH
        self._config: dict = {}
        self._mcp_server_config: dict = {}

        self._load_env()
        self._load_config()
        self._load_mcp_config()

    def _load_env(self):
        """从 .env 文件加载环境变量"""
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            logger.info("python-dotenv 未安装，仅使用系统环境变量")

    def _load_config(self):
        try:
            with open(self._config_file_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            logger.info(f"配置文件已加载: {self._config_file_path}")
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
            logger.warning(f"MCP 配置文件格式错误: {e}")
            self._mcp_server_config = {}

    def get(self, key: str, default=None):
        """
        获取配置项。密钥类配置优先从环境变量读取。

        Args:
            key: 配置项名称
            default: 默认值

        Returns:
            配置值；找不到则返回 default
        """
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
        """
        根据提示词名称加载文件内容。

        Args:
            prompt_name: 如 "soul", "start", "heartbeat"

        Returns:
            提示词文本

        Raises:
            ConfigError: 路径未配置或文件不存在
        """
        path = self.get(f"{prompt_name}_path")
        if not path:
            raise ConfigError(f"未配置提示词路径: {prompt_name}_path")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            raise ConfigError(f"提示词文件不存在: {path}")

    def update(self, key: str, value):
        """更新配置项并持久化到文件"""
        self._config[key] = value
        try:
            with open(self._config_file_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"配置持久化失败: {e}")

    def get_mcp_servers(self) -> dict:
        """获取已配置的 MCP 服务器列表"""
        return self._mcp_server_config.get("mcpServers", {})
