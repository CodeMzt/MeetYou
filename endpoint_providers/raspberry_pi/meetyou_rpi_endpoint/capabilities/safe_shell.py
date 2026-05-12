from __future__ import annotations

import asyncio
from typing import Any

from .base import (
    CapabilityContext,
    CapabilityDefinition,
    CapabilityError,
)
from ..logging import redact_text
from ..security import (
    ensure_sandbox_dir,
    find_shell_template,
)


MAX_OUTPUT_BYTES = 8192


async def handle_safe_exec(arguments: dict[str, Any], context: CapabilityContext) -> dict[str, Any]:
    if not context.config.security.safe_shell_enabled:
        raise CapabilityError("safe_shell_disabled", "Safe shell is disabled for this endpoint")
    if "argv" in arguments or "shell" in arguments or "cmd" in arguments:
        raise CapabilityError(
            "safe_shell_arbitrary_command_rejected",
            "Safe shell accepts only a configured command name, not arbitrary argv or shell strings",
        )
    command_name = str(arguments.get("command") or arguments.get("name") or "").strip()
    template = find_shell_template(command_name, context.config.security.safe_shell_allowlist)
    if template is None:
        raise CapabilityError(
            "safe_shell_command_not_allowed",
            f"Command is not allowlisted: {command_name or '<empty>'}",
        )
    timeout_seconds = _resolve_timeout_seconds(arguments, template.timeout_seconds, context.config.operation)
    sandbox = ensure_sandbox_dir(context.config.security.sandbox_dir)
    process = await asyncio.create_subprocess_exec(
        *template.argv,
        cwd=str(sandbox),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise CapabilityError(
            "safe_shell_timeout",
            f"Allowlisted command timed out after {timeout_seconds} seconds",
            retryable=True,
        ) from exc
    stdout_text, stdout_truncated = _decode_limited(stdout)
    stderr_text, stderr_truncated = _decode_limited(stderr)
    return {
        "summary": f"{command_name} exited with {process.returncode}",
        "command": command_name,
        "returncode": int(process.returncode or 0),
        "stdout": redact_text(stdout_text),
        "stderr": redact_text(stderr_text),
        "truncated": bool(stdout_truncated or stderr_truncated),
        "sandbox_dir": str(sandbox),
    }


def build_safe_shell_capability() -> CapabilityDefinition:
    return CapabilityDefinition(
        name="rpi.shell.safe_exec",
        description="Raspberry Pi Safe Shell",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_seconds": {"type": "integer"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "command": {"type": "string"},
                "returncode": {"type": "integer"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "truncated": {"type": "boolean"},
                "sandbox_dir": {"type": "string"},
            },
            "required": ["summary", "command", "returncode", "stdout", "stderr", "truncated"],
        },
        risk_level="destructive",
        requires_confirmation=True,
        handler=handle_safe_exec,
        safe_parallel=False,
        tags=("rpi", "shell", "allowlist"),
    )


def _resolve_timeout_seconds(arguments: dict[str, Any], template_timeout: int | None, operation_config) -> int:
    requested = arguments.get("timeout_seconds")
    if requested is None:
        requested = template_timeout
    if requested is None:
        requested = operation_config.default_timeout_seconds
    try:
        timeout = int(requested)
    except (TypeError, ValueError):
        timeout = operation_config.default_timeout_seconds
    return max(1, min(timeout, operation_config.max_timeout_seconds))


def _decode_limited(value: bytes) -> tuple[str, bool]:
    truncated = len(value) > MAX_OUTPUT_BYTES
    limited = value[:MAX_OUTPUT_BYTES]
    return limited.decode("utf-8", errors="replace"), truncated
