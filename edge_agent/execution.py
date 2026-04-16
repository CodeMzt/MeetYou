from __future__ import annotations

from typing import Any, Awaitable, Callable

from agent_sdk.capability_ids import build_agent_capability_id


Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def echo_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    text = str(arguments.get("text") or arguments.get("message") or "")
    return {
        "summary": text or "edge echo",
        "echo": text,
        "arguments": dict(arguments or {}),
    }


def _coerce_number(arguments: dict[str, Any], key: str) -> float:
    value = arguments.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Argument '{key}' must be a number")
    return float(value)


async def math_add_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    left = _coerce_number(arguments, "left")
    right = _coerce_number(arguments, "right")
    total = left + right
    return {
        "summary": f"{left:g} + {right:g} = {total:g}",
        "left": left,
        "right": right,
        "result": total,
        "operation": "add",
    }


async def math_divide_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    left = _coerce_number(arguments, "left")
    right = _coerce_number(arguments, "right")
    if right == 0:
        raise ValueError("Division by zero is not allowed")
    quotient = left / right
    return {
        "summary": f"{left:g} / {right:g} = {quotient:g}",
        "left": left,
        "right": right,
        "result": quotient,
        "operation": "divide",
    }


def build_capability_handlers(agent_id: str) -> dict[str, Handler]:
    return {
        build_agent_capability_id(agent_id, "utility.echo"): echo_handler,
        build_agent_capability_id(agent_id, "math.add"): math_add_handler,
        build_agent_capability_id(agent_id, "math.divide"): math_divide_handler,
    }
