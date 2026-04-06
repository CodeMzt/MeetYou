"""
Context management, token estimation, and history compaction.
"""

from __future__ import annotations

import json
import logging
from typing import Any


logger = logging.getLogger("meetyou.context")

_DEFAULT_PROVIDER_FAMILY = "generic"
_PROVIDER_LENGTH_POLICIES: dict[str, dict[str, Any]] = {
    "openai": {
        "reserve_ratio": 0.72,
        "response_ratio": 0.22,
        "min_response_tokens": 1024,
        "recent_history_turns": 8,
    },
    "anthropic": {
        "reserve_ratio": 0.78,
        "response_ratio": 0.18,
        "min_response_tokens": 768,
        "recent_history_turns": 10,
    },
    "gemini": {
        "reserve_ratio": 0.74,
        "response_ratio": 0.2,
        "min_response_tokens": 1024,
        "recent_history_turns": 8,
    },
    "generic": {
        "reserve_ratio": 0.75,
        "response_ratio": 0.2,
        "min_response_tokens": 768,
        "recent_history_turns": 8,
    },
}


class ContextManager:
    """
    Tracks short-term context, persisted summaries, and token estimates.
    """

    def __init__(self, memory, adapter, event_bus):
        self._memory = memory
        self._adapter = adapter
        self._event_bus = event_bus
        self.proprioception_info: dict = {
            "ui_info": "",
            "running_apps": [],
            "last_update_time": 0,
        }

    def set_adapter(self, adapter):
        self._adapter = adapter

    async def load_context(self, session_id: str = "") -> str:
        return await self._memory.load_working_summary(session_id=session_id)

    async def update_context(self, context: str, session_id: str = "", source=None) -> str:
        return await self._memory.update_working_summary(context, session_id=session_id)

    @staticmethod
    def estimate_text_tokens(text: str) -> int:
        return int(len(str(text or "")) / 1.8)

    @classmethod
    def _estimate_value_tokens(cls, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, str):
            return cls.estimate_text_tokens(value)
        try:
            return cls.estimate_text_tokens(json.dumps(value, ensure_ascii=False))
        except (TypeError, ValueError):
            return cls.estimate_text_tokens(str(value))

    @classmethod
    def estimate_message_tokens(cls, message: dict) -> int:
        total_tokens = cls._estimate_value_tokens(message.get("content", ""))
        total_tokens += cls._estimate_value_tokens(message.get("tool_calls"))
        total_tokens += cls._estimate_value_tokens(message.get("provider_items"))
        total_tokens += cls._estimate_value_tokens(message.get("tool_call_id"))
        return total_tokens

    @classmethod
    def estimate_tokens(cls, messages: list[dict]) -> int:
        return sum(cls.estimate_message_tokens(msg) for msg in messages)

    def get_context_limit(self, model_name: str) -> int:
        return self._adapter.get_context_limit(model_name)

    @staticmethod
    def _normalize_conversation_summary(summary: str) -> str:
        text = str(summary or "").strip()
        return text if text and text != "当前没有暂存的上下文信息。" else ""

    @staticmethod
    def _provider_family(provider_name: str = "", api_url: str = "") -> str:
        provider_text = str(provider_name or "").strip().lower()
        if provider_text in {"openai", "anthropic", "gemini"}:
            return provider_text
        url_text = str(api_url or "").strip().lower()
        if "anthropic" in url_text or "claude" in url_text:
            return "anthropic"
        if "gemini" in url_text or "googleapis" in url_text:
            return "gemini"
        if "openai" in url_text:
            return "openai"
        return _DEFAULT_PROVIDER_FAMILY

    def build_length_policy(
        self,
        *,
        model: str,
        provider_name: str = "",
        api_url: str = "",
        context_limit_override: int | None = None,
    ) -> dict[str, Any]:
        context_limit = int(context_limit_override or 0) or self.get_context_limit(model)
        provider_family = self._provider_family(provider_name=provider_name, api_url=api_url)
        provider_policy = dict(_PROVIDER_LENGTH_POLICIES.get(provider_family, _PROVIDER_LENGTH_POLICIES[_DEFAULT_PROVIDER_FAMILY]))
        reserve_ratio = float(provider_policy.get("reserve_ratio", 0.75) or 0.75)
        response_ratio = float(provider_policy.get("response_ratio", 0.2) or 0.2)
        min_response_tokens = int(provider_policy.get("min_response_tokens", 768) or 768)
        reserved_response_tokens = max(min_response_tokens, int(context_limit * response_ratio))
        target_input_tokens = max(512, min(int(context_limit * reserve_ratio), context_limit - reserved_response_tokens))
        return {
            "provider_family": provider_family,
            "model": str(model or ""),
            "context_limit_tokens": context_limit,
            "target_input_tokens": target_input_tokens,
            "reserved_response_tokens": reserved_response_tokens,
            "reserve_ratio": reserve_ratio,
            "recent_history_turns": int(provider_policy.get("recent_history_turns", 8) or 8),
            "budgets": {
                "system": max(256, int(target_input_tokens * 0.16)),
                "conversation_summary": max(192, int(target_input_tokens * 0.12)),
                "memory": max(192, int(target_input_tokens * 0.14)),
                "policy": max(256, int(target_input_tokens * 0.16)),
                "history": max(256, int(target_input_tokens * 0.26)),
                "tool_history": max(128, int(target_input_tokens * 0.1)),
                "current_input": max(128, int(target_input_tokens * 0.12)),
                "proprioception": max(64, int(target_input_tokens * 0.08)),
            },
        }

    @staticmethod
    def _trim_priority(message: dict) -> tuple[int, int]:
        role = str(message.get("role") or "")
        if role == "tool":
            return (0, 0)
        if message.get("tool_calls"):
            return (1, 0)
        if role == "assistant":
            return (2, 0)
        if role == "user":
            return (3, 0)
        return (4, 0)

    def build_context_breakdown(
        self,
        *,
        session_history_before_turn: list[dict],
        current_turn_messages: list[dict],
        auto_memory_message: dict | None,
        policy_messages: list[dict],
        proprioception_message: dict | None,
        conversation_summary_message: dict | None = None,
        selected_history_messages: list[dict] | None = None,
    ) -> dict[str, int]:
        system_tokens = 0
        history_tokens = 0
        tool_history_tokens = 0

        history_source = selected_history_messages if selected_history_messages is not None else session_history_before_turn
        for message in history_source:
            tokens = self.estimate_message_tokens(message)
            if message.get("role") == "system":
                system_tokens += tokens
            elif message.get("role") == "tool" or message.get("tool_calls"):
                tool_history_tokens += tokens
            else:
                history_tokens += tokens

        memory_tokens = self.estimate_message_tokens(auto_memory_message or {}) + self.estimate_message_tokens(conversation_summary_message or {})
        policy_tokens = self.estimate_tokens(policy_messages)
        current_input_tokens = self.estimate_tokens(current_turn_messages)
        proprioception_tokens = self.estimate_message_tokens(proprioception_message or {})

        total = (
            system_tokens
            + history_tokens
            + tool_history_tokens
            + memory_tokens
            + policy_tokens
            + current_input_tokens
            + proprioception_tokens
        )
        return {
            "system": system_tokens,
            "history": history_tokens,
            "tool_history": tool_history_tokens,
            "memory_context": memory_tokens,
            "policy": policy_tokens,
            "current_input": current_input_tokens,
            "proprioception": proprioception_tokens,
            "total": total,
        }

    async def build_context_plan(
        self,
        *,
        session_history_before_turn: list[dict],
        current_turn_messages: list[dict],
        auto_memory_message: dict | None,
        policy_messages: list[dict],
        proprioception_message: dict | None,
        conversation_summary: str = "",
        route_context: dict[str, Any] | None = None,
        requested_mode: str = "",
        model: str = "",
        provider_name: str = "",
        api_url: str = "",
        context_limit_override: int | None = None,
    ) -> dict[str, Any]:
        del requested_mode
        route_context = route_context or {}
        length_policy = self.build_length_policy(
            model=model,
            provider_name=provider_name,
            api_url=api_url,
            context_limit_override=context_limit_override,
        )
        normalized_summary = self._normalize_conversation_summary(conversation_summary)
        summary_message = None
        if normalized_summary:
            summary_message = {
                "role": "system",
                "content": "[对话摘要层]\n" + normalized_summary,
                "metadata": {"context_layer": "conversation_summary", "transient": True},
            }

        system_history = [dict(message) for message in session_history_before_turn if message.get("role") == "system"]
        non_system_history = [dict(message) for message in session_history_before_turn if message.get("role") != "system"]
        selected_history = list(non_system_history)

        def compose_messages() -> list[dict]:
            messages = list(system_history)
            if summary_message:
                messages.append(summary_message)
            if auto_memory_message is not None:
                messages.append(dict(auto_memory_message))
            messages.extend(dict(message) for message in policy_messages)
            messages.extend(dict(message) for message in selected_history)
            messages.extend(dict(message) for message in current_turn_messages)
            if proprioception_message is not None:
                messages.append(dict(proprioception_message))
            return messages

        messages = compose_messages()
        recent_history_turns = int(length_policy.get("recent_history_turns", 8) or 8)
        while self.estimate_tokens(messages) > int(length_policy.get("target_input_tokens", 0) or 0) and selected_history:
            removal_index = 0
            removable_prefix = max(len(selected_history) - recent_history_turns, 0)
            if removable_prefix > 0:
                candidate_window = selected_history[:removable_prefix]
                candidate_scores = [self._trim_priority(message) for message in candidate_window]
                removal_index = min(range(len(candidate_window)), key=lambda idx: candidate_scores[idx])
            else:
                removable_roles = [idx for idx, message in enumerate(selected_history) if message.get("role") == "tool" or message.get("tool_calls")]
                if not removable_roles:
                    break
                removal_index = removable_roles[0]
            selected_history.pop(removal_index)
            messages = compose_messages()

        breakdown = self.build_context_breakdown(
            session_history_before_turn=system_history,
            selected_history_messages=selected_history,
            current_turn_messages=current_turn_messages,
            auto_memory_message=auto_memory_message,
            policy_messages=policy_messages,
            proprioception_message=proprioception_message,
            conversation_summary_message=summary_message,
        )
        return {
            "messages": messages,
            "length_policy": length_policy,
            "breakdown": breakdown,
            "layers": {
                "conversation_summary": bool(summary_message),
                "memory_recall": bool(auto_memory_message),
                "session_preload": bool(route_context.get("should_preload_context")),
                "prefer_live_web": bool(route_context.get("prefer_live_web")),
                "history_message_count": len(selected_history),
            },
        }

    async def trim_history(
        self,
        chat_history: list[dict],
        model: str,
        session,
        api_url: str,
        api_key: str,
        reserve_ratio: float = 0.75,
        context_limit_override: int | None = None,
        session_id: str = "",
        provider_name: str = "",
        preserve_message_count: int = 1,
    ) -> dict:
        length_policy = self.build_length_policy(
            model=model,
            provider_name=provider_name,
            api_url=api_url,
            context_limit_override=context_limit_override,
        )
        limit = int(length_policy.get("context_limit_tokens", 0) or self.get_context_limit(model))
        usable_tokens = min(int(limit * reserve_ratio), int(length_policy.get("target_input_tokens", 0) or 0) or int(limit * reserve_ratio))
        current_tokens = self.estimate_tokens(chat_history)
        result = {
            "summary_usage": None,
            "limit": limit,
            "usable_tokens": usable_tokens,
            "current_tokens": current_tokens,
            "conversation_summary": "",
            "trimmed_messages": 0,
            "length_policy": length_policy,
            "compression": {
                "triggered": False,
                "level": "none",
                "trimmed_messages": 0,
                "before_tokens": current_tokens,
                "after_tokens": current_tokens,
                "usable_tokens": usable_tokens,
                "summary_tokens": 0,
            },
        }

        if current_tokens <= usable_tokens:
            return result

        logger.info(
            "Context trim triggered: %s tokens > %s usable (limit=%s)",
            current_tokens,
            usable_tokens,
            limit,
        )

        preserve_count = max(int(preserve_message_count), 0)
        removable_history = list(chat_history[preserve_count:])
        messages_to_summarize = []
        while self.estimate_tokens(chat_history[:preserve_count] + removable_history) > usable_tokens and len(removable_history) > 2:
            candidate_window = removable_history[:-2] if len(removable_history) > 2 else removable_history
            if not candidate_window:
                break
            candidate_scores = [self._trim_priority(message) for message in candidate_window]
            removal_index = min(range(len(candidate_window)), key=lambda idx: candidate_scores[idx])
            messages_to_summarize.append(removable_history.pop(removal_index))

        if not messages_to_summarize:
            return result

        summary, summary_usage = await self._summarize(
            messages_to_summarize,
            session,
            api_url,
            api_key,
            model,
            existing_summary=self._normalize_conversation_summary(await self.load_context(session_id)) if session_id else "",
        )

        chat_history[:] = chat_history[:preserve_count] + removable_history
        normalized_summary = self._normalize_conversation_summary(summary)
        if normalized_summary:
            await self.update_context(normalized_summary, session_id=session_id)

        result["summary_usage"] = summary_usage
        result["current_tokens"] = self.estimate_tokens(chat_history)
        result["conversation_summary"] = normalized_summary
        result["trimmed_messages"] = len(messages_to_summarize)
        result["compression"] = {
            "triggered": True,
            "level": "history_summary",
            "trimmed_messages": len(messages_to_summarize),
            "before_tokens": current_tokens,
            "after_tokens": result["current_tokens"],
            "usable_tokens": usable_tokens,
            "summary_tokens": self.estimate_text_tokens(normalized_summary),
        }
        logger.info(
            "Context trim complete: compressed %s messages, now %s tokens",
            len(messages_to_summarize),
            result["current_tokens"],
        )
        return result

    @staticmethod
    def _summary_line(prefix: str, value: Any) -> str:
        text = ""
        if isinstance(value, str):
            text = value.strip()
        elif value is not None:
            try:
                text = json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                text = str(value)
        if not text:
            return ""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        return f"{prefix}: {normalized[:1200]}"

    def _serialize_message_for_summary(self, message: dict, index: int) -> str:
        lines = [f"[消息 {index}]", f"role: {str(message.get('role') or 'unknown')}"]
        content_line = self._summary_line("content", message.get("content"))
        if content_line:
            lines.append(content_line)
        tool_calls_line = self._summary_line("tool_calls", message.get("tool_calls"))
        if tool_calls_line:
            lines.append(tool_calls_line)
        provider_items_line = self._summary_line("provider_items", message.get("provider_items"))
        if provider_items_line:
            lines.append(provider_items_line)
        tool_call_id_line = self._summary_line("tool_call_id", message.get("tool_call_id"))
        if tool_call_id_line:
            lines.append(tool_call_id_line)
        return "\n".join(lines)

    async def _summarize(
        self,
        messages: list[dict],
        session,
        api_url: str,
        api_key: str,
        model: str,
        existing_summary: str = "",
    ) -> tuple[str, dict | None]:
        text_to_summarize = "\n\n".join(
            self._serialize_message_for_summary(message, index + 1)
            for index, message in enumerate(messages)
        )
        summary_messages = [
            {
                "role": "system",
                "content": (
                    "请将以下对话历史压缩为结构化摘要。"
                    "必须保留关键决策、用户要求、未完成事项、工具调用、工具结果、provider_items 续接线索。"
                    "输出固定结构：\n"
                    "[关键事实]\n"
                    "- ...\n"
                    "[工具链路]\n"
                    "- tool=... args=... result=...\n"
                    "[后续约束]\n"
                    "- ...\n"
                    "[续接线索]\n"
                    "- provider_items / reasoning / tool_call_id ..."
                ),
            },
        ]
        if existing_summary:
            summary_messages.append(
                {
                    "role": "system",
                    "content": f"已有摘要如下，请增量更新而不是重复堆叠：\n{existing_summary}",
                }
            )
        summary_messages.append(
            {
                "role": "user",
                "content": text_to_summarize,
            }
        )

        try:
            result = await self._adapter.chat(
                session,
                api_url,
                api_key,
                model,
                summary_messages,
            )
            summary = str(result.get("content") or "").strip()
            if summary:
                return summary, result.get("usage")
        except Exception as exc:
            logger.error("Summary generation failed: %s", exc)

        if existing_summary and text_to_summarize:
            merged = f"{existing_summary}\n{text_to_summarize[:600]}".strip()
            return merged[:1200] + ("..." if len(merged) > 1200 else ""), None
        return text_to_summarize[:800] + "...", None
