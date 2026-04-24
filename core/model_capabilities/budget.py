"""Per-request context budgeting built on resolved model capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ModelCapabilityBudget:
    context_window: int
    max_output_tokens: int
    reserved_reasoning_tokens: int
    tool_result_budget: int

    @property
    def input_budget(self) -> int:
        consumed = self.max_output_tokens + self.reserved_reasoning_tokens + self.tool_result_budget
        return max(256, self.context_window - consumed)

    def to_dict(self) -> dict[str, int]:
        return {
            "context_window": int(self.context_window),
            "max_output_tokens": int(self.max_output_tokens),
            "reserved_reasoning_tokens": int(self.reserved_reasoning_tokens),
            "tool_result_budget": int(self.tool_result_budget),
            "input_budget": int(self.input_budget),
        }


class ModelContextBudgetResolver:
    def resolve(
        self,
        *,
        model: str,
        context_limit_info: dict[str, Any] | None,
        length_policy: dict[str, Any] | None = None,
        model_options: dict[str, Any] | None = None,
    ) -> ModelCapabilityBudget:
        del model
        context_window = int((context_limit_info or {}).get("context_limit_tokens", 0) or 8192)
        length_policy_payload = dict(length_policy or {})
        thinking_config = dict((model_options or {}).get("thinking") or {})

        max_output = int(
            length_policy_payload.get("reserved_response_tokens", 0)
            or max(768, int(context_window * 0.2))
        )
        reasoning_budget = 0
        thinking_enabled = thinking_config.get("enabled")
        if thinking_enabled is None or bool(thinking_enabled):
            reasoning_budget = int(thinking_config.get("budget_tokens", 0) or max(128, int(context_window * 0.04)))
        tool_result_budget = max(128, int(context_window * 0.08))

        if max_output + reasoning_budget + tool_result_budget >= context_window:
            max_output = min(max_output, max(256, int(context_window * 0.35)))
            reasoning_budget = min(reasoning_budget, max(0, int(context_window * 0.08)))
            tool_result_budget = min(tool_result_budget, max(64, int(context_window * 0.08)))

        return ModelCapabilityBudget(
            context_window=context_window,
            max_output_tokens=max_output,
            reserved_reasoning_tokens=reasoning_budget,
            tool_result_budget=tool_result_budget,
        )
