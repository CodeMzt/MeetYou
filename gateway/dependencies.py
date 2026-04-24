from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class GatewayDependencies:
    event_bus: Any
    session_manager: Any
    interaction_response_service: Any = None
    core_domain: Any = None
    config_snapshot_getter: Any = None
    config_item_getter: Any = None
    config_updater: Any = None
    memory_snapshot_getter: Any = None
    memory_graph_getter: Any = None
    memory_clearer: Any = None
    memory_record_status_updater: Any = None
    memory_record_deleter: Any = None
    runtime_state_getter: Any = None
    runtime_usage_getter: Any = None
    runtime_debug_getter: Any = None
    health_getter: Any = None
