from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DEFAULT_BLACKLIST_PATTERNS = [
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

CORE_DEFAULT_WHITELIST = [
    "dir",
    "echo",
    "hostname",
    "whoami",
    "date",
    "time",
    "ver",
    "where",
    "python --version",
    "node --version",
    "npm --version",
    "git status",
    "git log",
    "git diff",
    "git branch",
    "curl",
    "curl.exe",
    "wget -qO-",
    "wget.exe -qO-",
]

CORE_DEFAULT_POLICY = {
    "mode": "whitelist",
    "whitelist": list(CORE_DEFAULT_WHITELIST),
    "blacklist_patterns": [],
}

_SHELL_CONTROL_PATTERN = r"(^|\s)&(\s|$)|&&|\|\||[;|<>]"
_TRANSFER_TOOL_RE = re.compile(r"^\s*(curl(?:\.exe)?|wget(?:\.exe)?)(?:\s|$)", re.IGNORECASE)
_TRANSFER_WRITE_PATTERNS = [
    r"\s(?:-o|--output|--output-dir|-O|--remote-name|--remote-header-name|-J|--config|-K)(?:\s|=|$)",
    r"\s(?:-T|--upload-file|--form|-F)(?:\s|=|$)",
    r"\s(?:--data(?:-ascii|-binary|-raw|-urlencode)?|-d)(?:\s|=)*@",
    r"\s(?:--output-document|--directory-prefix|-P)(?:\s|=|$)",
    r"\b(?:file|ftp|sftp|scp|smb|gopher|dict|ldap)://",
]


def normalize_command(command: str) -> str:
    return re.sub(r"\s+", " ", str(command or "").strip())


def load_policy_file(path: str | Path, *, default_policy: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(default_policy)
    return payload if isinstance(payload, dict) else dict(default_policy)


def whitelist_matches(command: str, whitelist: list[Any], *, require_token_boundary: bool = True) -> bool:
    lowered = normalize_command(command).lower()
    for item in whitelist or []:
        allowed = normalize_command(str(item or "")).lower()
        if not allowed:
            continue
        if lowered == allowed:
            return True
        if require_token_boundary and lowered.startswith(f"{allowed} "):
            return True
        if not require_token_boundary and lowered.startswith(allowed):
            return True
    return False


def _combined_blacklist(policy: dict[str, Any]) -> list[str]:
    blacklist: list[str] = []
    seen: set[str] = set()
    for pattern in [*DEFAULT_BLACKLIST_PATTERNS, *list(policy.get("blacklist_patterns", []) or [])]:
        candidate = str(pattern or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        blacklist.append(candidate)
    return blacklist


def _matches_pattern(pattern: str, command: str, normalized_command: str) -> bool:
    try:
        return bool(
            re.search(pattern, command, re.IGNORECASE)
            or re.search(pattern, normalized_command, re.IGNORECASE)
        )
    except re.error:
        return pattern.lower() in normalized_command.lower()


def _hard_guard(command: str, normalized_command: str) -> tuple[str, str] | None:
    if _matches_pattern(_SHELL_CONTROL_PATTERN, command, normalized_command):
        return "blocked", "Matched shell control or redirection operator."
    if _TRANSFER_TOOL_RE.match(normalized_command):
        for pattern in _TRANSFER_WRITE_PATTERNS:
            if _matches_pattern(pattern, command, normalized_command):
                return "blocked", f"Matched restricted transfer option: {pattern}"
    return None


def assess_command_safety(
    command: str,
    *,
    policy: dict[str, Any] | None,
    blacklist_match_status: str = "blocked",
    enforce_hard_guards: bool = False,
    whitelist_requires_boundary: bool = True,
) -> tuple[str, str]:
    normalized_command = normalize_command(command)
    if not normalized_command:
        return "blocked", "Command is required."

    resolved_policy = dict(policy or {})
    if enforce_hard_guards:
        hard_result = _hard_guard(command, normalized_command)
        if hard_result is not None:
            return hard_result

    if not resolved_policy or resolved_policy.get("mode") == "none":
        return "safe", ""

    mode = str(resolved_policy.get("mode") or "blacklist").strip().lower()
    if mode == "whitelist":
        if whitelist_matches(
            normalized_command,
            list(resolved_policy.get("whitelist", []) or []),
            require_token_boundary=whitelist_requires_boundary,
        ):
            return "safe", ""
        return "blocked", f"Command is not in whitelist: {normalized_command}"

    for pattern in _combined_blacklist(resolved_policy):
        if _matches_pattern(pattern, command, normalized_command):
            return blacklist_match_status, f"Matched dangerous rule: {pattern}"

    return "safe", ""
