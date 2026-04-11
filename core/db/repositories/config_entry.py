from __future__ import annotations

from core.db.models.config_entry import ConfigEntry
from core.db.repositories.base import RepositoryBase


class ConfigEntryRepository(RepositoryBase):
    def delete_all(self) -> None:
        self.session.query(ConfigEntry).delete()
        self.session.flush()

    def upsert(
        self,
        *,
        config_key: str,
        value_json,
        is_secret: bool,
        has_value: bool,
        source: str,
        env_key: str | None,
        meta: dict | None = None,
    ) -> ConfigEntry:
        entry = self.session.query(ConfigEntry).filter_by(config_key=config_key).one_or_none()
        if entry is None:
            entry = ConfigEntry(config_key=config_key)
            self.session.add(entry)
        entry.value_json = value_json
        entry.is_secret = is_secret
        entry.has_value = has_value
        entry.source = source
        entry.env_key = env_key
        entry.meta = dict(meta or {})
        self.session.flush()
        return entry

    def list_all(self) -> list[ConfigEntry]:
        return list(self.session.query(ConfigEntry).order_by(ConfigEntry.config_key).all())

    def get_by_key(self, config_key: str) -> ConfigEntry | None:
        return self.session.query(ConfigEntry).filter_by(config_key=config_key).one_or_none()
