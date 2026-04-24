"""
Official OpenAI Responses adapter with OpenAI-compatible chat-completions fallback.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any, AsyncGenerator
from urllib.parse import urlparse, urlunparse

from adapters.base import LLMAdapter, StreamEvent, ToolCallInfo

logger = logging.getLogger("meetyou.adapter.openai")


class ProviderRequestError(RuntimeError):
    def __init__(self, payload: dict[str, Any]):
        self.runtime_error_payload = dict(payload)
        super().__init__(str(payload.get("message") or "Provider request failed"))


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


def _safe_lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _extract_error_message(error_body: dict[str, Any] | None, status: int) -> str:
    payload = error_body or {}
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message:
            return message
    message = str(payload.get("message") or "").strip()
    if message:
        return message
    return f"HTTP {status}"


class OpenAIAdapter(LLMAdapter):
    provider_name = "openai"

    @staticmethod
    def _assistant_call_ids(message: dict[str, Any]) -> list[str]:
        call_ids: list[str] = []
        for tool_call in message.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            call_id = str(tool_call.get("id") or "").strip()
            if call_id:
                call_ids.append(call_id)
        if call_ids:
            return call_ids

        for provider_item in message.get("provider_items") or []:
            if not isinstance(provider_item, dict) or provider_item.get("type") != "function_call":
                continue
            call_id = str(provider_item.get("call_id") or provider_item.get("id") or "").strip()
            if call_id:
                call_ids.append(call_id)
        return call_ids

    @classmethod
    def _sanitize_tool_message_history(cls, messages: list[dict]) -> list[dict]:
        sanitized: list[dict] = []
        pending_assistant: dict[str, Any] | None = None
        pending_call_ids: list[str] = []
        pending_tool_messages: list[dict[str, Any]] = []
        seen_tool_call_ids: set[str] = set()

        def drop_pending() -> None:
            nonlocal pending_assistant, pending_call_ids, pending_tool_messages, seen_tool_call_ids
            pending_assistant = None
            pending_call_ids = []
            pending_tool_messages = []
            seen_tool_call_ids = set()

        def flush_pending() -> None:
            if pending_assistant is None:
                return
            sanitized.append(pending_assistant)
            sanitized.extend(pending_tool_messages)
            drop_pending()

        for message in messages:
            if not isinstance(message, dict):
                continue

            role = str(message.get("role") or "")
            assistant_call_ids = cls._assistant_call_ids(message) if role == "assistant" else []
            if assistant_call_ids:
                drop_pending()
                pending_assistant = message
                pending_call_ids = assistant_call_ids
                pending_tool_messages = []
                seen_tool_call_ids = set()
                continue

            if pending_assistant is not None:
                if role != "tool":
                    drop_pending()
                    sanitized.append(message)
                    continue
                tool_call_id = str(message.get("tool_call_id") or "").strip()
                if tool_call_id in pending_call_ids and tool_call_id not in seen_tool_call_ids:
                    pending_tool_messages.append(message)
                    seen_tool_call_ids.add(tool_call_id)
                    if len(seen_tool_call_ids) == len(pending_call_ids):
                        flush_pending()
                continue

            if role == "tool":
                continue
            sanitized.append(message)

        return sanitized

    def _format_chat_messages(self, messages: list[dict], *, url: str = "", model: str = "") -> list[dict]:
        preserve_reasoning_content = self._supports_chat_reasoning_content_roundtrip(url, model)
        formatted = []
        for msg in self._sanitize_tool_message_history(messages):
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
                reasoning_content = msg.get("reasoning_content")
                if preserve_reasoning_content:
                    new_msg["reasoning_content"] = reasoning_content if isinstance(reasoning_content, str) else ""
            if "tool_call_id" in msg:
                new_msg["tool_call_id"] = msg["tool_call_id"]

            formatted.append(new_msg)
        return formatted

    def format_messages(self, messages: list[dict]) -> list[dict]:
        return self._format_chat_messages(messages)

    def format_tools(self, tools: list[dict]) -> list[dict] | None:
        return tools if tools else None

    @staticmethod
    def _supports_chat_reasoning_effort(url: str, model: str) -> bool:
        host = (urlparse(str(url or "").strip()).hostname or "").lower()
        normalized_model = str(model or "").strip().lower()
        return (
            host in {"api.openai.com", "api.deepseek.com"}
            or normalized_model.startswith(("gpt-", "o", "deepseek-"))
        )

    @staticmethod
    def _is_deepseek_family_model(model: str) -> bool:
        normalized_model = str(model or "").strip().lower()
        return (
            normalized_model.startswith("deepseek-")
            or normalized_model.startswith("deepseek/")
            or "/deepseek-" in normalized_model
        )

    @staticmethod
    def _supports_chat_reasoning_content_roundtrip(url: str, model: str) -> bool:
        host = (urlparse(str(url or "").strip()).hostname or "").lower()
        return host == "api.deepseek.com" or OpenAIAdapter._is_deepseek_family_model(model)

    @staticmethod
    def _backfill_tool_reasoning_content(payload: dict[str, Any]) -> bool:
        """DeepSeek thinking mode requires this field on assistant tool-call turns."""
        changed = False
        for message in payload.get("messages") or []:
            if not isinstance(message, dict):
                continue
            if message.get("role") != "assistant" or not message.get("tool_calls"):
                continue
            if not isinstance(message.get("reasoning_content"), str):
                message["reasoning_content"] = ""
                changed = True
        return changed

    @classmethod
    def _ensure_chat_reasoning_content_roundtrip(cls, payload: dict[str, Any], *, url: str, model: str) -> bool:
        if not cls._supports_chat_reasoning_content_roundtrip(url, model):
            return False
        return cls._backfill_tool_reasoning_content(payload)

    @staticmethod
    def _supports_chat_thinking_toggle(url: str, model: str) -> bool:
        host = (urlparse(str(url or "").strip()).hostname or "").lower()
        return host == "api.deepseek.com" or OpenAIAdapter._is_deepseek_family_model(model)

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

        for msg in self._sanitize_tool_message_history(messages):
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
        request_url = str(kwargs.pop("request_url", "") or "")
        thinking = kwargs.pop("thinking", None)
        effort = kwargs.pop("thinking_effort", None)
        kwargs.pop("thinking_budget", None)

        if effort and self._supports_chat_reasoning_effort(request_url, model):
            payload["reasoning_effort"] = effort
        elif thinking is False and self._supports_chat_reasoning_effort(request_url, model):
            payload["reasoning_effort"] = "none"

        if thinking is not None and self._supports_chat_thinking_toggle(request_url, model):
            payload["thinking"] = {"type": "enabled" if bool(thinking) else "disabled"}

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

    @staticmethod
    async def _read_error_body(response) -> dict[str, Any]:
        json_loader = getattr(response, "json", None)
        if callable(json_loader):
            try:
                payload = await json_loader()
                if isinstance(payload, dict):
                    return payload
            except Exception:
                pass
        text_loader = getattr(response, "text", None)
        if callable(text_loader):
            try:
                return {"message": await text_loader()}
            except Exception:
                pass
        return {}

    @staticmethod
    def _extract_invalid_parameter(error_body: dict[str, Any] | None, message: str) -> str:
        payload = error_body or {}
        error = payload.get("error")
        candidates = []
        if isinstance(error, dict):
            candidates.extend(
                [
                    error.get("param"),
                    error.get("parameter"),
                    error.get("field"),
                ]
            )
        candidates.extend(
            [
                payload.get("param"),
                payload.get("parameter"),
                payload.get("field"),
            ]
        )
        for candidate in candidates:
            value = str(candidate or "").strip()
            if value:
                return value
        lowered = _safe_lower(message)
        for field_name in ("stream_options", "reasoning_effort", "reasoning", "tools", "messages"):
            if field_name in lowered:
                return field_name
        return ""

    def _classify_error_payload(
        self,
        *,
        url: str,
        status: int,
        error_body: dict[str, Any] | None,
        request_payload: dict[str, Any],
        model: str,
    ) -> dict[str, Any]:
        parsed = urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        provider_mode = "official_openai_responses" if self._is_official_openai(url) else "openai_compatible_chat"
        message = _extract_error_message(error_body, status)
        lowered = _safe_lower(message)
        invalid_parameter = self._extract_invalid_parameter(error_body, message)

        code = "provider_request_failed"
        category = "dependency"
        retryable = status in {408, 409, 429} or status >= 500

        if status in {401, 403} or any(
            token in lowered
            for token in ("api key", "authentication", "unauthorized", "forbidden", "invalid key", "incorrect api key")
        ):
            code = "provider_auth_failed"
        elif status == 429 or "rate limit" in lowered:
            code = "provider_rate_limited"
            retryable = True
        elif any(
            token in lowered
            for token in (
                "maximum context length",
                "context length",
                "context window",
                "too many tokens",
                "prompt is too long",
                "reduce the length",
                "token limit",
            )
        ):
            code = "provider_context_limit_exceeded"
            category = "validation"
            retryable = False
        elif status in {400, 404, 422} and any(
            token in lowered
            for token in (
                "unknown parameter",
                "unsupported parameter",
                "unsupported field",
                "unexpected field",
                "invalid field",
                "extra fields not permitted",
                "invalid_request_error",
                "invalid request",
            )
        ):
            code = "provider_invalid_request_fields"
            category = "validation"
            retryable = False
        elif status in {400, 422}:
            code = "provider_bad_request"
            category = "validation"
            retryable = False
        elif status >= 500:
            code = "provider_upstream_unavailable"
            retryable = True

        details = {
            "provider_host": host,
            "provider_path": path,
            "provider_mode": provider_mode,
            "status_code": int(status),
            "model": str(model or ""),
            "request_message_count": len(request_payload.get("messages") or request_payload.get("input") or []),
            "request_has_tools": bool(request_payload.get("tools")),
            "request_has_stream_options": bool(request_payload.get("stream_options")),
            "request_has_reasoning_effort": "reasoning_effort" in request_payload,
            "request_has_reasoning": "reasoning" in request_payload,
            "invalid_parameter": invalid_parameter,
            "provider_error_type": str((error_body or {}).get("type") or ((error_body or {}).get("error") or {}).get("type") or ""),
        }
        return {
            "code": code,
            "category": category,
            "message": message,
            "retryable": retryable,
            "details": details,
        }

    def _build_retry_payload_for_compatible_400(
        self,
        payload: dict[str, Any],
        error_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        message = str(error_payload.get("message") or "").lower()
        if "reasoning_content" in message and "must be passed back" in message:
            next_payload = deepcopy(payload)
            if self._backfill_tool_reasoning_content(next_payload):
                return next_payload

        if str(error_payload.get("code") or "") != "provider_invalid_request_fields":
            return None
        next_payload = dict(payload)
        removed = False
        for key in ("stream_options", "reasoning_effort", "thinking"):
            if key in next_payload:
                next_payload.pop(key, None)
                removed = True
        return next_payload if removed else None

    async def _raise_http_error(self, response, *, url: str, request_payload: dict[str, Any], model: str) -> None:
        payload = self._classify_error_payload(
            url=url,
            status=int(getattr(response, "status", 0) or 0),
            error_body=await self._read_error_body(response),
            request_payload=request_payload,
            model=model,
        )
        raise ProviderRequestError(payload)

    async def _stream_chat_completions_once(
        self,
        session,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        model: str,
    ) -> AsyncGenerator[StreamEvent, None]:
        tool_calls_acc: dict[int, ToolCallInfo] = {}

        async with session.post(url, headers=headers, json=payload) as resp:
            if int(getattr(resp, "status", 200) or 200) >= 400:
                await self._raise_http_error(resp, url=url, request_payload=payload, model=model)
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

    async def _chat_completions_once(
        self,
        session,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        model: str,
    ) -> dict[str, Any]:
        async with session.post(url, headers=headers, json=payload) as resp:
            if int(getattr(resp, "status", 200) or 200) >= 400:
                await self._raise_http_error(resp, url=url, request_payload=payload, model=model)
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
        reasoning_content = message.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content:
            result["reasoning_content"] = reasoning_content

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
            if int(getattr(resp, "status", 200) or 200) >= 400:
                await self._raise_http_error(resp, url=request_url, request_payload=payload, model=model)
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
        cancel_event=None,
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
                if cancel_event is not None and cancel_event.is_set():
                    break
                yield event
            return

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": self._format_chat_messages(messages, url=url, model=model),
            "stream": True,
        }
        ft = self.format_tools(tools)
        if ft:
            payload["tools"] = ft
        payload["stream_options"] = {"include_usage": True}
        self._apply_chat_reasoning_options(payload, model, request_url=url, **kwargs)
        self._ensure_chat_reasoning_content_roundtrip(payload, url=url, model=model)

        try:
            async for event in self._stream_chat_completions_once(
                session,
                url=url,
                headers=headers,
                payload=payload,
                model=model,
            ):
                if cancel_event is not None and cancel_event.is_set():
                    break
                yield event
        except ProviderRequestError as exc:
            retry_payload = self._build_retry_payload_for_compatible_400(payload, exc.runtime_error_payload)
            if retry_payload is None:
                raise
            logger.warning(
                "Retrying OpenAI-compatible request without optional fields for %s%s after %s",
                (urlparse(str(url or "").strip()).hostname or "").lower(),
                urlparse(str(url or "").strip()).path or "",
                exc.runtime_error_payload.get("code"),
            )
            async for event in self._stream_chat_completions_once(
                session,
                url=url,
                headers=headers,
                payload=retry_payload,
                model=model,
            ):
                if cancel_event is not None and cancel_event.is_set():
                    break
                yield event

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
                if int(getattr(resp, "status", 200) or 200) >= 400:
                    await self._raise_http_error(resp, url=request_url, request_payload=payload, model=model)
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
            "messages": self._format_chat_messages(messages, url=url, model=model),
            "stream": False,
        }
        ft = self.format_tools(tools)
        if ft:
            payload["tools"] = ft
        self._apply_chat_reasoning_options(payload, model, request_url=url, **kwargs)
        self._ensure_chat_reasoning_content_roundtrip(payload, url=url, model=model)

        try:
            return await self._chat_completions_once(
                session,
                url=url,
                headers=headers,
                payload=payload,
                model=model,
            )
        except ProviderRequestError as exc:
            retry_payload = self._build_retry_payload_for_compatible_400(payload, exc.runtime_error_payload)
            if retry_payload is None:
                raise
            logger.warning(
                "Retrying OpenAI-compatible non-stream request without optional fields for %s%s after %s",
                (urlparse(str(url or "").strip()).hostname or "").lower(),
                urlparse(str(url or "").strip()).path or "",
                exc.runtime_error_payload.get("code"),
            )
            return await self._chat_completions_once(
                session,
                url=url,
                headers=headers,
                payload=retry_payload,
                model=model,
            )
