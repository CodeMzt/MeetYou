"""
Anthropic Claude Messages API 适配器。

支持：
- SSE 事件流 (content_block_start/delta/stop)
- tool_use content block 解析
- system 消息提取为顶层参数
- 多模态（base64 图像）
- Extended Thinking（推理模式）
"""

import json
import logging
from typing import AsyncGenerator

from adapters.base import LLMAdapter, StreamEvent, ToolCallInfo

logger = logging.getLogger("meetyou.adapter.anthropic")


class AnthropicAdapter(LLMAdapter):
    """Anthropic Messages API 适配器"""

    def format_messages(self, messages: list[dict]) -> dict:
        """返回 {"system": str|None, "messages": list}"""
        system_parts = []
        formatted = []

        for msg in messages:
            role = msg["role"]
            content = msg.get("content")

            # system 消息提取为顶层参数
            if role == "system":
                if isinstance(content, str) and content:
                    system_parts.append(content)
                continue

            # tool result → Anthropic 用 user message + tool_result block
            if role == "tool":
                formatted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": content if isinstance(content, str) else str(content),
                    }],
                })
                continue

            new_msg = {"role": "user" if role == "user" else "assistant"}

            # 多模态
            if isinstance(content, list):
                parts = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        parts.append({"type": "text", "text": part["text"]})
                    elif part.get("type") == "image":
                        parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": part.get("mime_type", "image/png"),
                                "data": part.get("image_data", ""),
                            },
                        })
                new_msg["content"] = parts

            # assistant + tool_calls
            elif role == "assistant" and msg.get("tool_calls"):
                blocks = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": json.loads(fn.get("arguments", "{}")),
                    })
                new_msg["content"] = blocks
            else:
                new_msg["content"] = content or ""

            formatted.append(new_msg)

        return {
            "system": "\n\n".join(system_parts) if system_parts else None,
            "messages": formatted,
        }

    def format_tools(self, tools: list[dict]) -> list[dict] | None:
        if not tools:
            return None
        result = []
        for tool in tools:
            fn = tool.get("function", {})
            result.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {}),
            })
        return result

    async def stream_chat(
        self, session, url, api_key, model, messages, tools=None, **kwargs
    ) -> AsyncGenerator[StreamEvent, None]:
        msg_data = self.format_messages(messages)
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": msg_data["messages"],
            "stream": True,
            "max_tokens": kwargs.pop("max_tokens", 4096),
        }
        if msg_data["system"]:
            payload["system"] = msg_data["system"]
        ft = self.format_tools(tools)
        if ft:
            payload["tools"] = ft
        # Extended thinking
        if kwargs.pop("thinking", False):
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": kwargs.pop("thinking_budget", 10000),
            }
        payload.update(kwargs)

        current_tool: ToolCallInfo | None = None
        tool_calls: list[ToolCallInfo] = []

        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.content:
                raw = line.decode("utf-8").strip()
                if not raw.startswith("data:"):
                    continue
                try:
                    data = json.loads(raw[5:].strip())
                except (json.JSONDecodeError, ValueError):
                    continue

                evt = data.get("type")
                if evt == "content_block_start":
                    block = data.get("content_block", {})
                    if block.get("type") == "tool_use":
                        current_tool = ToolCallInfo(
                            id=block.get("id", ""), name=block.get("name", "")
                        )
                elif evt == "content_block_delta":
                    delta = data.get("delta", {})
                    dt = delta.get("type")
                    if dt == "text_delta":
                        yield StreamEvent(type="text", text=delta.get("text", ""))
                    elif dt == "thinking_delta":
                        yield StreamEvent(type="reasoning", reasoning_text=delta.get("thinking", ""))
                    elif dt == "input_json_delta" and current_tool:
                        current_tool.arguments_str += delta.get("partial_json", "")
                elif evt == "content_block_stop":
                    if current_tool:
                        tool_calls.append(current_tool)
                        current_tool = None
                elif evt == "message_stop":
                    break

        if tool_calls:
            yield StreamEvent(type="tool_calls", tool_calls=tool_calls)
        yield StreamEvent(type="done")

    async def chat(self, session, url, api_key, model, messages, tools=None, **kwargs) -> dict:
        msg_data = self.format_messages(messages)
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": msg_data["messages"],
            "stream": False,
            "max_tokens": kwargs.pop("max_tokens", 4096),
        }
        if msg_data["system"]:
            payload["system"] = msg_data["system"]
        ft = self.format_tools(tools)
        if ft:
            payload["tools"] = ft
        payload.update(kwargs)

        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()

        result = {"content": "", "tool_calls": []}
        for block in data.get("content", []):
            if block.get("type") == "text":
                result["content"] += block.get("text", "")
            elif block.get("type") == "tool_use":
                result["tool_calls"].append(ToolCallInfo(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments_str=json.dumps(block.get("input", {})),
                ))
        return result
