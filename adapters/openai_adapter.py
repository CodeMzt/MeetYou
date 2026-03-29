"""
OpenAI / DeepSeek / 兼容 API 适配器。

支持：
- SSE 流式响应解析
- 多 tool_call 按 index 分组累积
- 多模态消息（image_url content parts）
- reasoning_content（o1/o3 推理模型）
"""

import json
import logging
from typing import AsyncGenerator

from adapters.base import LLMAdapter, StreamEvent, ToolCallInfo

logger = logging.getLogger("meetyou.adapter.openai")


class OpenAIAdapter(LLMAdapter):
    """OpenAI Chat Completions API 适配器（兼容 DeepSeek 等）"""

    def format_messages(self, messages: list[dict]) -> list[dict]:
        formatted = []
        for msg in messages:
            new_msg = {"role": msg["role"]}
            content = msg.get("content")

            if isinstance(content, list):
                # 多模态内容
                parts = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        parts.append({"type": "text", "text": part["text"]})
                    elif part.get("type") == "image":
                        img = part.get("image_data", "")
                        mime = part.get("mime_type", "image/png")
                        if img.startswith("http"):
                            parts.append({"type": "image_url", "image_url": {"url": img}})
                        else:
                            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img}"}})
                new_msg["content"] = parts
            else:
                new_msg["content"] = content

            if "tool_calls" in msg:
                new_msg["tool_calls"] = msg["tool_calls"]
            if "tool_call_id" in msg:
                new_msg["tool_call_id"] = msg["tool_call_id"]

            formatted.append(new_msg)
        return formatted

    def format_tools(self, tools: list[dict]) -> list[dict] | None:
        return tools if tools else None

    async def stream_chat(
        self, session, url, api_key, model, messages, tools=None, **kwargs
    ) -> AsyncGenerator[StreamEvent, None]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": self.format_messages(messages),
            "stream": True,
        }
        ft = self.format_tools(tools)
        if ft:
            payload["tools"] = ft
        payload.update(kwargs)

        # 按 index 累积多个 tool_calls
        tool_calls_acc: dict[int, ToolCallInfo] = {}

        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.content:
                raw = line.decode("utf-8").strip()
                if not raw.startswith("data:"):
                    continue
                json_str = raw[5:].strip()
                if json_str.startswith("[DONE]"):
                    break
                try:
                    data = json.loads(json_str)
                except (json.JSONDecodeError, ValueError):
                    continue

                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}

                # 推理内容 (o1/o3/DeepSeek-R1)
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    yield StreamEvent(type="reasoning", reasoning_text=reasoning)

                # 工具调用
                if "tool_calls" in delta:
                    for tc_chunk in delta["tool_calls"]:
                        idx = tc_chunk.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = ToolCallInfo()
                        if "id" in tc_chunk:
                            tool_calls_acc[idx].id = tc_chunk["id"]
                        if "function" in tc_chunk:
                            fn = tc_chunk["function"]
                            if "name" in fn:
                                tool_calls_acc[idx].name = fn["name"]
                            if "arguments" in fn:
                                tool_calls_acc[idx].arguments_str += fn["arguments"]
                    continue

                # 文本内容
                text = delta.get("content")
                if text:
                    yield StreamEvent(type="text", text=text)

        if tool_calls_acc:
            yield StreamEvent(type="tool_calls", tool_calls=list(tool_calls_acc.values()))
        yield StreamEvent(type="done")

    async def chat(self, session, url, api_key, model, messages, tools=None, **kwargs) -> dict:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": self.format_messages(messages),
            "stream": False,
        }
        ft = self.format_tools(tools)
        if ft:
            payload["tools"] = ft
        payload.update(kwargs)

        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()

        choices = data.get("choices") or []
        if not choices:
            return {"content": "", "tool_calls": []}

        message = choices[0].get("message") or {}
        result = {"content": message.get("content") or "", "tool_calls": []}

        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                fn = tc.get("function", {})
                result["tool_calls"].append(ToolCallInfo(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments_str=fn.get("arguments", "{}"),
                ))
        return result
