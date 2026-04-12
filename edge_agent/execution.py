from __future__ import annotations

from typing import Any, Awaitable, Callable


Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def echo_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    text = str(arguments.get("text") or arguments.get("message") or "")
    return {
        "summary": text or "edge echo",
        "echo": text,
        "arguments": dict(arguments or {}),
    }


def build_capability_handlers(agent_id: str) -> dict[str, Handler]:
    return {
        f"agent.{agent_id}.utility.echo": echo_handler,
    }
