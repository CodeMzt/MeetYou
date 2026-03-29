"""
Google Gemini generateContent API 适配器。

支持：
- SSE 流式分块响应
- functionCall / functionResponse 解析
- 多模态 (inlineData)
- systemInstruction 处理
"""

import json
import logging
from typing import AsyncGenerator

from adapters.base import LLMAdapter, StreamEvent, ToolCallInfo

logger = logging.getLogger("meetyou.adapter.gemini")


class GeminiAdapter(LLMAdapter):
    """Google Gemini API 适配器"""

    def _build_url(self, base_url: str, model: str, stream: bool, api_key: str) -> str:
        action = "streamGenerateContent" if stream else "generateContent"
        if "generateContent" in base_url or "streamGenerateContent" in base_url:
            url = base_url
        else:
            url = f"{base_url.rstrip('/')}/models/{model}:{action}"
        sep = "&" if "?" in url else "?"
        url += f"{sep}key={api_key}"
        if stream:
            url += "&alt=sse"
        return url

    def format_messages(self, messages: list[dict]) -> dict:
        """返回 {"system_instruction": dict|None, "contents": list}"""
        system_parts = []
        contents = []

        for msg in messages:
            role = msg["role"]
            content = msg.get("content")

            if role == "system":
                if isinstance(content, str) and content:
                    system_parts.append(content)
                continue

            gemini_role = "model" if role == "assistant" else "user"
            parts = []

            # tool response
            if role == "tool":
                parts.append({
                    "functionResponse": {
                        "name": msg.get("tool_call_name", "function"),
                        "response": {"result": content if isinstance(content, str) else str(content)},
                    }
                })
            # 多模态
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        parts.append({"text": part["text"]})
                    elif part.get("type") == "image":
                        parts.append({
                            "inlineData": {
                                "mimeType": part.get("mime_type", "image/png"),
                                "data": part.get("image_data", ""),
                            }
                        })
            # assistant with tool calls
            elif role == "assistant" and msg.get("tool_calls"):
                if content:
                    parts.append({"text": content})
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    parts.append({
                        "functionCall": {
                            "name": fn.get("name", ""),
                            "args": json.loads(fn.get("arguments", "{}")),
                        }
                    })
            else:
                parts.append({"text": content or ""})

            contents.append({"role": gemini_role, "parts": parts})

        sys_inst = None
        if system_parts:
            sys_inst = {"parts": [{"text": "\n\n".join(system_parts)}]}

        return {"system_instruction": sys_inst, "contents": contents}

    def format_tools(self, tools: list[dict]) -> list[dict] | None:
        if not tools:
            return None
        declarations = []
        for tool in tools:
            fn = tool.get("function", {})
            decl = {"name": fn.get("name", ""), "description": fn.get("description", "")}
            params = fn.get("parameters")
            if params:
                decl["parameters"] = params
            declarations.append(decl)
        return [{"functionDeclarations": declarations}]

    async def stream_chat(
        self, session, url, api_key, model, messages, tools=None, **kwargs
    ) -> AsyncGenerator[StreamEvent, None]:
        api_url = self._build_url(url, model, stream=True, api_key=api_key)
        msg_data = self.format_messages(messages)

        payload = {"contents": msg_data["contents"]}
        if msg_data["system_instruction"]:
            payload["systemInstruction"] = msg_data["system_instruction"]
        ft = self.format_tools(tools)
        if ft:
            payload["tools"] = ft
        payload.update(kwargs)

        headers = {"Content-Type": "application/json"}
        tool_calls: list[ToolCallInfo] = []

        async with session.post(api_url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.content:
                raw = line.decode("utf-8").strip()
                if not raw.startswith("data:"):
                    continue
                try:
                    data = json.loads(raw[5:].strip())
                except (json.JSONDecodeError, ValueError):
                    continue

                for cand in data.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        if "text" in part:
                            yield StreamEvent(type="text", text=part["text"])
                        elif "functionCall" in part:
                            fc = part["functionCall"]
                            tool_calls.append(ToolCallInfo(
                                id=f"call_{len(tool_calls)}",
                                name=fc.get("name", ""),
                                arguments_str=json.dumps(fc.get("args", {})),
                            ))

        if tool_calls:
            yield StreamEvent(type="tool_calls", tool_calls=tool_calls)
        yield StreamEvent(type="done")

    async def chat(self, session, url, api_key, model, messages, tools=None, **kwargs) -> dict:
        api_url = self._build_url(url, model, stream=False, api_key=api_key)
        msg_data = self.format_messages(messages)

        payload = {"contents": msg_data["contents"]}
        if msg_data["system_instruction"]:
            payload["systemInstruction"] = msg_data["system_instruction"]
        ft = self.format_tools(tools)
        if ft:
            payload["tools"] = ft
        payload.update(kwargs)

        headers = {"Content-Type": "application/json"}
        async with session.post(api_url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()

        result = {"content": "", "tool_calls": []}
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                if "text" in part:
                    result["content"] += part["text"]
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    result["tool_calls"].append(ToolCallInfo(
                        id=f"call_{len(result['tool_calls'])}",
                        name=fc.get("name", ""),
                        arguments_str=json.dumps(fc.get("args", {})),
                    ))
        return result
