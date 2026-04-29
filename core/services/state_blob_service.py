from __future__ import annotations

import copy

from core.db.repositories import RuntimeStateBlobRepository
from core.services.base import ServiceBase


class RuntimeStateBlobService(ServiceBase):
    @staticmethod
    def namespaced_key(*, namespace: str, key: str) -> str:
        normalized_namespace = str(namespace or "").strip()
        normalized_key = str(key or "").strip()
        if not normalized_key:
            raise ValueError("state key is required")
        state_key = f"{normalized_namespace}:{normalized_key}" if normalized_namespace else normalized_key
        if len(state_key) > 64:
            raise ValueError("state key must be 64 characters or fewer")
        return state_key

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

    def load_namespaced_state(self, *, principal_id, namespace: str, key: str, default_factory):
        return self.load_state(
            principal_id=principal_id,
            state_key=self.namespaced_key(namespace=namespace, key=key),
            default_factory=default_factory,
        )

    def save_namespaced_state(self, *, principal_id, namespace: str, key: str, payload: dict, meta: dict | None = None):
        merged_meta = {"namespace": str(namespace or "").strip(), "key": str(key or "").strip(), **dict(meta or {})}
        return self.save_state(
            principal_id=principal_id,
            state_key=self.namespaced_key(namespace=namespace, key=key),
            payload=payload,
            meta=merged_meta,
        )
