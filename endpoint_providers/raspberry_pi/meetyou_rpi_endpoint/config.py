from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("user") / "rpi_endpoint.json"
DEFAULT_ENDPOINT_TOKEN_ENV = "MEETYOU_RPI_ENDPOINT_TOKEN"


class RpiConfigError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class ReconnectConfig:
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_seconds: float = 1.0


@dataclass(slots=True)
class KeepaliveConfig:
    interval_seconds: int = 20
    timeout_seconds: int = 10


@dataclass(slots=True)
class OperationConfig:
    default_timeout_seconds: int = 30
    max_timeout_seconds: int = 300


@dataclass(slots=True)
class SecurityConfig:
    sandbox_dir: str = "/var/lib/meetyou-rpi/sandbox"
    safe_shell_enabled: bool = False
    safe_shell_allowlist: list[dict[str, Any] | str] = field(default_factory=list)
    gpio_allowed_pins: list[int] = field(default_factory=lambda: [17, 27, 22])
    gpio_write_default_duration_ms: int = 500


@dataclass(slots=True)
class RpiEndpointConfig:
    core_base_url: str = "http://127.0.0.1:8000"
    endpoint_id: str = "raspberry-pi-dev"
    endpoint_name: str = "Raspberry Pi Dev Endpoint"
    endpoint_token_env: str = DEFAULT_ENDPOINT_TOKEN_ENV
    connect_path: str = "/endpoint/ws"
    workspace_ids: list[str] = field(default_factory=lambda: ["personal"])
    provider_type: str = "rpi"
    transport_profile: str = "rpi_wss"
    supports_markdown: bool = True
    supports_offline_cache: bool = False
    max_parallel_calls: int = 2
    reconnect: ReconnectConfig = field(default_factory=ReconnectConfig)
    keepalive: KeepaliveConfig = field(default_factory=KeepaliveConfig)
    operation: OperationConfig = field(default_factory=OperationConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    core_access_token: str = field(default="", repr=False)
    config_file_path: str = str(DEFAULT_CONFIG_PATH)

    @property
    def provider_id(self) -> str:
        return self.endpoint_id

    @property
    def display_name(self) -> str:
        return self.endpoint_name

    @property
    def executor_endpoint_id(self) -> str:
        return f"{self.provider_type}.{self.endpoint_id}.executor"

    @property
    def websocket_url(self) -> str:
        base = self.core_base_url.rstrip("/")
        if base.startswith("https://"):
            base = "wss://" + base[len("https://") :]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://") :]
        path = self.connect_path if self.connect_path.startswith("/") else f"/{self.connect_path}"
        return f"{base}{path}"

    @property
    def heartbeat_interval_seconds(self) -> int:
        return self.keepalive.interval_seconds

    @property
    def reconnect_delay_seconds(self) -> int:
        return int(self.reconnect.initial_delay_seconds)

    def token_status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.core_access_token),
            "endpoint_token_env": self.endpoint_token_env,
        }

    def require_token(self) -> None:
        if self.core_access_token:
            return
        raise RpiConfigError(
            "missing_endpoint_token",
            (
                "missing Raspberry Pi endpoint token; set env "
                f"`{DEFAULT_ENDPOINT_TOKEN_ENV}` or configured env `{self.endpoint_token_env}`"
            ),
        )


def _load_env_file(env_file_path: Path) -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file_path, override=False)
    except ImportError:
        return


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RpiConfigError("invalid_config_json", f"invalid JSON config: {path}") from exc
    if not isinstance(payload, dict):
        raise RpiConfigError("invalid_config_shape", f"config root must be an object: {path}")
    return payload


def _dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: Any, default: list[str]) -> list[str]:
    if value is None:
        value = default
    if not isinstance(value, list):
        value = [value]
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _int_list(value: Any, default: list[int]) -> list[int]:
    if value is None:
        value = default
    if not isinstance(value, list):
        value = [value]
    result: list[int] = []
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number not in result:
            result.append(number)
    return result


