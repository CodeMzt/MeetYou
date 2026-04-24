from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class BuildInfo:
    git_commit: str
    branch: str
    build_time: str
    component: str
    package_version: str

    def to_dict(self) -> dict[str, str]:
        return {
            "git_commit": self.git_commit,
            "branch": self.branch,
            "build_time": self.build_time,
            "component": self.component,
            "package_version": self.package_version,
        }


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    try:
        output = subprocess.check_output(["git", *args], cwd=str(cwd) if cwd else None, stderr=subprocess.DEVNULL)
    except Exception:
        return ""
    return output.decode("utf-8", errors="ignore").strip()


def infer_git_commit(cwd: Path | None = None) -> str:
    return _run_git(["rev-parse", "HEAD"], cwd=cwd) or "unknown"


def infer_git_branch(cwd: Path | None = None) -> str:
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    return branch or "unknown"


def resolve_build_info(
    *,
    component: str,
    package_version: str,
    build_time: str | None = None,
    git_commit: str | None = None,
    branch: str | None = None,
    cwd: Path | None = None,
) -> dict[str, str]:
    info = BuildInfo(
        git_commit=str(git_commit or infer_git_commit(cwd) or "unknown").strip() or "unknown",
        branch=str(branch or infer_git_branch(cwd) or "unknown").strip() or "unknown",
        build_time=str(build_time or _utcnow_iso()).strip() or _utcnow_iso(),
        component=str(component or "unknown").strip() or "unknown",
        package_version=str(package_version or "0.0.0").strip() or "0.0.0",
    )
    return info.to_dict()


def load_build_info(
    file_path: str | Path,
    *,
    component: str,
    package_version: str,
) -> dict[str, str]:
    path = Path(file_path)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            return {
                "git_commit": str(payload.get("git_commit") or "unknown"),
                "branch": str(payload.get("branch") or "unknown"),
                "build_time": str(payload.get("build_time") or _utcnow_iso()),
                "component": str(payload.get("component") or component),
                "package_version": str(payload.get("package_version") or package_version),
            }
    return resolve_build_info(component=component, package_version=package_version, cwd=path.parent)


def write_build_info(file_path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {
        "git_commit": str(payload.get("git_commit") or "unknown"),
        "branch": str(payload.get("branch") or "unknown"),
        "build_time": str(payload.get("build_time") or _utcnow_iso()),
        "component": str(payload.get("component") or "unknown"),
        "package_version": str(payload.get("package_version") or "0.0.0"),
    }
    path.write_text(f"{json.dumps(clean, ensure_ascii=False, indent=2)}\n", encoding="utf-8")


def package_version_from_env(key: str, fallback: str) -> str:
    return str(os.getenv(key) or os.getenv("MEETYOU_PACKAGE_VERSION") or fallback or "0.0.0").strip() or "0.0.0"
