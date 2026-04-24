"""
LLM adapter abstraction and shared event/data models.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncGenerator
import json


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


MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
    "o1": 200000,
    "o1-mini": 128000,
    "o1-preview": 128000,
    "o3-mini": 200000,
    "gpt-4.1": 1048576,
    "gpt-4.1-mini": 1048576,
    "gpt-4.1-nano": 1048576,
    "gpt-5.4": 400000,
    "gpt-5.4-mini": 400000,
    "gpt-5.4-nano": 400000,
    "deepseek-chat": 65536,
    "deepseek-reasoner": 65536,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-3.5-sonnet": 200000,
    "claude-3.5-haiku": 200000,
    "claude-4-opus": 200000,
    "claude-4-sonnet": 200000,
    "gemini-pro": 32768,
    "gemini-1.5-pro": 2097152,
    "gemini-1.5-flash": 1048576,
    "gemini-2.0-flash": 1048576,
    "gemini-2.5-pro": 1048576,
    "gemini-2.5-flash": 1048576,
    "llama3": 8192,
    "llama3.1": 131072,
    "llama3.2": 131072,
    "mistral": 32768,
    "qwen2.5": 131072,
}


class LLMAdapter(ABC):
    """
    Abstract base class for provider adapters.
    """

    def get_context_limit_info(self, model_name: str, *, provider_name: str = "") -> dict[str, Any]:
        normalized_provider = str(provider_name or "").strip().lower()
        if not normalized_provider:
            normalized_provider = self.__class__.__name__.replace("Adapter", "").lower()
        normalized_model = str(model_name or "").strip().lower()
        from core.model_capabilities import get_model_capability_resolver

        resolver = get_model_capability_resolver()
        capability, diagnostic = resolver.resolve(provider=normalized_provider, model=normalized_model)
        return {
            "context_limit_tokens": int(capability.context_window),
            "max_output_tokens": int(capability.max_output_tokens),
            "provider": normalized_provider,
            "model": normalized_model,
            "source": str(diagnostic.get("source") or capability.source),
            "confidence": str(diagnostic.get("confidence") or capability.confidence),
            "diagnostic": str(diagnostic.get("diagnostic") or ""),
        }

    def get_context_limit(self, model_name: str) -> int:
        return int(self.get_context_limit_info(model_name).get("context_limit_tokens", 8192) or 8192)

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
