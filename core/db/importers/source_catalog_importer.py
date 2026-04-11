from __future__ import annotations

from core.source_catalog import SOURCE_CATALOG_STATE_KEY, SourceCatalogManager


class _StaticConfig:
    def __init__(self, values: dict[str, object] | None = None):
        self._values = values or {}

    def get(self, key: str, default=None):
        return self._values.get(key, default)


def import_source_catalog_state(source_catalog_path: str, *, principal_id, services) -> int:
    manager = SourceCatalogManager(_StaticConfig({"source_catalog_path": source_catalog_path}))
    status = manager.get_catalog_status()
    if not bool(status.get("available")):
        return 0
    catalog = manager.get_catalog_snapshot()
    services.state_blob.save_state(
        principal_id=principal_id,
        state_key=SOURCE_CATALOG_STATE_KEY,
        payload=catalog,
        meta={"imported_from": source_catalog_path, "source": "file_import"},
    )
    return len(catalog.get("sources", []))
