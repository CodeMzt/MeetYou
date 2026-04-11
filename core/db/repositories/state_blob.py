from __future__ import annotations

from core.db.models.state_blob import RuntimeStateBlob
from core.db.repositories.base import RepositoryBase


class RuntimeStateBlobRepository(RepositoryBase):
    def get(self, *, principal_id, state_key: str) -> RuntimeStateBlob | None:
        return self.session.query(RuntimeStateBlob).filter_by(principal_id=principal_id, state_key=state_key).one_or_none()

    def upsert(self, *, principal_id, state_key: str, payload_json: dict, meta: dict | None = None) -> RuntimeStateBlob:
        row = self.get(principal_id=principal_id, state_key=state_key)
        if row is None:
            row = RuntimeStateBlob(principal_id=principal_id, state_key=state_key)
            self.session.add(row)
        row.payload_json = dict(payload_json or {})
        row.meta = dict(meta or {})
        self.session.flush()
        return row
