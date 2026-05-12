from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .capabilities.base import CapabilityError


@dataclass(frozen=True, slots=True)
class ShellTemplate:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: int | None = None
    description: str = ""


def ensure_sandbox_dir(path: str) -> Path:
    sandbox = Path(path).expanduser()
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox.resolve()


def validate_gpio_pin(pin: Any, allowed_pins: list[int]) -> int:
    try:
        normalized = int(pin)
    except (TypeError, ValueError) as exc:
        raise CapabilityError("invalid_gpio_pin", "GPIO pin must be an integer") from exc
    if normalized not in set(int(item) for item in allowed_pins):
        raise CapabilityError(
            "gpio_pin_not_allowed",
            f"GPIO pin {normalized} is not allowlisted for this endpoint",
        )
    return normalized


def normalize_safe_shell_allowlist(items: list[dict[str, Any] | str]) -> list[ShellTemplate]:
    templates: list[ShellTemplate] = []
    seen: set[str] = set()
    for item in items or []:
        template = _normalize_shell_template(item)
        if template is None or template.name in seen:
            continue
        seen.add(template.name)
        templates.append(template)
    return templates


def find_shell_template(name: str, items: list[dict[str, Any] | str]) -> ShellTemplate | None:
    normalized = str(name or "").strip()
    if not normalized:
        return None
    for item in normalize_safe_shell_allowlist(items):
        if item.name == normalized:
            return item
    return None


def _normalize_shell_template(item: dict[str, Any] | str) -> ShellTemplate | None:
    if isinstance(item, str):
        argv = tuple(part for part in shlex.split(item) if part)
        if not argv:
            return None
        return ShellTemplate(name=argv[0], argv=argv)
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or "").strip()
    raw_argv = item.get("argv")
    if not isinstance(raw_argv, list):
        return None
    argv = tuple(str(part) for part in raw_argv if str(part or "").strip())
    if not name or not argv:
        return None
    timeout_seconds = item.get("timeout_seconds")
    try:
        timeout = int(timeout_seconds) if timeout_seconds is not None else None
    except (TypeError, ValueError):
        timeout = None
    return ShellTemplate(
        name=name,
        argv=argv,
        timeout_seconds=timeout,
        description=str(item.get("description") or "").strip(),
    )
