from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CONFIG_PATH = Path("user") / "desktop_client.json"
DEFAULT_LOCAL_BRIDGE_HOST = "127.0.0.1"
DEFAULT_LOCAL_BRIDGE_PORT = 38951
DEFAULT_ENV_PATH = Path(".env")


def _default_client_id() -> str:
    return f"{socket.gethostname().lower()}-desktop-client"


def _default_display_name() -> str:
    return f"{socket.gethostname()} Desktop Client"


@dataclass(slots=True)
class DesktopClientConfig:
    core_base_url: str = "http://127.0.0.1:8000"
    core_access_token: str = ""
    gateway_access_token: str = ""
    client_id: str = field(default_factory=_default_client_id)
    display_name: str = field(default_factory=_default_display_name)
    workspace_ids: list[str] = field(default_factory=lambda: ["personal", "desktop-main", "study"])
    enabled_endpoint_tools: list[str] = field(default_factory=list)
    read_roots: list[str] = field(default_factory=lambda: ["."])
    trusted_write_roots: list[str] = field(default_factory=lambda: ["."])
    cmd_policy_path: str = "user/cmd_policy.json"
    mcp_servers_path: str = "user/mcp_servers.json"
    command_timeout_seconds: int = 120
    max_parallel_calls: int = 2
    heartbeat_interval_seconds: int = 20
    reconnect_delay_seconds: int = 3
    supports_offline_cache: bool = True
    transport_profile: str = "desktop_wss"
    local_bridge_enabled: bool = True
    local_bridge_host: str = DEFAULT_LOCAL_BRIDGE_HOST
    local_bridge_port: int = DEFAULT_LOCAL_BRIDGE_PORT
    local_bridge_access_token: str = ""
    config_file_path: str = str(DEFAULT_CONFIG_PATH)

    @property
    def websocket_url(self) -> str:
        return f"{self.core_base_url.rstrip('/').replace('http://', 'ws://').replace('https://', 'wss://')}/endpoint/ws"

    @property
    def workspace_root(self) -> Path:
        return Path.cwd().resolve()

    @property
    def local_bridge_base_url(self) -> str:
        return f"http://{self.local_bridge_host}:{self.local_bridge_port}"

    @property
    def resolved_read_roots(self) -> list[Path]:
        return [_resolve_local_path(self.workspace_root, item) for item in self.read_roots]

    @property
    def resolved_write_roots(self) -> list[Path]:
        return [_resolve_local_path(self.workspace_root, item) for item in self.trusted_write_roots]

    @property
    def resolved_cmd_policy_path(self) -> Path:
        return _resolve_local_path(self.workspace_root, self.cmd_policy_path)

    @property
    def resolved_mcp_servers_path(self) -> Path:
        return _resolve_local_path(self.workspace_root, self.mcp_servers_path)


def _resolve_local_path(root: Path, value: str) -> Path:
    candidate = Path(str(value or ".")).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (root / candidate).resolve()


def _to_bool(value: object, *, default: bool) -> bool:
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


def _string_list(payload: dict[str, object], key: str, default: list[str]) -> list[str]:
    values = payload.get(key)
    if not isinstance(values, list):
        values = default
    return [str(item).strip() for item in values if str(item).strip()]


def _load_env_file(env_file_path: Path = DEFAULT_ENV_PATH) -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file_path, override=False)
    except ImportError:
        return


def _resolve_core_access_token(payload: dict[str, object]) -> str:
    return str(
        os.environ.get("MEETYOU_CLIENT_ACCESS_TOKEN")
        or os.environ.get("MEETYOU_GATEWAY_ACCESS_TOKEN")
        or payload.get("core_access_token")
        or payload.get("gateway_access_token")
        or ""
    ).strip()


