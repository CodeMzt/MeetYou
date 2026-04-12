from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CONFIG_PATH = Path("user") / "edge_agent.json"


@dataclass(slots=True)
class EdgeAgentConfig:
    core_base_url: str = "http://127.0.0.1:8000"
    agent_access_token: str = ""
    agent_id: str = "edge-agent"
    display_name: str = "Edge Agent"
    agent_type: str = "edge"
    workspace_ids: list[str] = field(default_factory=lambda: ["home-lab"])
    heartbeat_interval_seconds: int = 20
    reconnect_delay_seconds: int = 3
    supports_offline_cache: bool = False
    transport_profile: str = "edge_wss"
    config_file_path: str = str(DEFAULT_CONFIG_PATH)

    @property
    def websocket_url(self) -> str:
        return f"{self.core_base_url.rstrip('/').replace('http://', 'ws://').replace('https://', 'wss://')}/agent/ws"


def load_edge_agent_config(config_file_path: str | None = None) -> EdgeAgentConfig:
    file_path = Path(config_file_path or DEFAULT_CONFIG_PATH)
    payload: dict[str, object] = {}
    if file_path.exists():
        payload = json.loads(file_path.read_text(encoding="utf-8"))

    return EdgeAgentConfig(
        core_base_url=str(
            os.environ.get("MEETYOU_EDGE_BASE_URL")
            or os.environ.get("MEETYOU_AGENT_BASE_URL")
            or payload.get("core_base_url")
            or "http://127.0.0.1:8000"
        ).strip(),
        agent_access_token=str(
            os.environ.get("MEETYOU_EDGE_ACCESS_TOKEN")
            or os.environ.get("MEETYOU_AGENT_ACCESS_TOKEN")
            or os.environ.get("MEETYOU_GATEWAY_ACCESS_TOKEN")
            or payload.get("agent_access_token")
            or ""
        ).strip(),
        agent_id=str(os.environ.get("MEETYOU_EDGE_AGENT_ID") or payload.get("agent_id") or "edge-agent").strip(),
        display_name=str(os.environ.get("MEETYOU_EDGE_DISPLAY_NAME") or payload.get("display_name") or "Edge Agent").strip(),
        agent_type=str(os.environ.get("MEETYOU_EDGE_AGENT_TYPE") or payload.get("agent_type") or "edge").strip(),
        workspace_ids=[str(item).strip() for item in (payload.get("workspace_ids") if isinstance(payload.get("workspace_ids"), list) else ["home-lab"]) if str(item).strip()],
        heartbeat_interval_seconds=max(int(os.environ.get("MEETYOU_EDGE_HEARTBEAT_SECONDS") or payload.get("heartbeat_interval_seconds") or 20), 1),
        reconnect_delay_seconds=max(int(os.environ.get("MEETYOU_EDGE_RECONNECT_SECONDS") or payload.get("reconnect_delay_seconds") or 3), 1),
        supports_offline_cache=bool(payload.get("supports_offline_cache", False)),
        transport_profile=str(payload.get("transport_profile") or "edge_wss"),
        config_file_path=str(file_path),
    )
