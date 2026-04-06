from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable


def atomic_write_text(file_path: str, text: str, *, backup_suffix: str = ".bak") -> None:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = path.with_name(f"{path.name}{backup_suffix}")
    descriptor, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        shutil.copy2(path, backup_path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def atomic_write_json(file_path: str, payload: Any, *, backup_suffix: str = ".bak") -> None:
    atomic_write_text(
        file_path,
        json.dumps(payload, ensure_ascii=False, indent=2),
        backup_suffix=backup_suffix,
    )


def load_json_with_recovery(
    file_path: str,
    *,
    validator: Callable[[Any], bool] | None = None,
    default_factory: Callable[[], Any] | None = None,
    backup_suffix: str = ".bak",
) -> Any:
    path = Path(file_path)
    backup_path = path.with_name(f"{path.name}{backup_suffix}")
    failure_reasons: list[str] = []
    for candidate in (path, backup_path):
        if not candidate.exists():
            continue
        try:
            raw = candidate.read_text(encoding="utf-8").strip()
            if not raw:
                raise ValueError("empty file")
            payload = json.loads(raw)
            if validator is not None and not validator(payload):
                raise ValueError("invalid payload")
        except Exception as exc:
            failure_reasons.append(f"{candidate.name}: {exc}")
            continue
        if candidate != path:
            atomic_write_json(str(path), payload, backup_suffix=backup_suffix)
        return payload
    if default_factory is not None:
        return default_factory()
    reason = "; ".join(failure_reasons) or f"{file_path}: missing file"
    raise ValueError(reason)