def load_desktop_client_config(config_file_path: str | None = None) -> DesktopClientConfig:
    requested_path = config_file_path or os.environ.get("MEETYOU_DESKTOP_CLIENT_CONFIG") or DEFAULT_CONFIG_PATH
    file_path = Path(requested_path)
    env_root = file_path.parent.parent if file_path.parent.name == "user" else file_path.parent
    _load_env_file(env_root / DEFAULT_ENV_PATH)
    payload: dict[str, object] = {}
    if file_path.exists():
        payload = json.loads(file_path.read_text(encoding="utf-8-sig"))

    workspace_ids = payload.get("workspace_ids") if isinstance(payload.get("workspace_ids"), list) else None
    env_workspace_ids = os.environ.get("MEETYOU_CLIENT_WORKSPACES", "").strip()

    return DesktopClientConfig(
        core_base_url=str(os.environ.get("MEETYOU_CORE_BASE_URL") or payload.get("core_base_url") or "http://127.0.0.1:8000").strip(),
        core_access_token=_resolve_core_access_token(payload),
        gateway_access_token=str(
            os.environ.get("MEETYOU_GATEWAY_ACCESS_TOKEN")
            or payload.get("gateway_access_token")
            or ""
        ).strip(),
        client_id=str(os.environ.get("MEETYOU_CLIENT_ID") or payload.get("client_id") or _default_client_id()).strip(),
        display_name=str(os.environ.get("MEETYOU_CLIENT_DISPLAY_NAME") or payload.get("display_name") or _default_display_name()).strip(),
        workspace_ids=[item for item in (env_workspace_ids.split(",") if env_workspace_ids else workspace_ids or ["personal", "desktop-main", "study"]) if str(item).strip()],
        enabled_endpoint_tools=_string_list(payload, "enabled_endpoint_tools", []),
        read_roots=[str(item) for item in (payload.get("read_roots") if isinstance(payload.get("read_roots"), list) else ["."])],
        trusted_write_roots=[str(item) for item in (payload.get("trusted_write_roots") if isinstance(payload.get("trusted_write_roots"), list) else ["."])],
        cmd_policy_path=str(payload.get("cmd_policy_path") or "user/cmd_policy.json"),
        mcp_servers_path=str(payload.get("mcp_servers_path") or "user/mcp_servers.json"),
        command_timeout_seconds=int(payload.get("command_timeout_seconds") or 120),
        max_parallel_calls=max(
            1,
            min(
                int(os.environ.get("MEETYOU_CLIENT_MAX_PARALLEL_CALLS") or payload.get("max_parallel_calls") or 2),
                4,
            ),
        ),
        heartbeat_interval_seconds=int(os.environ.get("MEETYOU_CLIENT_HEARTBEAT_SECONDS") or payload.get("heartbeat_interval_seconds") or 20),
        reconnect_delay_seconds=int(os.environ.get("MEETYOU_CLIENT_RECONNECT_SECONDS") or payload.get("reconnect_delay_seconds") or 3),
        supports_offline_cache=bool(payload.get("supports_offline_cache", True)),
        transport_profile=str(payload.get("transport_profile") or "desktop_wss"),
        local_bridge_enabled=_to_bool(
            os.environ.get("MEETYOU_DESKTOP_LOCAL_BRIDGE_ENABLED", payload.get("local_bridge_enabled")),
            default=True,
        ),
        local_bridge_host=str(
            os.environ.get("MEETYOU_DESKTOP_LOCAL_HOST")
            or payload.get("local_bridge_host")
            or DEFAULT_LOCAL_BRIDGE_HOST
        ).strip()
        or DEFAULT_LOCAL_BRIDGE_HOST,
        local_bridge_port=int(
            os.environ.get("MEETYOU_DESKTOP_LOCAL_PORT")
            or payload.get("local_bridge_port")
            or DEFAULT_LOCAL_BRIDGE_PORT
        ),
        local_bridge_access_token=str(
            os.environ.get("MEETYOU_DESKTOP_LOCAL_TOKEN")
            or payload.get("local_bridge_access_token")
            or ""
        ).strip(),
        config_file_path=str(file_path),
    )
