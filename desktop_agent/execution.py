from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from agent_sdk.capability_ids import build_agent_capability_id
from desktop_agent.config import DesktopAgentConfig
from desktop_agent.policy import (
    DesktopAgentPolicyError,
    assess_command_safety,
    ensure_readable_path,
    ensure_workspace_path,
    ensure_writable_path,
    load_cmd_policy,
)
from tools.document_tools import build_workspace_analysis_payload


Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def echo_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    text = str(arguments.get("text") or arguments.get("message") or "")
    return {
        "summary": text or "echo",
        "echo": text,
        "arguments": dict(arguments or {}),
    }


def _read_text_file(path: Path, encoding: str) -> str:
    return path.read_text(encoding=encoding, errors="replace")


def _summarize_text(text: str, limit: int = 6000) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def build_file_read_handler(config: DesktopAgentConfig) -> Handler:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(arguments.get("path") or "").strip()
        if not raw_path:
            raise DesktopAgentPolicyError("path_required", "path is required")
        encoding = str(arguments.get("encoding") or "utf-8").strip() or "utf-8"
        target = ensure_readable_path(config, raw_path)
        content = await asyncio.to_thread(_read_text_file, target, encoding)
        excerpt, truncated = _summarize_text(content, limit=int(arguments.get("max_chars") or 6000))
        return {
            "summary": f"Read file: {target}",
            "path": str(target),
            "content": excerpt,
            "truncated": truncated,
            "size_bytes": target.stat().st_size,
            "encoding": encoding,
        }

    return handler


def build_file_write_handler(config: DesktopAgentConfig) -> Handler:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(arguments.get("path") or "").strip()
        if not raw_path:
            raise DesktopAgentPolicyError("path_required", "path is required")
        content = str(arguments.get("content") or "")
        mode = str(arguments.get("mode") or "overwrite").strip().lower() or "overwrite"
        target = ensure_writable_path(config, raw_path)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        if mode == "append":
            await asyncio.to_thread(_append_text_file, target, content)
        elif mode == "create_if_missing":
            if target.exists():
                raise DesktopAgentPolicyError("already_exists", f"File already exists: {target}")
            await asyncio.to_thread(target.write_text, content, encoding="utf-8")
        else:
            await asyncio.to_thread(target.write_text, content, encoding="utf-8")
        return {
            "summary": f"Wrote file: {target}",
            "path": str(target),
            "mode": mode,
            "bytes_written": len(content.encode("utf-8")),
        }

    return handler


def _append_text_file(path: Path, content: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)


def build_shell_exec_handler(config: DesktopAgentConfig) -> Handler:
    policy = load_cmd_policy(config)

    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        command = str(arguments.get("command") or arguments.get("cmd") or "").strip()
        if not command:
            raise DesktopAgentPolicyError("command_required", "command is required")
        safety, reason = assess_command_safety(command, policy=policy)
        if safety != "safe":
            raise DesktopAgentPolicyError("command_blocked", reason or "command blocked by policy")

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(config.workspace_root),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=max(5, config.command_timeout_seconds))
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise DesktopAgentPolicyError("command_timeout", f"command timed out after {config.command_timeout_seconds} seconds") from exc

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise DesktopAgentPolicyError(
                "command_failed",
                f"command failed with exit code {process.returncode}: {stderr_text or stdout_text}",
            )
        return {
            "summary": f"Command succeeded: {command}",
            "command": command,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "returncode": process.returncode,
        }

    return handler


def build_workspace_analyze_handler(config: DesktopAgentConfig) -> Handler:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(arguments.get("path") or "").strip()
        if not raw_path:
            raise DesktopAgentPolicyError("path_required", "path is required")
        target = ensure_workspace_path(config, raw_path)
        depth = int(arguments.get("depth") or 3)
        include_hidden = bool(arguments.get("include_hidden", False))
        focus = str(arguments.get("focus") or "")
        payload = await asyncio.to_thread(
            build_workspace_analysis_payload,
            target,
            depth=depth,
            include_hidden=include_hidden,
            focus=focus,
        )
        return payload

    return handler


def build_capability_handlers(config: DesktopAgentConfig) -> dict[str, Handler]:
    return {
        build_agent_capability_id(config.agent_id, "utility.echo"): echo_handler,
        build_agent_capability_id(config.agent_id, "workspace.analyze"): build_workspace_analyze_handler(config),
        build_agent_capability_id(config.agent_id, "file.read"): build_file_read_handler(config),
        build_agent_capability_id(config.agent_id, "file.write"): build_file_write_handler(config),
        build_agent_capability_id(config.agent_id, "shell.exec"): build_shell_exec_handler(config),
    }
