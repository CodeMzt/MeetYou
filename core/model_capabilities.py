"""Model capability resolver for request budgeting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ContextBudget:
    context_window: int
    max_output_tokens: int
    reserved_reasoning_tokens: int
    tool_result_budget: int
    target_input_tokens: int

    def to_dict(self) -> dict[str, int]:
        return {
            "context_window": int(self.context_window),
            "max_output_tokens": int(self.max_output_tokens),
            "reserved_reasoning_tokens": int(self.reserved_reasoning_tokens),
            "tool_result_budget": int(self.tool_result_budget),
            "target_input_tokens": int(self.target_input_tokens),
        }


class ModelCapabilityResolver:
    """Resolve per-request budget based on model limits + options."""

    @staticmethod
    def resolve(*, context_limit_info: dict[str, Any] | None = None, model_options: dict[str, Any] | None = None) -> ContextBudget:
        info = context_limit_info or {}
        options = model_options or {}
        context_window = int(info.get("context_limit_tokens", 0) or 8192)

        explicit_output = int(info.get("max_output_tokens", 0) or 0)
        if explicit_output <= 0:
            explicit_output = max(512, int(context_window * 0.2))

        thinking = dict(options.get("thinking") or {})
        explicit_reasoning = int(info.get("reserved_reasoning_tokens", 0) or thinking.get("budget_tokens") or 0)
        if explicit_reasoning <= 0:
            explicit_reasoning = max(128, int(explicit_output * 0.25))

        tool_result_budget = int(info.get("tool_result_budget", 0) or 0)
        if tool_result_budget <= 0:
            tool_result_budget = max(256, int(context_window * 0.08))

        headroom = max(512, int(context_window * 0.03))
        target_input_tokens = max(
            256,
            context_window - explicit_output - explicit_reasoning - headroom,
        )

        return ContextBudget(
            context_window=context_window,
            max_output_tokens=explicit_output,
            reserved_reasoning_tokens=explicit_reasoning,
            tool_result_budget=tool_result_budget,
            target_input_tokens=target_input_tokens,
        )
