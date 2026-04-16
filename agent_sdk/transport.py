from __future__ import annotations

from typing import Any

import aiohttp


def build_agent_auth_headers(access_token: str = "") -> dict[str, str]:
    normalized_token = str(access_token or "").strip()
    if not normalized_token:
        return {}
    return {"Authorization": f"Bearer {normalized_token}"}


def build_agent_ws_timeout(*, connect_seconds: int = 15, total: Any = None) -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(total=total, connect=max(1, int(connect_seconds)))


def normalize_heartbeat_interval(interval: int, *, minimum_seconds: int = 1) -> int:
    return max(int(minimum_seconds), int(interval))
