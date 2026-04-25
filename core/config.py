"""
配置管理器。

从 config.json 加载普通配置，从 .env/环境变量加载密钥配置，
并提供统一的读取、写入、快照与热更新辅助能力。
"""

from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from adapters.base import create_adapter
from core.exceptions import ConfigError
from core.persistence import atomic_write_json, atomic_write_text, load_json_with_recovery
from core.protocol_schema import CONFIG_FIELD_KEYS, SUPPORTED_PROVIDER_VALUES, THINKING_EFFORT_VALUES
from core.repositories import ConfigRepository, ConfigTransactionSnapshot
from tools.memory_layers import dt_to_iso, utcnow

logger = logging.getLogger("meetyou.config")

_CONFIG_FILE_PATH = "user/config.json"
_ENV_FILE_PATH = ".env"
_MCP_SERVER_CONFIG_PATH = "user/core_mcp_servers.json"
_CONFIG_METADATA_KEY = "_meta"
_CONFIG_SCHEMA_VERSION = "2"
_REMOVED_WECHAT_CONFIG_KEYS = {
    "enable_" + "wechat_bot",
    *{
        "wechat_" + "i" + "link_" + suffix
        for suffix in (
            "base_url",
            "channel_version",
            "login_poll_interval_seconds",
            "max_text_chars",
            "poll_timeout_ms",
            "qr_output_path",
            "token_file",
            "inbound_worker_count",
            "inbound_queue_size",
            "outbound_worker_count",
            "outbound_queue_size",
            "outbound_min_interval_ms",
            "send_timeout_ms",
            "state_flush_interval_ms",
            "gateway_client_idle_ttl_seconds",
        )
    },
}
_REMOVED_CONFIG_KEYS = {
    "enable_gateway",
    "source_profiles",
    *_REMOVED_WECHAT_CONFIG_KEYS,
}
_ENV_ASSIGNMENT_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_BOOLEAN_TRUE_VALUES = {"1", "true", "yes", "on"}
_BOOLEAN_FALSE_VALUES = {"0", "false", "no", "off"}
_BOOLEAN_KEYS = {
    "enable_feishu_bot",
    "enable_meetwechat_client",
    "memory_background_episode_save",
    "thinking_enabled",
    "heartbeat_idle_poke_enabled",
    "heartbeat_idle_context_compaction_enabled",
}
_INTEGER_KEYS = {
    "gateway_port",
    "heartbeat_interval",
    "heartbeat_idle_poke_after_seconds",
    "heartbeat_idle_poke_cooldown_seconds",
    "housekeeping_interval",
    "scheduler_interval",
    "thinking_budget_tokens",
    "meetwechat_error_backoff_seconds",
    "meetwechat_max_text_chars",
    "meetwechat_poll_interval_seconds",
    "meetwechat_inbound_worker_count",
    "meetwechat_inbound_queue_size",
    "meetwechat_outbound_worker_count",
    "meetwechat_outbound_queue_size",
    "meetwechat_outbound_min_interval_ms",
    "meetwechat_send_timeout_ms",
    "meetwechat_state_flush_interval_ms",
    "meetwechat_gateway_client_idle_ttl_seconds",
    "max_parallel_tool_calls",
    "web_search_parallel_reads",
    "web_search_extract_timeout_seconds",
    "memory_auto_search_timeout_ms",
}
_POSITIVE_INTEGER_KEYS = {
    "heartbeat_interval",
    "heartbeat_idle_poke_after_seconds",
    "heartbeat_idle_poke_cooldown_seconds",
    "housekeeping_interval",
    "scheduler_interval",
    "meetwechat_error_backoff_seconds",
    "meetwechat_max_text_chars",
    "meetwechat_poll_interval_seconds",
    "meetwechat_inbound_worker_count",
    "meetwechat_inbound_queue_size",
    "meetwechat_outbound_worker_count",
    "meetwechat_outbound_queue_size",
    "meetwechat_outbound_min_interval_ms",
    "meetwechat_send_timeout_ms",
    "meetwechat_state_flush_interval_ms",
    "meetwechat_gateway_client_idle_ttl_seconds",
    "max_parallel_tool_calls",
    "web_search_parallel_reads",
    "web_search_extract_timeout_seconds",
    "memory_auto_search_timeout_ms",
}
_JSON_OBJECT_KEYS = {
    "assistant_modes",
    "mode_router",
    "document_parsers",
    "office_integrations",
    "meetwechat_proxy_policy",
}
_LIST_KEYS = {"trusted_write_roots", "feishu_broadcast_chat_ids", "gateway_cors_origins"}
_URL_KEYS = {
    "api_url",
    "embedding_api_url",
    "heartbeat_api_url",
    "mcp_registry_url",
    "meetwechat_base_url",
}
_PROVIDER_KEYS = {"api_provider", "heartbeat_api_provider"}
_THINKING_EFFORT_VALUES = set(THINKING_EFFORT_VALUES)
_SUPPORTED_PROVIDERS = set(SUPPORTED_PROVIDER_VALUES)

