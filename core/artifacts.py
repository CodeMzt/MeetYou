from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(slots=True)
class StoredArtifact:
    storage_backend: str
    storage_key: str
    path: Path
    filename: str
    content_type: str
    byte_size: int
    checksum: str


class LocalArtifactStore:
    backend_name = "local"

    def __init__(self, root: str | Path = "user/artifacts") -> None:
        self.root = Path(root)

    @staticmethod
    def safe_filename(filename: str, *, default: str = "artifact.md") -> str:
        raw = str(filename or "").strip() or default
        name = _SAFE_NAME_RE.sub("_", raw).strip("._")
        return name or default

    def put_bytes(self, *, artifact_id: str, data: bytes, filename: str, content_type: str = "") -> StoredArtifact:
        normalized_id = str(artifact_id or "").strip()
        if not normalized_id:
            raise ValueError("artifact_id is required")
        safe_name = self.safe_filename(filename)
        target_dir = self.root / normalized_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / safe_name
        target_path.write_bytes(data)
        checksum = hashlib.sha256(data).hexdigest()
        resolved_content_type = content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        return StoredArtifact(
            storage_backend=self.backend_name,
            storage_key=f"{normalized_id}/{safe_name}",
            path=target_path,
            filename=safe_name,
            content_type=resolved_content_type,
            byte_size=len(data),
            checksum=checksum,
        )

    def put_text(self, *, artifact_id: str, text: str, filename: str, content_type: str = "text/markdown; charset=utf-8") -> StoredArtifact:
        return self.put_bytes(
            artifact_id=artifact_id,
            data=str(text or "").encode("utf-8"),
            filename=filename,
            content_type=content_type,
        )

    def resolve_path(self, storage_key: str) -> Path:
        normalized = str(storage_key or "").strip().replace("\\", "/")
        if not normalized or normalized.startswith("/") or ".." in Path(normalized).parts:
            raise ValueError("invalid artifact storage key")
        target = (self.root / normalized).resolve()
        root = self.root.resolve()
        if target != root and root not in target.parents:
            raise ValueError("artifact path escapes store root")
        return target
