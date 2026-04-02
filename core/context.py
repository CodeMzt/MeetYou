"""
Context management, token estimation, and history compaction.
"""

from __future__ import annotations

import json
import logging


logger = logging.getLogger("meetyou.context")


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
    def estimate_message_tokens(cls, message: dict) -> int:
        total_chars = 0
        content = message.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total_chars += len(part.get("text", ""))
        if "tool_calls" in message:
            total_chars += len(json.dumps(message["tool_calls"], ensure_ascii=False))
        if "tool_call_id" in message:
            total_chars += len(str(message.get("tool_call_id") or ""))
        return int(total_chars / 1.8)

    @classmethod
    def estimate_tokens(cls, messages: list[dict]) -> int:
        return sum(cls.estimate_message_tokens(msg) for msg in messages)

    def get_context_limit(self, model_name: str) -> int:
        return self._adapter.get_context_limit(model_name)

    def build_context_breakdown(
        self,
        *,
        session_history_before_turn: list[dict],
        current_turn_messages: list[dict],
        auto_memory_message: dict | None,
        policy_messages: list[dict],
        proprioception_message: dict | None,
    ) -> dict[str, int]:
        system_tokens = 0
        history_tokens = 0
        tool_history_tokens = 0

        for message in session_history_before_turn:
            tokens = self.estimate_message_tokens(message)
            if message.get("role") == "system":
                system_tokens += tokens
            elif message.get("role") == "tool" or message.get("tool_calls"):
                tool_history_tokens += tokens
            else:
                history_tokens += tokens

        memory_tokens = self.estimate_message_tokens(auto_memory_message or {})
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

    async def trim_history(
        self,
        chat_history: list[dict],
        model: str,
        session,
        api_url: str,
        api_key: str,
        reserve_ratio: float = 0.75,
    ) -> dict:
        limit = self.get_context_limit(model)
        usable_tokens = int(limit * reserve_ratio)
        current_tokens = self.estimate_tokens(chat_history)
        result = {
            "summary_usage": None,
            "limit": limit,
            "usable_tokens": usable_tokens,
            "current_tokens": current_tokens,
        }

        if current_tokens <= usable_tokens:
            return result

        logger.info(
            "Context trim triggered: %s tokens > %s usable (limit=%s)",
            current_tokens,
            usable_tokens,
            limit,
        )

        messages_to_summarize = []
        while self.estimate_tokens(chat_history) > usable_tokens and len(chat_history) > 3:
            removed = chat_history.pop(1)
            messages_to_summarize.append(removed)

        if not messages_to_summarize:
            return result

        summary, summary_usage = await self._summarize(
            messages_to_summarize,
            session,
            api_url,
            api_key,
            model,
        )

        chat_history.insert(
            1,
            {
                "role": "system",
                "content": f"[历史对话摘要]\n{summary}",
            },
        )

        result["summary_usage"] = summary_usage
        result["current_tokens"] = self.estimate_tokens(chat_history)
        logger.info(
            "Context trim complete: compressed %s messages, now %s tokens",
            len(messages_to_summarize),
            result["current_tokens"],
        )
        return result

    async def _summarize(
        self,
        messages: list[dict],
        session,
        api_url: str,
        api_key: str,
        model: str,
    ) -> tuple[str, dict | None]:
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                lines.append(f"[{role}]: {content}")

        text_to_summarize = "\n".join(lines)
        summary_messages = [
            {
                "role": "system",
                "content": "请将以下对话历史压缩为简洁摘要，保留关键信息、决策和约定。只输出纯文本。",
            },
            {
                "role": "user",
                "content": text_to_summarize,
            },
        ]

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

        return text_to_summarize[:800] + "...", None
