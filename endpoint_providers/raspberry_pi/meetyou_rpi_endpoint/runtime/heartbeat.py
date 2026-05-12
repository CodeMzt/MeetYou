from __future__ import annotations

from typing import Any


def build_heartbeat_metrics(*, active_calls: int, capability_count: int) -> dict[str, Any]:
    return {
        "active_calls": max(0, int(active_calls)),
        "capability_count": max(0, int(capability_count)),
    }

