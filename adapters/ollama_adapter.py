"""
Ollama 本地 Chat API 适配器。

支持：
- NDJSON 流式解析
- message.tool_calls 处理
- images 字段（base64 列表）
- /api/show 查询模型上下文长度
"""

import json
import logging
from typing import AsyncGenerator

from adapters.base import LLMAdapter, StreamEvent, ToolCallInfo

logger = logging.getLogger("meetyou.adapter.ollama")


class OllamaAdapter(LLMAdapter):
    """Ollama Chat API 适配器"""

    async def query_model_context_limit(self, session, base_url: str, model: str) -> int | None:
        """通过 /api/show 查询模型实际上下文长度"""
        try:
            show_url = base_url.split("/api/")[0] + "/api/show"
            async with session.post(show_url, json={"name": model}) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                # 尝试从 model_info 中获取
                for key, val in data.get("model_info", {}).items():
                    if "context_length" in key:
                        return int(val)
                # 尝试从 parameters 文本中解析
                params = data.get("parameters", "")
                for line in params.split("\n"):
                    if "num_ctx" in line:
                        return int(line.split()[-1])
        except Exception as e:
            logger.debug(f"查询 Ollama 模型信息失败: {e}")
        return None

    def format_messages(self, messages: list[dict]) -> list[dict]:
        formatted = []
        for msg in messages:
            role = msg["role"]
            content = msg.get("content")
            new_msg = {"role": role}

            if isinstance(content, list):
                text_parts = []
                images = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        text_parts.append(part["text"])
                    elif part.get("type") == "image":
                        images.append(part.get("image_data", ""))
                new_msg["content"] = " ".join(text_parts)
                if images:
                    new_msg["images"] = images
            else:
                new_msg["content"] = content or ""

            if role == "assistant" and msg.get("tool_calls"):
                new_msg["tool_calls"] = []
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    new_msg["tool_calls"].append({
                        "function": {
                            "name": fn.get("name", ""),
                            "arguments": json.loads(fn.get("arguments", "{}")),
                        }
                    })

            formatted.append(new_msg)
        return formatted

    def format_tools(self, tools: list[dict]) -> list[dict] | None:
        return tools if tools else None

    async def stream_chat(
        self, session, url, api_key, model, messages, tools=None, **kwargs
    ) -> AsyncGenerator[StreamEvent, None]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "messages": self.format_messages(messages),
            "stream": True,
        }
        ft = self.format_tools(tools)
        if ft:
            payload["tools"] = ft
        payload.update(kwargs)

        tool_calls: list[ToolCallInfo] = []

        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.content:
                raw = line.decode("utf-8").strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue

                message = data.get("message", {})
                text = message.get("content")
                if text:
                    yield StreamEvent(type="text", text=text)

                if "tool_calls" in message:
                    for tc in message["tool_calls"]:
                        fn = tc.get("function", {})
                        tool_calls.append(ToolCallInfo(
                            id=f"call_{len(tool_calls)}",
                            name=fn.get("name", ""),
                            arguments_str=json.dumps(fn.get("arguments", {})),
                        ))

                if data.get("done"):
                    break

        if tool_calls:
            yield StreamEvent(type="tool_calls", tool_calls=tool_calls)
        yield StreamEvent(type="done")

    async def chat(self, session, url, api_key, model, messages, tools=None, **kwargs) -> dict:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

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

        message = data.get("message", {})
        result = {"content": message.get("content", ""), "tool_calls": []}

        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                fn = tc.get("function", {})
                result["tool_calls"].append(ToolCallInfo(
                    id=f"call_{len(result['tool_calls'])}",
                    name=fn.get("name", ""),
                    arguments_str=json.dumps(fn.get("arguments", {})),
                ))
        return result