def _to_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _to_int(value: Any, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _to_float(value: Any, default: float, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _resolve_token(payload: dict[str, Any], endpoint_token_env: str) -> str:
    env_candidates = [
        DEFAULT_ENDPOINT_TOKEN_ENV,
        endpoint_token_env,
        "MEETYOU_CLIENT_ACCESS_TOKEN",
        "MEETYOU_GATEWAY_ACCESS_TOKEN",
    ]
    for env_name in env_candidates:
        value = str(os.environ.get(env_name, "")).strip()
        if value:
            return value
    return str(payload.get("core_access_token") or "").strip()


def _config_path(config_file_path: str | None) -> Path:
    selected = config_file_path or os.environ.get("MEETYOU_RPI_CONFIG") or str(DEFAULT_CONFIG_PATH)
    return Path(selected)


def load_rpi_endpoint_config(config_file_path: str | None = None) -> RpiEndpointConfig:
    file_path = _config_path(config_file_path)
    env_root = file_path.parent.parent if file_path.parent.name == "user" else file_path.parent
    _load_env_file(env_root / ".env")
    payload = _read_json(file_path)
    reconnect_payload = _dict(payload, "reconnect")
    keepalive_payload = _dict(payload, "keepalive")
    operation_payload = _dict(payload, "operation")
    security_payload = _dict(payload, "security")

    endpoint_token_env = str(
        os.environ.get("MEETYOU_RPI_ENDPOINT_TOKEN_ENV")
        or payload.get("endpoint_token_env")
        or DEFAULT_ENDPOINT_TOKEN_ENV
    ).strip() or DEFAULT_ENDPOINT_TOKEN_ENV

    max_timeout = _to_int(operation_payload.get("max_timeout_seconds"), 300, minimum=1)
    default_timeout = _to_int(
        operation_payload.get("default_timeout_seconds"),
        30,
        minimum=1,
        maximum=max_timeout,
    )

    safe_shell_enabled = _to_bool(
        os.environ.get("MEETYOU_RPI_SAFE_SHELL_ENABLED", security_payload.get("safe_shell_enabled")),
        default=False,
    )

    return RpiEndpointConfig(
        core_base_url=str(
            os.environ.get("MEETYOU_RPI_CORE_BASE_URL")
            or os.environ.get("MEETYOU_CORE_BASE_URL")
            or payload.get("core_base_url")
            or "http://127.0.0.1:8000"
        ).strip(),
        endpoint_id=str(
            os.environ.get("MEETYOU_RPI_ENDPOINT_ID")
            or payload.get("endpoint_id")
            or "raspberry-pi-dev"
        ).strip(),
        endpoint_name=str(
            os.environ.get("MEETYOU_RPI_ENDPOINT_NAME")
            or payload.get("endpoint_name")
            or "Raspberry Pi Dev Endpoint"
        ).strip(),
        endpoint_token_env=endpoint_token_env,
        connect_path=str(payload.get("connect_path") or "/endpoint/ws").strip() or "/endpoint/ws",
        workspace_ids=_string_list(payload.get("workspace_ids"), ["personal"]),
        provider_type=str(payload.get("provider_type") or "rpi").strip() or "rpi",
        transport_profile=str(payload.get("transport_profile") or "rpi_wss").strip() or "rpi_wss",
        supports_markdown=_to_bool(payload.get("supports_markdown"), default=True),
        supports_offline_cache=_to_bool(payload.get("supports_offline_cache"), default=False),
        max_parallel_calls=_to_int(payload.get("max_parallel_calls"), 2, minimum=1, maximum=4),
        reconnect=ReconnectConfig(
            initial_delay_seconds=_to_float(reconnect_payload.get("initial_delay_seconds"), 1.0, minimum=0.1),
            max_delay_seconds=_to_float(reconnect_payload.get("max_delay_seconds"), 30.0, minimum=1.0),
            jitter_seconds=_to_float(reconnect_payload.get("jitter_seconds"), 1.0, minimum=0.0),
        ),
        keepalive=KeepaliveConfig(
            interval_seconds=_to_int(keepalive_payload.get("interval_seconds"), 20, minimum=3),
            timeout_seconds=_to_int(keepalive_payload.get("timeout_seconds"), 10, minimum=1),
        ),
        operation=OperationConfig(
            default_timeout_seconds=default_timeout,
            max_timeout_seconds=max_timeout,
        ),
        security=SecurityConfig(
            sandbox_dir=str(security_payload.get("sandbox_dir") or "/var/lib/meetyou-rpi/sandbox").strip(),
            safe_shell_enabled=safe_shell_enabled,
            safe_shell_allowlist=list(security_payload.get("safe_shell_allowlist") or []),
            gpio_allowed_pins=_int_list(security_payload.get("gpio_allowed_pins"), [17, 27, 22]),
            gpio_write_default_duration_ms=_to_int(
                security_payload.get("gpio_write_default_duration_ms"),
                500,
                minimum=0,
                maximum=60_000,
            ),
        ),
        core_access_token=_resolve_token(payload, endpoint_token_env),
        config_file_path=str(file_path),
    )

