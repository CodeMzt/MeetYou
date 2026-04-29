from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Callable, Protocol


class RuntimeStateStoreBackend(Protocol):
    def load(self, *, namespace: str, key: str, default_factory: Callable[[], dict]):
        ...

    def save(self, *, namespace: str, key: str, payload: dict, meta: dict | None = None):
        ...


def _copy_payload(payload):
    return copy.deepcopy(dict(payload or {}))


def _safe_file_part(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return normalized.strip("._") or "default"


class DatabaseRuntimeStateStoreBackend:
    def __init__(self, service, *, principal_id):
        self._service = service
        self._principal_id = principal_id

    def load(self, *, namespace: str, key: str, default_factory: Callable[[], dict]):
        loader = getattr(self._service, "load_namespaced_state", None)
        if callable(loader):
            payload = loader(
                principal_id=self._principal_id,
                namespace=namespace,
                key=key,
                default_factory=default_factory,
            )
        else:
            state_key = f"{namespace}:{key}" if namespace else key
            payload = self._service.load_state(
                principal_id=self._principal_id,
                state_key=state_key,
                default_factory=default_factory,
            )
        return _copy_payload(payload)

    def save(self, *, namespace: str, key: str, payload: dict, meta: dict | None = None):
        saver = getattr(self._service, "save_namespaced_state", None)
        if callable(saver):
            return saver(
                principal_id=self._principal_id,
                namespace=namespace,
                key=key,
                payload=_copy_payload(payload),
                meta=meta,
            )
        state_key = f"{namespace}:{key}" if namespace else key
        return self._service.save_state(
            principal_id=self._principal_id,
            state_key=state_key,
            payload=_copy_payload(payload),
            meta={"namespace": namespace, "key": key, **dict(meta or {})},
        )


class FileRuntimeStateStoreBackend:
    def __init__(self, root_dir):
        self._root_dir = Path(root_dir)

    def _path(self, *, namespace: str, key: str) -> Path:
        return self._root_dir / _safe_file_part(namespace) / f"{_safe_file_part(key)}.json"

    def load(self, *, namespace: str, key: str, default_factory: Callable[[], dict]):
        path = self._path(namespace=namespace, key=key)
        if not path.exists():
            return _copy_payload(default_factory())
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return _copy_payload(default_factory())
        return _copy_payload(data if isinstance(data, dict) else default_factory())

    def save(self, *, namespace: str, key: str, payload: dict, meta: dict | None = None):
        del meta
        path = self._path(namespace=namespace, key=key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(_copy_payload(payload), handle, ensure_ascii=False, indent=2, sort_keys=True)
        return path


class RuntimeStateStore:
    def __init__(self, backend: RuntimeStateStoreBackend, *, namespace: str):
        self._backend = backend
        self._namespace = str(namespace or "").strip()

    @property
    def namespace(self) -> str:
        return self._namespace

    def for_namespace(self, namespace: str) -> "RuntimeStateStore":
        return RuntimeStateStore(self._backend, namespace=namespace)

    def load(self, key: str, default_factory: Callable[[], dict] = dict):
        return self._backend.load(
            namespace=self._namespace,
            key=str(key or "").strip(),
            default_factory=default_factory,
        )

    def save(self, key: str, payload: dict, meta: dict | None = None):
        return self._backend.save(
            namespace=self._namespace,
            key=str(key or "").strip(),
            payload=_copy_payload(payload),
            meta=meta,
        )

    def blob_backend(self, key: str, default_factory: Callable[[], dict] = dict) -> "RuntimeStateStoreBlobBackend":
        return RuntimeStateStoreBlobBackend(self, key=key, default_factory=default_factory)


class RuntimeStateStoreBlobBackend:
    def __init__(self, store: RuntimeStateStore, *, key: str, default_factory):
        self._store = store
        self._key = str(key or "").strip()
        self._default_factory = default_factory

    def load(self):
        return self._store.load(self._key, self._default_factory)

    def save(self, payload):
        self._store.save(self._key, payload, meta={"source": "runtime"})


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
