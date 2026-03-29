"""
LLM 适配器抽象基类与统一数据类型定义。

所有 Provider（OpenAI、Anthropic、Gemini、Ollama）都继承 LLMAdapter，
实现统一的消息格式化、工具格式化、流式/非流式对话接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator, Any
import json


# ============================================================
# 统一数据类型
# ============================================================

@dataclass
class ContentPart:
    """统一的多模态内容块"""
    type: str                           # "text" | "image"
    text: str | None = None             # type=="text" 时
    image_data: str | None = None       # base64 或 URL
    mime_type: str = "image/png"


@dataclass
class ToolCallInfo:
    """统一的 tool_call 表示"""
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
    """流式响应的统一事件"""
    type: str                                       # "text" | "tool_calls" | "reasoning" | "done" | "error"
    text: str | None = None
    tool_calls: list[ToolCallInfo] | None = None
    reasoning_text: str | None = None
    error: str | None = None


# ============================================================
# 已知模型上下文窗口限度表
# ============================================================

MODEL_CONTEXT_LIMITS: dict[str, int] = {
    # OpenAI
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
    "gpt-5.4-nano": 1048576,
    # DeepSeek
    "deepseek-chat": 65536,
    "deepseek-reasoner": 65536,
    # Anthropic
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-3.5-sonnet": 200000,
    "claude-3.5-haiku": 200000,
    "claude-4-opus": 200000,
    "claude-4-sonnet": 200000,
    # Gemini
    "gemini-pro": 32768,
    "gemini-1.5-pro": 2097152,
    "gemini-1.5-flash": 1048576,
    "gemini-2.0-flash": 1048576,
    "gemini-2.5-pro": 1048576,
    "gemini-2.5-flash": 1048576,
    # Ollama 常见
    "llama3": 8192,
    "llama3.1": 131072,
    "llama3.2": 131072,
    "mistral": 32768,
    "qwen2.5": 131072,
}


# ============================================================
# 抽象基类
# ============================================================

class LLMAdapter(ABC):
    """
    LLM API 适配器抽象基类。

    子类必须实现：
    - format_messages: 将统一消息格式转为 Provider 格式
    - format_tools: 将 OpenAI 格式工具 Schema 转为 Provider 格式
    - stream_chat: 流式对话
    - chat: 非流式对话
    """

    def get_context_limit(self, model_name: str) -> int:
        """获取模型上下文窗口大小（token 数）"""
        if model_name in MODEL_CONTEXT_LIMITS:
            return MODEL_CONTEXT_LIMITS[model_name]
        # 前缀匹配
        for key, limit in MODEL_CONTEXT_LIMITS.items():
            if model_name.startswith(key):
                return limit
        return 8192  # 保守默认值

    @abstractmethod
    def format_messages(self, messages: list[dict]) -> Any:
        """将统一消息格式转换为 Provider 特定格式"""

    @abstractmethod
    def format_tools(self, tools: list[dict]) -> Any:
        """将 OpenAI 格式的工具 Schema 转换为 Provider 特定格式"""

    @abstractmethod
    async def stream_chat(
        self, session, url: str, api_key: str, model: str,
        messages: list[dict], tools: list[dict] | None = None, **kwargs
    ) -> AsyncGenerator[StreamEvent, None]:
        """流式对话，yield StreamEvent"""

    @abstractmethod
    async def chat(
        self, session, url: str, api_key: str, model: str,
        messages: list[dict], tools: list[dict] | None = None, **kwargs
    ) -> dict:
        """非流式对话，返回 {"content": str, "tool_calls": list[ToolCallInfo]}"""


# ============================================================
# 工厂函数
# ============================================================

def create_adapter(provider_name: str) -> LLMAdapter:
    """根据 provider 名称创建对应的适配器实例"""
    from adapters.openai_adapter import OpenAIAdapter
    from adapters.anthropic_adapter import AnthropicAdapter
    from adapters.gemini_adapter import GeminiAdapter
    from adapters.ollama_adapter import OllamaAdapter

    adapters = {
        "openai": OpenAIAdapter,
        "anthropic": AnthropicAdapter,
        "gemini": GeminiAdapter,
        "ollama": OllamaAdapter,
    }
    cls = adapters.get(provider_name.lower())
    if not cls:
        raise ValueError(
            f"不支持的 LLM Provider: {provider_name}。"
            f"支持的选项: {', '.join(adapters.keys())}"
        )
    return cls()
