from __future__ import annotations

from typing import Any

from .base import (
    CapabilityContext,
    CapabilityDefinition,
)


async def handle_echo(arguments: dict[str, Any], context: CapabilityContext) -> dict[str, Any]:
    del context
    text = str(arguments.get("text") or "")
    return {"text": text}


def build_echo_capability() -> CapabilityDefinition:
    return CapabilityDefinition(
        name="rpi.echo",
        description="Raspberry Pi Echo",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        risk_level="read",
        requires_confirmation=False,
        handler=handle_echo,
        safe_parallel=True,
        tags=("rpi", "utility", "debug"),
    )
