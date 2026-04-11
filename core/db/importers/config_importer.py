from __future__ import annotations

from core.config import ConfigManager


def import_config_state(config: ConfigManager, services) -> int:
    snapshot = config.snapshot()
    payloads: list[dict] = []
    for key, described in snapshot.items():
        payloads.append(
            {
                "config_key": key,
                "value_json": config.get(key),
                "is_secret": bool(described.get("is_secret")),
                "has_value": bool(described.get("has_value")),
                "source": str(described.get("source") or "default"),
                "env_key": described.get("env_key"),
                "meta": {"imported_from": "config_manager_snapshot"},
            }
        )
    return services.config_state.replace_entries(payloads)
