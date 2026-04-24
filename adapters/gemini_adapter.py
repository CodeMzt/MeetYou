"""
Google Gemini generateContent adapter.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

from adapters.base import LLMAdapter, StreamEvent, ToolCallInfo

logger = logging.getLogger("meetyou.adapter.gemini")


def _gemini_usage(payload: dict | None) -> dict | None:
    payload = payload or {}
    usage = payload.get("usageMetadata") or {}
    if not usage:
        return None
    prompt_tokens = int(usage.get("promptTokenCount", 0) or 0)
    completion_tokens = int(usage.get("candidatesTokenCount", 0) or 0)
    reasoning_tokens = int(usage.get("thoughtsTokenCount", 0) or 0)
    total_tokens = int(
        usage.get("totalTokenCount", 0)
        or (prompt_tokens + completion_tokens + reasoning_tokens)
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
    }


class GeminiAdapter(LLMAdapter):
    provider_name = "gemini"

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

            if role == "tool":
                parts.append(
                    {
                        "functionResponse": {
                            "name": msg.get("tool_call_name", "function"),
                            "response": {
                                "result": content if isinstance(content, str) else str(content),
                            },
                        }
                    }
                )
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        parts.append({"text": part["text"]})
                    elif part.get("type") == "image":
                        parts.append(
                            {
                                "inlineData": {
                                    "mimeType": part.get("mime_type", "image/png"),
                                    "data": part.get("image_data", ""),
                                }
                            }
                        )
            elif role == "assistant" and msg.get("tool_calls"):
                if content:
                    parts.append({"text": content})
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    parts.append(
                        {
                            "functionCall": {
                                "name": fn.get("name", ""),
                                "args": json.loads(fn.get("arguments", "{}")),
                            }
                        }
                    )
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
            decl = {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
            }
            params = fn.get("parameters")
            if params:
                decl["parameters"] = params
            declarations.append(decl)
        return [{"functionDeclarations": declarations}]

    def _apply_thinking(self, payload: dict, **kwargs) -> None:
        thinking_enabled = kwargs.pop("thinking", None)
        thinking_effort = kwargs.pop("thinking_effort", None)
        thinking_budget = kwargs.pop("thinking_budget", None)

        generation_config = payload.setdefault("generationConfig", {})
        if thinking_enabled is False:
            generation_config["thinkingConfig"] = {
                "thinkingBudget": 0,
                "includeThoughts": False,
            }
        elif thinking_enabled:
            thinking_config = {"includeThoughts": True}
            if thinking_budget is not None:
                thinking_config["thinkingBudget"] = int(thinking_budget)
            elif thinking_effort == "low":
                thinking_config["thinkingBudget"] = 256
            elif thinking_effort == "medium":
                thinking_config["thinkingBudget"] = 1024
            elif thinking_effort == "high":
                thinking_config["thinkingBudget"] = 2048
            generation_config["thinkingConfig"] = thinking_config

        payload.update(kwargs)

    async def stream_chat(
        self,
        session,
        url,
        api_key,
        model,
        messages,
        tools=None,
        cancel_event=None,
        **kwargs,
    ) -> AsyncGenerator[StreamEvent, None]:
        api_url = self._build_url(url, model, stream=True, api_key=api_key)
        msg_data = self.format_messages(messages)

        payload = {"contents": msg_data["contents"]}
        if msg_data["system_instruction"]:
            payload["systemInstruction"] = msg_data["system_instruction"]
        ft = self.format_tools(tools)
        if ft:
            payload["tools"] = ft
        self._apply_thinking(payload, **kwargs)

        headers = {"Content-Type": "application/json"}
        tool_calls: list[ToolCallInfo] = []

        async with session.post(api_url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.content:
                if cancel_event is not None and cancel_event.is_set():
                    break
                raw = line.decode("utf-8").strip()
                if not raw.startswith("data:"):
                    continue
                try:
                    data = json.loads(raw[5:].strip())
                except (json.JSONDecodeError, ValueError):
                    continue

                usage = _gemini_usage(data)
                if usage:
                    yield StreamEvent(type="usage", usage=usage)

                for cand in data.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        if "text" in part:
                            if part.get("thought"):
                                yield StreamEvent(type="reasoning", reasoning_text=part["text"])
                            else:
                                yield StreamEvent(type="text", text=part["text"])
                        elif "functionCall" in part:
                            fc = part["functionCall"]
                            tool_calls.append(
                                ToolCallInfo(
                                    id=f"call_{len(tool_calls)}",
                                    name=fc.get("name", ""),
                                    arguments_str=json.dumps(fc.get("args", {})),
                                )
                            )

        if cancel_event is None or not cancel_event.is_set():
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
        self._apply_thinking(payload, **kwargs)

        headers = {"Content-Type": "application/json"}
        async with session.post(api_url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()

        result = {"content": "", "tool_calls": [], "usage": _gemini_usage(data)}
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                if "text" in part and not part.get("thought"):
                    result["content"] += part["text"]
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    result["tool_calls"].append(
                        ToolCallInfo(
                            id=f"call_{len(result['tool_calls'])}",
                            name=fc.get("name", ""),
                            arguments_str=json.dumps(fc.get("args", {})),
                        )
                    )
        return result
