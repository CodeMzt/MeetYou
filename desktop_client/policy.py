from __future__ import annotations

import json
from pathlib import Path

from desktop_client.config import DesktopClientConfig
from tools.command_policy import assess_command_safety as assess_shared_command_safety


class DesktopClientPolicyError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def is_path_allowed(target: Path, roots: list[Path]) -> bool:
    resolved_target = target.resolve()
    for root in roots:
        try:
            resolved_target.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def ensure_readable_path(config: DesktopClientConfig, raw_path: str) -> Path:
    target = (config.workspace_root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
    if not is_path_allowed(target, config.resolved_read_roots):
        raise DesktopClientPolicyError("path_not_allowed", f"Requested path is outside allowed read roots: {target}")
    if not target.exists() or not target.is_file():
        raise DesktopClientPolicyError("file_not_found", f"Requested file does not exist: {target}")
    return target


def ensure_workspace_path(config: DesktopClientConfig, raw_path: str) -> Path:
    target = (config.workspace_root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
    if not is_path_allowed(target, config.resolved_read_roots):
        raise DesktopClientPolicyError("path_not_allowed", f"Requested path is outside allowed read roots: {target}")
    if not target.exists() or not target.is_dir():
        raise DesktopClientPolicyError("directory_not_found", f"Requested directory does not exist: {target}")
    return target


def ensure_writable_path(config: DesktopClientConfig, raw_path: str) -> Path:
    target = (config.workspace_root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
    if not is_path_allowed(target, config.resolved_write_roots):
        raise DesktopClientPolicyError("path_not_allowed", f"Requested path is outside trusted write roots: {target}")
    return target


def load_cmd_policy(config: DesktopClientConfig) -> dict:
    path = config.resolved_cmd_policy_path
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"mode": "none"}
    except json.JSONDecodeError:
        return {"mode": "none"}


def assess_command_safety(command: str, *, policy: dict) -> tuple[str, str]:
    return assess_shared_command_safety(
        command,
        policy=policy,
        blacklist_match_status="blocked",
        enforce_hard_guards=False,
        whitelist_requires_boundary=False,
    )