_ENV_KEY_MAP = {
    "agent_access_token": "MEETYOU_AGENT_WS_ACCESS_TOKEN",
    "api_key": "MEETYOU_API_KEY",
    "heartbeat_api_key": "MEETYOU_HEARTBEAT_API_KEY",
    "embedding_api_key": "MEETYOU_EMBEDDING_API_KEY",
    "object_store_access_key": "MEETYOU_OBJECT_STORE_ACCESS_KEY",
    "object_store_secret_key": "MEETYOU_OBJECT_STORE_SECRET_KEY",
    "database_url": "MEETYOU_DATABASE_URL",
    "gateway_access_token": "MEETYOU_GATEWAY_ACCESS_TOKEN",
    "feishu_app_id": "MEETYOU_FEISHU_APP_ID",
    "feishu_app_secret": "MEETYOU_FEISHU_APP_SECRET",
    "notion_token": "NOTION_TOKEN",
    "tavily_api_key": "TAVILY_API_KEY",
}
_ENV_OVERRIDE_KEY_MAP = {
    "enable_meetwechat_client": "MEETYOU_MEETWECHAT_ENABLE",
    "meetwechat_base_url": "MEETYOU_MEETWECHAT_BASE_URL",
    "meetwechat_error_backoff_seconds": "MEETYOU_MEETWECHAT_ERROR_BACKOFF_SECONDS",
    "meetwechat_max_text_chars": "MEETYOU_MEETWECHAT_MAX_TEXT_CHARS",
    "meetwechat_poll_interval_seconds": "MEETYOU_MEETWECHAT_POLL_INTERVAL_SECONDS",
    "meetwechat_state_file": "MEETYOU_MEETWECHAT_STATE_FILE",
    "meetwechat_inbound_worker_count": "MEETYOU_MEETWECHAT_INBOUND_WORKERS",
    "meetwechat_inbound_queue_size": "MEETYOU_MEETWECHAT_INBOUND_QUEUE_SIZE",
    "meetwechat_outbound_worker_count": "MEETYOU_MEETWECHAT_OUTBOUND_WORKERS",
    "meetwechat_outbound_queue_size": "MEETYOU_MEETWECHAT_OUTBOUND_QUEUE_SIZE",
    "meetwechat_outbound_min_interval_ms": "MEETYOU_MEETWECHAT_OUTBOUND_MIN_INTERVAL_MS",
    "meetwechat_send_timeout_ms": "MEETYOU_MEETWECHAT_SEND_TIMEOUT_MS",
    "meetwechat_state_flush_interval_ms": "MEETYOU_MEETWECHAT_STATE_FLUSH_INTERVAL_MS",
    "meetwechat_gateway_client_idle_ttl_seconds": "MEETYOU_MEETWECHAT_GATEWAY_CLIENT_IDLE_TTL_SECONDS",
}

_KNOWN_CONFIG_KEYS = set(CONFIG_FIELD_KEYS)
_AGENT_ACCESS_TOKEN_ENV_KEYS = (
    "MEETYOU_AGENT_WS_ACCESS_TOKEN",
    "MEETYOU_AGENT_ACCESS_TOKEN",
)


