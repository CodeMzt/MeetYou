from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core.exceptions import ConfigError
from core.http_headers import build_attachment_content_disposition


@dataclass(slots=True)
class StoredObject:
    object_key: str
    size_bytes: int


@dataclass(slots=True)
class ObjectStoreSettings:
    backend: str = "local"
    root: Path = Path("user") / "attachments"
    endpoint: str = ""
    bucket: str = ""
    region: str = ""
    access_key: str = ""
    secret_key: str = ""


class ObjectStoreBackend(Protocol):
    def put_bytes(self, object_key: str, content: bytes) -> StoredObject: ...

    def read_bytes(self, object_key: str) -> bytes: ...

    def delete_object(self, object_key: str) -> None: ...

    def generate_presigned_download_url(
        self,
        object_key: str,
        *,
        expires_in_seconds: int,
        file_name: str = "",
        mime_type: str = "",
    ) -> str: ...


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        return self._root

    @staticmethod
    def _path_from_normalized_key(normalized: str) -> Path:
        parts = [part for part in str(normalized or "").split("/") if part]
        return Path(*parts) if parts else Path("")

    @staticmethod
    def _to_relative_path(object_key: str) -> Path:
        normalized = str(object_key or "").strip().replace("\\", "/").lstrip("/")
        if normalized.startswith("attachments/"):
            normalized = normalized[len("attachments/") :]
        return LocalObjectStore._path_from_normalized_key(normalized)

    @staticmethod
    def _to_legacy_relative_path(object_key: str) -> Path:
        normalized = str(object_key or "").strip().replace("\\", "/").lstrip("/")
        return LocalObjectStore._path_from_normalized_key(normalized)

    def _resolve_existing_path(self, object_key: str) -> Path:
        primary = self.root / self._to_relative_path(object_key)
        if primary.exists():
            return primary
        legacy = self.root / self._to_legacy_relative_path(object_key)
        if legacy.exists():
            return legacy
        raise FileNotFoundError(object_key)

    def put_bytes(self, object_key: str, content: bytes) -> StoredObject:
        target = self.root / self._to_relative_path(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return StoredObject(object_key=object_key, size_bytes=len(content))

    def resolve_path(self, object_key: str) -> Path:
        return self._resolve_existing_path(object_key)

    def read_bytes(self, object_key: str) -> bytes:
        return self.resolve_path(object_key).read_bytes()

    def delete_object(self, object_key: str) -> None:
        try:
            target = self._resolve_existing_path(object_key)
        except FileNotFoundError:
            return
        target.unlink()

    def generate_presigned_download_url(
        self,
        object_key: str,
        *,
        expires_in_seconds: int,
        file_name: str = "",
        mime_type: str = "",
    ) -> str:
        del object_key, expires_in_seconds, file_name, mime_type
        return ""


class S3CompatibleObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint: str = "",
        region: str = "",
        access_key: str = "",
        secret_key: str = "",
        client=None,
    ) -> None:
        self._bucket = str(bucket or "").strip()
        self._endpoint = str(endpoint or "").strip()
        self._region = str(region or "").strip()
        self._access_key = str(access_key or "").strip()
        self._secret_key = str(secret_key or "").strip()
        self._client = client
        if not self._bucket:
            raise ConfigError("object_store_bucket 为必填，当前 backend=s3_compatible。")

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - depends on optional dependency
                raise ConfigError("当前 backend=s3_compatible，但未安装 boto3。") from exc

            client_kwargs: dict[str, Any] = {}
            if self._endpoint:
                client_kwargs["endpoint_url"] = self._endpoint
            if self._region:
                client_kwargs["region_name"] = self._region
            if self._access_key:
                client_kwargs["aws_access_key_id"] = self._access_key
            if self._secret_key:
                client_kwargs["aws_secret_access_key"] = self._secret_key
            self._client = boto3.client("s3", **client_kwargs)
        return self._client

    def put_bytes(self, object_key: str, content: bytes) -> StoredObject:
        self.client.put_object(Bucket=self._bucket, Key=object_key, Body=content)
        return StoredObject(object_key=object_key, size_bytes=len(content))

    def read_bytes(self, object_key: str) -> bytes:
        response = self.client.get_object(Bucket=self._bucket, Key=object_key)
        return bytes(response["Body"].read())

    def delete_object(self, object_key: str) -> None:
        self.client.delete_object(Bucket=self._bucket, Key=object_key)

    def generate_presigned_download_url(
        self,
        object_key: str,
        *,
        expires_in_seconds: int,
        file_name: str = "",
        mime_type: str = "",
    ) -> str:
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": object_key,
        }
        if mime_type:
            params["ResponseContentType"] = mime_type
        normalized_name = str(file_name or "").strip().replace('"', "")
        if normalized_name:
            params["ResponseContentDisposition"] = build_attachment_content_disposition(normalized_name)
        return str(
            self.client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=max(int(expires_in_seconds or 0), 60),
            )
        )


def resolve_object_store_settings(config: Any | None, *, storage_root_override: Path | None = None) -> ObjectStoreSettings:
    backend = "local"
    endpoint = ""
    bucket = ""
    region = ""
    access_key = ""
    secret_key = ""
    root = Path(storage_root_override or Path("user") / "attachments")
    if config is not None:
        getter = getattr(config, "get", None)
        if callable(getter):
            backend = str(getter("object_store_backend", backend) or backend).strip().lower() or "local"
            endpoint = str(getter("object_store_endpoint", "") or "").strip()
            bucket = str(getter("object_store_bucket", "") or "").strip()
            region = str(getter("object_store_region", "") or "").strip()
            access_key = str(getter("object_store_access_key", "") or "").strip()
            secret_key = str(getter("object_store_secret_key", "") or "").strip()
            configured_root = str(getter("attachment_storage_root", "") or "").strip()
            if storage_root_override is None and configured_root:
                root = Path(configured_root)
    return ObjectStoreSettings(
        backend=backend,
        root=root,
        endpoint=endpoint,
        bucket=bucket,
        region=region,
        access_key=access_key,
        secret_key=secret_key,
    )


def build_object_store(config: Any | None = None, *, storage_root_override: Path | None = None):
    settings = resolve_object_store_settings(config, storage_root_override=storage_root_override)
    if settings.backend in {"local", "filesystem"}:
        return LocalObjectStore(settings.root)
    if settings.backend in {"s3", "s3_compatible", "minio"}:
        return S3CompatibleObjectStore(
            bucket=settings.bucket,
            endpoint=settings.endpoint,
            region=settings.region,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
        )
    raise ConfigError(
        f"当前 object_store_backend={settings.backend!r} 尚未实现。"
        "当前仅支持 local/filesystem/s3_compatible。"
    )
