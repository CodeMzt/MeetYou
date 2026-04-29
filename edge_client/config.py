from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CONFIG_PATH = Path("user") / "edge_client.json"
DEFAULT_ENV_PATH = Path(".env")


@dataclass(slots=True)
class EdgeClientConfig:
    core_base_url: str = "http://127.0.0.1:8000"
    core_access_token: str = ""
    provider_id: str = "edge-client"
    display_name: str = "Edge Endpoint Provider"
    provider_type: str = "edge"
    workspace_ids: list[str] = field(default_factory=lambda: ["home-lab"])
    enabled_endpoint_tools: list[str] = field(default_factory=list)
    heartbeat_interval_seconds: int = 20
    reconnect_delay_seconds: int = 3
    max_parallel_calls: int = 2
    supports_offline_cache: bool = False
    supports_markdown: bool = True
    transport_profile: str = "edge_wss"
    config_file_path: str = str(DEFAULT_CONFIG_PATH)

    @property
    def websocket_url(self) -> str:
        return f"{self.core_base_url.rstrip('/').replace('http://', 'ws://').replace('https://', 'wss://')}/endpoint/ws"


def _load_env_file(env_file_path: Path = DEFAULT_ENV_PATH) -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file_path, override=False)
    except ImportError:
        return


def _resolve_core_access_token(payload: dict[str, object]) -> str:
    return str(
        os.environ.get("MEETYOU_EDGE_CLIENT_ACCESS_TOKEN")
        or os.environ.get("MEETYOU_CLIENT_ACCESS_TOKEN")
        or os.environ.get("MEETYOU_GATEWAY_ACCESS_TOKEN")
        or payload.get("core_access_token")
        or ""
    ).strip()


def _string_list(payload: dict[str, object], key: str, default: list[str]) -> list[str]:
    values = payload.get(key)
    if not isinstance(values, list):
        values = default
    return [str(item).strip() for item in values if str(item).strip()]


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


def load_edge_client_config(config_file_path: str | None = None) -> EdgeClientConfig:
    file_path = Path(config_file_path or DEFAULT_CONFIG_PATH)
    env_root = file_path.parent.parent if file_path.parent.name == "user" else file_path.parent
    _load_env_file(env_root / DEFAULT_ENV_PATH)
    payload: dict[str, object] = {}
    if file_path.exists():
        payload = json.loads(file_path.read_text(encoding="utf-8"))

    return EdgeClientConfig(
        core_base_url=str(
            os.environ.get("MEETYOU_EDGE_BASE_URL")
            or os.environ.get("MEETYOU_CORE_BASE_URL")
            or payload.get("core_base_url")
            or "http://127.0.0.1:8000"
        ).strip(),
        core_access_token=_resolve_core_access_token(payload),
        provider_id=str(os.environ.get("MEETYOU_EDGE_PROVIDER_ID") or payload.get("provider_id") or "edge-client").strip(),
        display_name=str(os.environ.get("MEETYOU_EDGE_PROVIDER_DISPLAY_NAME") or payload.get("display_name") or "Edge Endpoint Provider").strip(),
        provider_type=str(os.environ.get("MEETYOU_EDGE_PROVIDER_TYPE") or payload.get("provider_type") or "edge").strip(),
        workspace_ids=[str(item).strip() for item in (payload.get("workspace_ids") if isinstance(payload.get("workspace_ids"), list) else ["home-lab"]) if str(item).strip()],
        enabled_endpoint_tools=_string_list(payload, "enabled_endpoint_tools", []),
        heartbeat_interval_seconds=max(int(os.environ.get("MEETYOU_EDGE_HEARTBEAT_SECONDS") or payload.get("heartbeat_interval_seconds") or 20), 1),
        reconnect_delay_seconds=max(int(os.environ.get("MEETYOU_EDGE_RECONNECT_SECONDS") or payload.get("reconnect_delay_seconds") or 3), 1),
        max_parallel_calls=max(
            1,
            min(
                int(os.environ.get("MEETYOU_EDGE_MAX_PARALLEL_CALLS") or os.environ.get("MEETYOU_ENDPOINT_MAX_PARALLEL_CALLS") or payload.get("max_parallel_calls") or 2),
                4,
            ),
        ),
        supports_offline_cache=bool(payload.get("supports_offline_cache", False)),
        supports_markdown=_to_bool(payload.get("supports_markdown"), default=True),
        transport_profile=str(payload.get("transport_profile") or "edge_wss"),
        config_file_path=str(file_path),
    )