class ConfigManager(ConfigRepository):
    def __init__(
        self,
        config_file_path: str = _CONFIG_FILE_PATH,
        env_file_path: str = _ENV_FILE_PATH,
    ):
        self._config_file_path = config_file_path
        self._env_file_path = env_file_path
        self._mcp_server_config_path = _MCP_SERVER_CONFIG_PATH
        self._config: dict[str, Any] = {}
        self._config_metadata: dict[str, Any] = self._default_config_metadata()
        self._mcp_server_config: dict[str, Any] = {}
        self._mcp_server_config_diagnostic = self._build_mcp_server_config_diagnostic(
            status="not_loaded",
            message="Core MCP 配置尚未加载。",
        )
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

    def _default_config_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": _CONFIG_SCHEMA_VERSION,
            "revision": 0,
            "updated_at": "",
        }

    def _load_env(self):
        try:
            from dotenv import load_dotenv

            load_dotenv(self._env_file_path, override=False)
        except ImportError:
            logger.info("python-dotenv 未安装，仅使用系统环境变量")

    def _load_config(self):
        try:
            payload = load_json_with_recovery(
                self._config_file_path,
                validator=lambda data: isinstance(data, dict),
            )
        except FileNotFoundError:
            raise ConfigError(f"配置文件不存在: {self._config_file_path}")
        except ValueError as exc:
            raise ConfigError(f"配置文件格式错误: {exc}")
        if not isinstance(payload, dict):
            raise ConfigError(f"配置文件格式错误: {self._config_file_path}")
        metadata = payload.get(_CONFIG_METADATA_KEY)
        payload, metadata = self._strip_removed_config_keys(payload, metadata)
        self._config_metadata = self._normalize_config_metadata(metadata)
        self._config = {
            key: value
            for key, value in payload.items()
            if key != _CONFIG_METADATA_KEY
        }
        logger.info("配置文件已加载: %s", self._config_file_path)

    def _strip_removed_config_keys(self, payload: dict[str, Any], metadata: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        removed_keys = sorted(key for key in _REMOVED_CONFIG_KEYS if key in payload)
        if not removed_keys:
            return payload, metadata if isinstance(metadata, dict) else {}
        cleaned_payload = {key: value for key, value in payload.items() if key not in _REMOVED_CONFIG_KEYS}
        cleaned_metadata = self._normalize_config_metadata(metadata)
        cleaned_metadata["schema_version"] = _CONFIG_SCHEMA_VERSION
        cleaned_metadata["revision"] = int(cleaned_metadata.get("revision", 0) or 0) + 1
        cleaned_metadata["updated_at"] = dt_to_iso(utcnow())
        self._persist_config_state(
            {
                key: value
                for key, value in cleaned_payload.items()
                if key != _CONFIG_METADATA_KEY
            },
            cleaned_metadata,
        )
        logger.warning("已从配置中移除失效配置项: %s", ", ".join(removed_keys))
        return cleaned_payload, cleaned_metadata

    def _normalize_config_metadata(self, metadata: Any) -> dict[str, Any]:
        payload = metadata if isinstance(metadata, dict) else {}
        try:
            revision = int(payload.get("revision", 0) or 0)
        except (TypeError, ValueError):
            revision = 0
        return {
            "schema_version": str(payload.get("schema_version") or _CONFIG_SCHEMA_VERSION),
            "revision": max(revision, 0),
            "updated_at": str(payload.get("updated_at") or ""),
        }

    def _build_mcp_server_config_diagnostic(
        self,
        *,
        status: str,
        message: str,
        server_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "scope": "core",
            "path": self._mcp_server_config_path,
            "status": status,
            "server_count": max(int(server_count or 0), 0),
            "message": str(message or "").strip(),
        }

    def _load_mcp_config(self):
        try:
            with open(self._mcp_server_config_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except FileNotFoundError:
            self._mcp_server_config = {}
            self._mcp_server_config_diagnostic = self._build_mcp_server_config_diagnostic(
                status="missing",
                message=(
                    f"Core MCP 配置文件不存在: {self._mcp_server_config_path}。"
                    "这只表示服务端 Core 级 MCP 未配置；客户端本地 MCP 仍由 Desktop Agent 的 user/mcp_servers.json 托管。"
                ),
            )
            logger.info(self._mcp_server_config_diagnostic["message"])
            return
        except json.JSONDecodeError as e:
            self._mcp_server_config = {}
            self._mcp_server_config_diagnostic = self._build_mcp_server_config_diagnostic(
                status="invalid",
                message=f"Core MCP 配置文件格式错误: {self._mcp_server_config_path} ({e})",
            )
            logger.warning(self._mcp_server_config_diagnostic["message"])
            return
        if not isinstance(payload, dict):
            self._mcp_server_config = {}
            self._mcp_server_config_diagnostic = self._build_mcp_server_config_diagnostic(
                status="invalid",
                message=f"Core MCP 配置文件格式错误: {self._mcp_server_config_path}",
            )
            logger.warning(self._mcp_server_config_diagnostic["message"])
            return
        self._mcp_server_config = payload
        server_count = len(self.get_mcp_servers())
        self._mcp_server_config_diagnostic = self._build_mcp_server_config_diagnostic(
            status="loaded",
            server_count=server_count,
            message=(
                f"已加载 Core MCP 配置: {self._mcp_server_config_path} "
                f"({server_count} 个服务端 MCP)。"
            ),
        )
        logger.info(self._mcp_server_config_diagnostic["message"])

    @staticmethod
    def _mask_secret(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 4:
            return "*" * len(value)
        return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"

    @staticmethod
    def is_secret_key(key: str) -> bool:
        return key in _ENV_KEY_MAP

    def is_manageable_key(self, key: str) -> bool:
        return key in _ENV_KEY_MAP or key in _KNOWN_CONFIG_KEYS or (
            key in self._config and key != _CONFIG_METADATA_KEY
        )

    def _build_config_payload(self, config: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        ordered: dict[str, Any] = {_CONFIG_METADATA_KEY: self._normalize_config_metadata(metadata)}
        ordered.update(config)
        return ordered

    def _persist_config_state(self, config: dict[str, Any], metadata: dict[str, Any]) -> None:
        atomic_write_json(
            self._config_file_path,
            self._build_config_payload(config, metadata),
        )

    def _read_env_text(self) -> str:
        env_path = Path(self._env_file_path)
        if not env_path.exists():
            return ""
        return env_path.read_text(encoding="utf-8")

    @staticmethod
    def _serialize_env_value(value: Any) -> str:
        text = "" if value is None else str(value)
        return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"

    def _build_env_text(self, updates: dict[str, Any]) -> str:
        lines = self._read_env_text().splitlines()
        pending = {key: self._serialize_env_value(value) for key, value in updates.items()}
        rendered: list[str] = []
        for line in lines:
            match = _ENV_ASSIGNMENT_RE.match(line)
            if match is None:
                rendered.append(line)
                continue
            env_key = match.group(1)
            if env_key in pending:
                rendered.append(f"{env_key}={pending.pop(env_key)}")
            else:
                rendered.append(line)
        for env_key, serialized in pending.items():
            rendered.append(f"{env_key}={serialized}")
        if not rendered:
            return ""
        return "\n".join(rendered) + "\n"

    def _persist_env_updates(self, updates: dict[str, Any]) -> None:
        atomic_write_text(self._env_file_path, self._build_env_text(updates))
        for env_key, value in updates.items():
            os.environ[env_key] = "" if value is None else str(value)

    def begin_transaction(self) -> ConfigTransactionSnapshot:
        return ConfigTransactionSnapshot(
            config=deepcopy(self._config),
            metadata=deepcopy(self._config_metadata),
            env_text=self._read_env_text(),
            env_values={env_key: os.environ.get(env_key) for env_key in _ENV_KEY_MAP.values()},
        )

    def rollback_transaction(self, snapshot: ConfigTransactionSnapshot) -> None:
        self._persist_config_state(snapshot.config, snapshot.metadata)
        atomic_write_text(self._env_file_path, snapshot.env_text)
        for env_key, value in snapshot.env_values.items():
            if value is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = value
        self._config = deepcopy(snapshot.config)
        self._config_metadata = deepcopy(snapshot.metadata)

    def get(self, key: str, default=None):
        if key == "agent_access_token":
            for env_key in _AGENT_ACCESS_TOKEN_ENV_KEYS:
                env_val = os.environ.get(env_key)
                if env_val:
                    return env_val
        if key in _ENV_KEY_MAP:
            env_val = os.environ.get(_ENV_KEY_MAP[key])
            if env_val:
                return env_val
        if key in _ENV_OVERRIDE_KEY_MAP:
            env_val = os.environ.get(_ENV_OVERRIDE_KEY_MAP[key])
            if env_val:
                return env_val
        return self._config.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in _BOOLEAN_TRUE_VALUES
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

    def _normalize_boolean(self, key: str, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in _BOOLEAN_TRUE_VALUES:
                return True
            if lowered in _BOOLEAN_FALSE_VALUES:
                return False
        raise ConfigError(f"配置项 {key} 需要布尔值")

    def _normalize_integer(self, key: str, value: Any) -> int:
        if isinstance(value, bool):
            raise ConfigError(f"配置项 {key} 需要整数")
        if isinstance(value, int):
            number = value
        elif isinstance(value, float) and value.is_integer():
            number = int(value)
        elif isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
            number = int(value.strip())
        else:
            raise ConfigError(f"配置项 {key} 需要整数")
        if key == "gateway_port" and not 0 <= number <= 65535:
            raise ConfigError("gateway_port 需在 0 到 65535 之间")
        if key in _POSITIVE_INTEGER_KEYS and number < 1:
            raise ConfigError(f"配置项 {key} 需要大于 0")
        if key == "thinking_budget_tokens" and number < 0:
            raise ConfigError("thinking_budget_tokens 不能小于 0")
        return number

    def _normalize_json_object(self, key: str, value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"配置项 {key} 需要有效 JSON 对象: {exc}") from exc
        if not isinstance(value, dict):
            raise ConfigError(f"配置项 {key} 需要 JSON 对象")
        return value

    def _normalize_list(self, key: str, value: Any) -> list[str]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"配置项 {key} 需要字符串数组: {exc}") from exc
        if not isinstance(value, list):
            raise ConfigError(f"配置项 {key} 需要字符串数组")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            if not text:
                raise ConfigError(f"配置项 {key} 不能包含空字符串")
            if text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    def _normalize_url(self, key: str, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError(f"配置项 {key} 需要有效 URL")
        return text

    def _normalize_provider(self, key: str, value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        if text not in _SUPPORTED_PROVIDERS:
            raise ConfigError(f"配置项 {key} 不支持值: {text}")
        create_adapter(text)
        return text

    def _normalize_text(self, value: Any) -> str:
        return str(value or "").strip()

    def _normalize_value(self, key: str, value: Any) -> Any:
        if key in _ENV_KEY_MAP:
            return self._normalize_text(value)
        if key in _BOOLEAN_KEYS:
            return self._normalize_boolean(key, value)
        if key in _INTEGER_KEYS:
            return self._normalize_integer(key, value)
        if key in _JSON_OBJECT_KEYS:
            return self._normalize_json_object(key, value)
        if key in _LIST_KEYS:
            return self._normalize_list(key, value)
        if key in _URL_KEYS:
            return self._normalize_url(key, value)
        if key in _PROVIDER_KEYS:
            return self._normalize_provider(key, value)
        if key == "thinking_effort":
            text = self._normalize_text(value).lower()
            if text and text not in _THINKING_EFFORT_VALUES:
                raise ConfigError(f"thinking_effort 仅支持: {', '.join(sorted(_THINKING_EFFORT_VALUES))}")
            return text
        if key == "research_contact_email":
            text = self._normalize_text(value)
            if text and ("@" not in text or text.startswith("@") or text.endswith("@")):
                raise ConfigError("research_contact_email 需要有效邮箱地址")
            return text
        if key == "gateway_host":
            text = self._normalize_text(value)
            if text and any(char.isspace() for char in text):
                raise ConfigError("gateway_host 不能包含空白字符")
            return text
        return value

    def _validate_semantics(self, updates: dict[str, Any], merged_config: dict[str, Any]) -> None:
        provider = str(merged_config.get("api_provider") or "").strip().lower()
        if {"api_provider", "model"}.intersection(updates) and provider and not str(merged_config.get("model") or "").strip():
            raise ConfigError("配置主模型时必须同时提供 model")
        heartbeat_provider = str(merged_config.get("heartbeat_api_provider") or "").strip().lower()
        if {"heartbeat_api_provider", "heart_model"}.intersection(updates) and heartbeat_provider and not str(merged_config.get("heart_model") or "").strip():
            raise ConfigError("配置心跳模型提供商时必须同时提供 heart_model")
        thinking_enabled = bool(merged_config.get("thinking_enabled"))
        thinking_effort = str(merged_config.get("thinking_effort") or "").strip()
        if {"thinking_enabled", "thinking_effort"}.intersection(updates) and not thinking_enabled and thinking_effort:
            raise ConfigError("thinking_enabled=false 时不能设置 thinking_effort")
        gateway_cors_origins = merged_config.get("gateway_cors_origins")
        if isinstance(gateway_cors_origins, list) and "*" in gateway_cors_origins:
            raise ConfigError("gateway_cors_origins 不能包含通配符 *")
        trusted_write_roots = merged_config.get("trusted_write_roots")
        if isinstance(trusted_write_roots, list):
            for item in trusted_write_roots:
                if not str(item or "").strip():
                    raise ConfigError("trusted_write_roots 不能包含空路径")

    def apply_updates(self, updates: dict[str, Any]) -> tuple[list[str], list[str]]:
        if not isinstance(updates, dict):
            raise ConfigError("配置更新载荷必须是对象")
        if not updates:
            return [], []
        normalized_updates: dict[str, Any] = {}
        secret_updates: dict[str, Any] = {}
        next_config = deepcopy(self._config)
        for key, value in updates.items():
            if not self.is_manageable_key(key):
                raise ConfigError(f"未知配置项: {key}")
            normalized_value = self._normalize_value(key, value)
            normalized_updates[key] = normalized_value
            if self.is_secret_key(key):
                secret_updates[_ENV_KEY_MAP[key]] = normalized_value
            else:
                next_config[key] = normalized_value
        self._validate_semantics(normalized_updates, next_config)
        next_metadata = self._normalize_config_metadata(self._config_metadata)
        next_metadata["schema_version"] = _CONFIG_SCHEMA_VERSION
        next_metadata["revision"] = int(next_metadata.get("revision", 0) or 0) + 1
        next_metadata["updated_at"] = dt_to_iso(utcnow())
        snapshot = self.begin_transaction()
        try:
            self._persist_config_state(next_config, next_metadata)
            self._persist_env_updates(secret_updates)
        except Exception as exc:
            try:
                self.rollback_transaction(snapshot)
            except Exception as rollback_exc:
                logger.error("配置写入失败且回滚失败: %s", rollback_exc)
            logger.error("配置持久化失败: %s", exc)
            raise ConfigError(f"配置持久化失败: {exc}") from exc
        self._config = next_config
        self._config_metadata = next_metadata
        return sorted(normalized_updates.keys()), []

    def describe_key(self, key: str) -> dict[str, Any]:
        if not self.is_manageable_key(key):
            raise ConfigError(f"未知配置项: {key}")

        secret = self.is_secret_key(key)
        if secret:
            env_key = _ENV_KEY_MAP[key]
            if key == "agent_access_token":
                value = ""
                for candidate_env_key in _AGENT_ACCESS_TOKEN_ENV_KEYS:
                    value = os.environ.get(candidate_env_key, "")
                    if value:
                        env_key = candidate_env_key
                        break
            else:
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

        if key in _ENV_OVERRIDE_KEY_MAP:
            env_key = _ENV_OVERRIDE_KEY_MAP[key]
            value = os.environ.get(env_key, "")
            if value:
                return {
                    "key": key,
                    "value": value,
                    "raw_value": value,
                    "is_secret": False,
                    "has_value": True,
                    "source": "env",
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
        keys = sorted(set(self._config) | _KNOWN_CONFIG_KEYS | set(_ENV_KEY_MAP) | set(_ENV_OVERRIDE_KEY_MAP))
        return {key: self.describe_key(key) for key in keys if self.is_manageable_key(key)}

    def get_mcp_servers(self) -> dict[str, Any]:
        servers = self._mcp_server_config.get("mcpServers", {})
        if isinstance(servers, dict) and servers:
            return servers
        synthesized: dict[str, Any] = {}
        tavily_api_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if tavily_api_key:
            synthesized["tavily_web"] = {
                "command": "npx",
                "args": ["-y", "tavily-mcp@0.1.3"],
                "env": {},
                "enabled": True,
            }
        return synthesized

    def get_mcp_server_config_diagnostic(self) -> dict[str, Any]:
        return dict(self._mcp_server_config_diagnostic)
