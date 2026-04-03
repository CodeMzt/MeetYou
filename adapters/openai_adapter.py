"""
Official OpenAI Responses adapter with OpenAI-compatible chat-completions fallback.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator
from urllib.parse import urlparse, urlunparse

from adapters.base import LLMAdapter, StreamEvent, ToolCallInfo

logger = logging.getLogger("meetyou.adapter.openai")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _extract_chat_usage(payload: dict | None) -> dict | None:
    payload = payload or {}
    usage = payload.get("usage") or {}
    if not usage:
        return None
    completion_details = usage.get("completion_tokens_details") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "reasoning_tokens": int(completion_details.get("reasoning_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def _extract_responses_usage(payload: dict | None) -> dict | None:
    payload = payload or {}
    usage = payload.get("usage") or {}
    if not usage:
        return None

    prompt_tokens = int(
        usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
    )
    completion_tokens = int(
        usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
    )
    output_details = (
        usage.get("output_tokens_details")
        or usage.get("completion_tokens_details")
        or {}
    )
    reasoning_tokens = int(
        output_details.get("reasoning_tokens", usage.get("reasoning_tokens", 0)) or 0
    )
    total_tokens = int(
        usage.get("total_tokens", 0)
        or (prompt_tokens + completion_tokens + reasoning_tokens)
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
    }


class OpenAIAdapter(LLMAdapter):
    def format_messages(self, messages: list[dict]) -> list[dict]:
        formatted = []
        for msg in messages:
            new_msg = {"role": msg["role"]}
            content = msg.get("content")

            if isinstance(content, list):
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
                            parts.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{mime};base64,{img}"},
                                }
                            )
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

    @staticmethod
    def _supports_stream_usage(url: str, model: str) -> bool:
        url = str(url or "").lower()
        model = str(model or "").lower()
        return "openai.com" in url or model.startswith(("gpt-", "o"))

    @staticmethod
    def _is_official_openai(url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        return (parsed.hostname or "").lower() == "api.openai.com"

    @staticmethod
    def _normalize_official_url(url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        if not parsed.scheme:
            return "https://api.openai.com/v1/responses"
        return urlunparse(parsed._replace(path="/v1/responses"))

    @staticmethod
    def _stringify_content(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        return _json_dumps(content)

    def _format_responses_content_parts(self, content: list[dict]) -> list[dict]:
        parts: list[dict] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                parts.append({"type": "input_text", "text": part.get("text", "")})
            elif part.get("type") == "image":
                img = part.get("image_data", "")
                mime = part.get("mime_type", "image/png")
                image_url = img if img.startswith("http") else f"data:{mime};base64,{img}"
                parts.append({"type": "input_image", "image_url": image_url})
        return parts

    def _format_responses_input(self, messages: list[dict]) -> dict[str, Any]:
        instructions: list[str] = []
        input_items: list[dict[str, Any]] = []

        for msg in messages:
            role = str(msg.get("role") or "user")
            content = msg.get("content")

            if role == "system":
                text = self._stringify_content(content)
                if text:
                    instructions.append(text)
                continue

            if role == "tool":
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": msg.get("tool_call_id", ""),
                        "output": self._stringify_content(content),
                    }
                )
                continue

            if role == "assistant" and isinstance(msg.get("provider_items"), list):
                input_items.extend(
                    item
                    for item in msg["provider_items"]
                    if isinstance(item, dict) and item.get("type") in {"reasoning", "function_call"}
                )
                continue

            if role == "assistant" and msg.get("tool_calls"):
                text = self._stringify_content(content)
                if text:
                    input_items.append({"role": "assistant", "content": text})
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    input_items.append(
                        {
                            "type": "function_call",
                            "call_id": tc.get("id", ""),
                            "name": fn.get("name", ""),
                            "arguments": fn.get("arguments", "{}") or "{}",
                        }
                    )
                continue

            if isinstance(content, list):
                parts = self._format_responses_content_parts(content)
                input_items.append({"role": role, "content": parts})
            else:
                input_items.append({"role": role, "content": self._stringify_content(content)})

        return {
            "instructions": "\n\n".join(instructions) if instructions else None,
            "input": input_items,
        }

    def _format_responses_tools(self, tools: list[dict]) -> list[dict] | None:
        if not tools:
            return None
        formatted = []
        for tool in tools:
            fn = tool.get("function", {})
            formatted.append(
                {
                    "type": "function",
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                }
            )
        return formatted

    def _apply_chat_reasoning_options(self, payload: dict, model: str, **kwargs) -> None:
        thinking = kwargs.pop("thinking", None)
        effort = kwargs.pop("thinking_effort", None)
        kwargs.pop("thinking_budget", None)

        if effort:
            payload["reasoning_effort"] = effort
        elif thinking is False and str(model or "").lower().startswith("gpt-5"):
            payload["reasoning_effort"] = "none"

        payload.update(kwargs)

    def _apply_responses_reasoning_options(self, payload: dict, **kwargs) -> None:
        thinking = kwargs.pop("thinking", None)
        effort = kwargs.pop("thinking_effort", None)
        kwargs.pop("thinking_budget", None)

        if thinking is False:
            payload["reasoning"] = {"effort": "none"}
        elif thinking:
            payload["reasoning"] = {
                "effort": effort or "medium",
                "summary": "concise",
            }
            include = payload.setdefault("include", [])
            if "reasoning.encrypted_content" not in include:
                include.append("reasoning.encrypted_content")

        payload.update(kwargs)

    @staticmethod
    def _provider_item_key(item: dict[str, Any]) -> str:
        return str(
            item.get("id")
            or item.get("call_id")
            or f"{item.get('type', 'item')}:{json.dumps(item, sort_keys=True, ensure_ascii=False)}"
        )

    @staticmethod
    def _stream_event_key(data: dict[str, Any]) -> tuple[str, ...]:
        return (
            str(data.get("item_id") or data.get("id") or ""),
            str(data.get("output_index", "")),
            str(data.get("content_index", "")),
            str(data.get("summary_index", "")),
        )

    async def _iter_sse_payloads(self, response) -> AsyncGenerator[dict[str, Any], None]:
        event_lines: list[str] = []

        def parse_payload() -> dict[str, Any] | None:
            payload = "\n".join(event_lines).strip()
            if not payload:
                return None
            if payload == "[DONE]":
                return {"__done__": True}
            try:
                return json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                return None

        async for raw_line in response.content:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if not line:
                if not event_lines:
                    continue
                parsed = parse_payload()
                event_lines.clear()
                if parsed is None:
                    continue
                if parsed.get("__done__"):
                    break
                yield parsed
                continue

            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                event_lines.append(line[5:].strip())
                parsed = parse_payload()
                if parsed is None:
                    continue
                event_lines.clear()
                if parsed.get("__done__"):
                    break
                yield parsed

        if event_lines:
            parsed = parse_payload()
            if parsed is not None and not parsed.get("__done__"):
                yield parsed

    @staticmethod
    def _extract_reasoning_texts(item: dict[str, Any] | None) -> list[str]:
        if not isinstance(item, dict) or item.get("type") != "reasoning":
            return []

        texts: list[str] = []
        for part in item.get("summary") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "summary_text" and part.get("text"):
                texts.append(str(part["text"]))

        if texts:
            return texts

        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") in {"reasoning_text", "summary_text", "text"} and part.get("text"):
                texts.append(str(part["text"]))
        return texts

    def _add_provider_item(
        self,
        provider_items: dict[str, dict[str, Any]],
        item: dict[str, Any] | None,
    ) -> None:
        if not isinstance(item, dict):
            return
        if item.get("type") not in {"reasoning", "function_call"}:
            return
        provider_items[self._provider_item_key(item)] = item

    @staticmethod
    def _record_response_tool_call(
        tool_calls_acc: dict[str, ToolCallInfo],
        item: dict[str, Any] | None,
    ) -> None:
        if not isinstance(item, dict) or item.get("type") != "function_call":
            return

        state_key = str(item.get("id") or item.get("call_id") or f"call_{len(tool_calls_acc)}")
        tool_call = tool_calls_acc.get(state_key, ToolCallInfo())
        tool_call.id = str(item.get("call_id") or item.get("id") or tool_call.id or state_key)
        tool_call.name = str(item.get("name") or tool_call.name or "")

        arguments = item.get("arguments")
        if isinstance(arguments, str):
            tool_call.arguments_str = arguments
        elif arguments is not None:
            tool_call.arguments_str = _json_dumps(arguments)

        tool_calls_acc[state_key] = tool_call

    async def _stream_responses(
        self,
        session,
        url,
        api_key,
        model,
        messages,
        tools=None,
        **kwargs,
    ) -> AsyncGenerator[StreamEvent, None]:
        request_url = self._normalize_official_url(url)
        msg_data = self._format_responses_input(messages)
        payload = {
            "model": model,
            "input": msg_data["input"],
            "stream": True,
        }
        if msg_data["instructions"]:
            payload["instructions"] = msg_data["instructions"]
        ft = self._format_responses_tools(tools)
        if ft:
            payload["tools"] = ft
        self._apply_responses_reasoning_options(payload, **kwargs)

        logger.info("Using official OpenAI Responses API at %s", request_url)
        if payload.get("reasoning"):
            logger.info("Official OpenAI summary mode enabled for model %s", model)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        tool_calls_acc: dict[str, ToolCallInfo] = {}
        provider_items: dict[str, dict[str, Any]] = {}
        output_text_delta_keys: set[tuple[str, ...]] = set()
        reasoning_summary_delta_keys: set[tuple[str, ...]] = set()
        reasoning_requested = bool(payload.get("reasoning"))
        saw_reasoning_summary = False

        async with session.post(request_url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for data in self._iter_sse_payloads(resp):
                event_type = data.get("type", "")
                if event_type == "response.output_text.delta":
                    output_text_delta_keys.add(self._stream_event_key(data))
                    text = data.get("delta") or data.get("text") or ""
                    if text:
                        yield StreamEvent(type="text", text=text)
                    continue

                if event_type == "response.output_text.done":
                    key = self._stream_event_key(data)
                    text = data.get("text") or ""
                    if key not in output_text_delta_keys and text:
                        yield StreamEvent(type="text", text=text)
                    continue

                if event_type == "response.reasoning_summary_text.delta":
                    reasoning_summary_delta_keys.add(self._stream_event_key(data))
                    reasoning_text = data.get("delta") or data.get("text") or ""
                    if reasoning_text:
                        saw_reasoning_summary = True
                        yield StreamEvent(type="reasoning", reasoning_text=reasoning_text)
                    continue

                if event_type == "response.reasoning_summary_text.done":
                    key = self._stream_event_key(data)
                    reasoning_text = data.get("text") or ""
                    if key not in reasoning_summary_delta_keys and reasoning_text:
                        saw_reasoning_summary = True
                        yield StreamEvent(type="reasoning", reasoning_text=reasoning_text)
                    continue

                if event_type == "response.output_item.added":
                    self._record_response_tool_call(tool_calls_acc, data.get("item"))
                    continue

                if event_type == "response.function_call_arguments.delta":
                    item_id = str(data.get("item_id") or "")
                    if item_id:
                        tool_call = tool_calls_acc.get(item_id, ToolCallInfo(id=item_id))
                        tool_call.arguments_str += str(data.get("delta") or "")
                        tool_calls_acc[item_id] = tool_call
                    continue

                if event_type == "response.output_item.done":
                    item = data.get("item") or {}
                    self._record_response_tool_call(tool_calls_acc, item)
                    self._add_provider_item(provider_items, item)
                    if not saw_reasoning_summary:
                        fallback_reasoning = self._extract_reasoning_texts(item)
                        if fallback_reasoning:
                            saw_reasoning_summary = True
                            for reasoning_text in fallback_reasoning:
                                yield StreamEvent(type="reasoning", reasoning_text=reasoning_text)
                    continue

                if event_type == "response.completed":
                    response = data.get("response") or data
                    for item in response.get("output") or []:
                        self._record_response_tool_call(tool_calls_acc, item)
                        self._add_provider_item(provider_items, item)
                        if not saw_reasoning_summary:
                            fallback_reasoning = self._extract_reasoning_texts(item)
                            if fallback_reasoning:
                                saw_reasoning_summary = True
                                for reasoning_text in fallback_reasoning:
                                    yield StreamEvent(type="reasoning", reasoning_text=reasoning_text)
                    usage = _extract_responses_usage(response)
                    if usage:
                        yield StreamEvent(type="usage", usage=usage)
                    continue

                if event_type in {"response.failed", "error"}:
                    error = data.get("error") or {}
                    message = (
                        error.get("message")
                        or data.get("message")
                        or _json_dumps(error)
                        or "OpenAI Responses API error"
                    )
                    yield StreamEvent(type="error", error=message)

        if reasoning_requested and not saw_reasoning_summary:
            logger.info("Responses API returned no reasoning summary events for model %s", model)
        if provider_items:
            yield StreamEvent(type="provider_items", provider_items=list(provider_items.values()))
        if tool_calls_acc:
            yield StreamEvent(type="tool_calls", tool_calls=list(tool_calls_acc.values()))
        yield StreamEvent(type="done")

    async def stream_chat(
        self,
        session,
        url,
        api_key,
        model,
        messages,
        tools=None,
        **kwargs,
    ) -> AsyncGenerator[StreamEvent, None]:
        if self._is_official_openai(url):
            async for event in self._stream_responses(
                session,
                url,
                api_key,
                model,
                messages,
                tools,
                **kwargs,
            ):
                yield event
            return

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
        if self._supports_stream_usage(url, model):
            payload["stream_options"] = {"include_usage": True}
        self._apply_chat_reasoning_options(payload, model, **kwargs)

        tool_calls_acc: dict[int, ToolCallInfo] = {}

        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for data in self._iter_sse_payloads(resp):
                usage = _extract_chat_usage(data)
                if usage:
                    yield StreamEvent(type="usage", usage=usage)

                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}

                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if isinstance(reasoning, str) and reasoning:
                    yield StreamEvent(type="reasoning", reasoning_text=reasoning)

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

        if self._is_official_openai(url):
            request_url = self._normalize_official_url(url)
            msg_data = self._format_responses_input(messages)
            payload = {
                "model": model,
                "input": msg_data["input"],
                "stream": False,
            }
            if msg_data["instructions"]:
                payload["instructions"] = msg_data["instructions"]
            ft = self._format_responses_tools(tools)
            if ft:
                payload["tools"] = ft
            self._apply_responses_reasoning_options(payload, **kwargs)

            async with session.post(request_url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()

            tool_calls_acc: dict[str, ToolCallInfo] = {}
            provider_items: dict[str, dict[str, Any]] = {}
            content = ""
            for item in data.get("output") or []:
                self._record_response_tool_call(tool_calls_acc, item)
                self._add_provider_item(provider_items, item)
                if item.get("type") == "message":
                    for part in item.get("content") or []:
                        if part.get("type") in {"output_text", "text"}:
                            content += str(part.get("text") or "")

            result = {
                "content": content,
                "tool_calls": list(tool_calls_acc.values()),
                "usage": _extract_responses_usage(data),
            }
            if provider_items:
                result["provider_items"] = list(provider_items.values())
            return result

        payload = {
            "model": model,
            "messages": self.format_messages(messages),
            "stream": False,
        }
        ft = self.format_tools(tools)
        if ft:
            payload["tools"] = ft
        self._apply_chat_reasoning_options(payload, model, **kwargs)

        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()

        choices = data.get("choices") or []
        if not choices:
            return {
                "content": "",
                "tool_calls": [],
                "usage": _extract_chat_usage(data),
            }

        message = choices[0].get("message") or {}
        result = {
            "content": message.get("content") or "",
            "tool_calls": [],
            "usage": _extract_chat_usage(data),
        }

        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                fn = tc.get("function", {})
                result["tool_calls"].append(
                    ToolCallInfo(
                        id=tc.get("id", ""),
                        name=fn.get("name", ""),
                        arguments_str=fn.get("arguments", "{}"),
                    )
                )
        return result
