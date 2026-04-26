from __future__ import annotations

import json
import re
from pathlib import Path

from desktop_client.config import DesktopClientConfig

_DEFAULT_BLACKLIST_PATTERNS = [
    r"(^|[;&|])\s*(rm|del|erase|rd|rmdir|Remove-Item)\b",
    r"(^|[;&|])\s*(shutdown|reboot|halt|poweroff|restart-computer|stop-computer)\b",
    r"\b(format|diskpart|mkfs(?:\.\w+)?|fdisk|parted|dd\s+if=|cipher\s+/w|sdelete)\b",
    r"(^|[;&|])\s*(reg(?:\.exe)?\s+(add|delete|import|load|unload)|regedit)\b",
    r"\b(bcdedit|bootrec|wevtutil\s+cl|vssadmin|wbadmin)\b",
    r"(^|[;&|])\s*(powershell(?:\.exe)?|pwsh)\b.*-(enc|encodedcommand|e)\b",
    r"\b(Invoke-Expression|iex|Set-ExecutionPolicy|Start-Process)\b",
    r"\b(curl|wget|Invoke-WebRequest|iwr)\b.*(\||&&|;).*\b(sh|bash|zsh|powershell|pwsh|cmd)(?:\.exe)?\b",
    r"(^|[;&|])\s*(net\s+(user|localgroup)|sc(?:\.exe)?\s+(config|create|delete|stop|start)|schtasks|crontab)\b",
    r"(^|[;&|])\s*(systemctl\s+(stop|disable|mask|reboot|poweroff)|service\s+\S+\s+(stop|restart))\b",
    r"(^|[;&|])\s*(taskkill|Stop-Process|pkill|killall|kill\s+-9)\b",
    r"\b(chmod\s+777|chown|takeown|icacls|attrib\s+[+-][rhs])\b",
    r"\b(netsh\b.*\badvfirewall\b|iptables|ufw|route\s+(add|delete|change))\b",
    r"\bgit\s+(reset\s+--hard|clean\s+-fdx|checkout\s+--)\b",
    r"\b(docker\s+(rm|rmi|system\s+prune|volume\s+rm)|kubectl\s+delete)\b",
]


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
    if not policy or policy.get("mode") == "none":
        return "safe", ""

    normalized_cmd = re.sub(r"\s+", " ", str(command or "").strip())
    cmd_lower = normalized_cmd.lower()
    mode = str(policy.get("mode") or "blacklist")

    if mode == "whitelist":
        whitelist = [str(item).strip().lower() for item in policy.get("whitelist", []) if str(item).strip()]
        if any(cmd_lower.startswith(item) for item in whitelist):
            return "safe", ""
        return "blocked", f"Command is not in whitelist: {normalized_cmd}"

    blacklist: list[str] = []
    seen: set[str] = set()
    for pattern in [*_DEFAULT_BLACKLIST_PATTERNS, *policy.get("blacklist_patterns", [])]:
        candidate = str(pattern).strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        blacklist.append(candidate)

    for pattern in blacklist:
        try:
            if re.search(pattern, normalized_cmd, re.IGNORECASE):
                return "blocked", f"Matched dangerous rule: {pattern}"
        except re.error:
            if pattern.lower() in cmd_lower:
                return "blocked", f"Matched dangerous keyword: {pattern}"

    return "safe", ""
