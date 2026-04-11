from __future__ import annotations

import copy

from core.db.repositories import RuntimeStateBlobRepository
from core.services.base import ServiceBase


class RuntimeStateBlobService(ServiceBase):
    def load_state(self, *, principal_id, state_key: str, default_factory):
        with self.session_scope() as session:
            row = RuntimeStateBlobRepository(session).get(principal_id=principal_id, state_key=state_key)
            if row is None:
                return default_factory()
            return copy.deepcopy(dict(row.payload_json or {}))

    def save_state(self, *, principal_id, state_key: str, payload: dict, meta: dict | None = None):
        with self.session_scope() as session:
            return RuntimeStateBlobRepository(session).upsert(
                principal_id=principal_id,
                state_key=state_key,
                payload_json=dict(payload or {}),
                meta=meta,
            )
