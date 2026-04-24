"""
LLM adapter abstraction and shared event/data models.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncGenerator
import json

from core.model_capabilities.resolver import get_model_capability_resolver


@dataclass
class ContentPart:
    """Unified multimodal content part."""

    type: str
    text: str | None = None
    image_data: str | None = None
    mime_type: str = "image/png"


@dataclass
class ToolCallInfo:
    """Unified tool call representation."""

    id: str = ""
    name: str = ""
    arguments_str: str = ""

    @property
    def arguments(self) -> dict:
        try:
            return json.loads(self.arguments_str) if self.arguments_str else {}
        except (json.JSONDecodeError, TypeError):
            return {}


@dataclass
class StreamEvent:
    """Unified streaming event."""

    type: str
    text: str | None = None
    tool_calls: list[ToolCallInfo] | None = None
    provider_items: list[dict[str, Any]] | None = None
    reasoning_text: str | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None


class LLMAdapter(ABC):
    """
    Abstract base class for provider adapters.
    """

    provider_name: str = ""

    def get_context_limit(self, model_name: str) -> int:
        capability = get_model_capability_resolver().resolve(self.provider_name, model_name)
        return int(capability.context_window)

    @abstractmethod
    def format_messages(self, messages: list[dict]) -> Any:
        """Convert unified messages into provider-specific payload."""

    @abstractmethod
    def format_tools(self, tools: list[dict]) -> Any:
        """Convert unified tool schema into provider-specific payload."""

    @abstractmethod
    async def stream_chat(
        self,
        session,
        url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        cancel_event=None,
        **kwargs,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream chat response."""

    @abstractmethod
    async def chat(
        self,
        session,
        url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> dict:
        """Non-streaming chat response."""


def _build_compat_context_limits() -> dict[str, int]:
    resolver = get_model_capability_resolver()
    limits: dict[str, int] = {}
    for item in resolver._registry.get("entries", []):  # backward-compat export
        if not isinstance(item, dict):
            continue
        patterns = item.get("model_patterns") or []
        if not patterns:
            continue
        limits[str(patterns[0]).strip().lower()] = int(item.get("context_window", 0) or 0)
    return {k: v for k, v in limits.items() if v > 0}


MODEL_CONTEXT_LIMITS: dict[str, int] = _build_compat_context_limits()


def create_adapter(provider_name: str) -> LLMAdapter:
    """Create an adapter instance for the given provider."""

    from adapters.anthropic_adapter import AnthropicAdapter
    from adapters.gemini_adapter import GeminiAdapter
    from adapters.ollama_adapter import OllamaAdapter
    from adapters.openai_adapter import OpenAIAdapter

    adapters = {
        "openai": OpenAIAdapter,
        "anthropic": AnthropicAdapter,
        "gemini": GeminiAdapter,
        "ollama": OllamaAdapter,
    }
    cls = adapters.get(provider_name.lower())
    if not cls:
        raise ValueError(
            f"Unsupported LLM provider: {provider_name}. "
            f"Available: {', '.join(adapters.keys())}"
        )
    return cls()
