from __future__ import annotations

from core.db.repositories import ConfigEntryRepository
from core.services.base import ServiceBase


class ConfigStateService(ServiceBase):
    def replace_entries(self, entries: list[dict]) -> int:
        with self.session_scope() as session:
            repo = ConfigEntryRepository(session)
            repo.delete_all()
            for entry in entries:
                repo.upsert(**entry)
            return len(entries)

    def list_entries(self):
        with self.session_scope() as session:
            return ConfigEntryRepository(session).list_all()

    def get_snapshot_view(self) -> dict[str, dict]:
        items = {}
        for entry in self.list_entries():
            items[entry.config_key] = {
                "key": entry.config_key,
                "value": entry.value_json,
                "is_secret": bool(entry.is_secret),
                "has_value": bool(entry.has_value),
                "source": entry.source,
                "env_key": entry.env_key,
            }
        return items

    def get_entry_view(self, key: str) -> dict | None:
        with self.session_scope() as session:
            entry = ConfigEntryRepository(session).get_by_key(key)
            if entry is None:
                return None
            return {
                "key": entry.config_key,
                "value": entry.value_json,
                "is_secret": bool(entry.is_secret),
                "has_value": bool(entry.has_value),
                "source": entry.source,
                "env_key": entry.env_key,
            }
