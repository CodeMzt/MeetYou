from __future__ import annotations

import copy


class RuntimeStateBlobBackend:
    def __init__(self, service, *, principal_id, state_key: str, default_factory):
        self._service = service
        self._principal_id = principal_id
        self._state_key = state_key
        self._default_factory = default_factory

    def load(self):
        payload = self._service.load_state(
            principal_id=self._principal_id,
            state_key=self._state_key,
            default_factory=self._default_factory,
        )
        return copy.deepcopy(payload)

    def save(self, payload):
        self._service.save_state(
            principal_id=self._principal_id,
            state_key=self._state_key,
            payload=copy.deepcopy(payload),
            meta={"source": "runtime"},
        )
