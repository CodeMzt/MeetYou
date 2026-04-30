"""
Context management, token estimation, and history compaction.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.runtime_context import get_event_context


logger = logging.getLogger("meetyou.context")

_DEFAULT_PROVIDER_FAMILY = "generic"
DEFAULT_THREAD_CONTEXT_MESSAGE_LIMIT = 24
DEFAULT_THREAD_SUMMARY_MESSAGE_LIMIT = 80
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
        self._context_pool_service = None
        self._context_pool_principal_getter = None
        self._thread_service = None
        self._message_service = None
        self.proprioception_info: dict = {
            "ui_info": "",
            "running_apps": [],
            "last_update_time": 0,
        }

    def set_adapter(self, adapter):
        self._adapter = adapter

    def set_context_pool_service(self, service, *, principal_getter=None) -> None:
        self._context_pool_service = service
        self._context_pool_principal_getter = principal_getter

    def set_thread_context_services(self, *, thread_service=None, message_service=None) -> None:
        self._thread_service = thread_service
        self._message_service = message_service

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
                "context_pool": max(192, int(target_input_tokens * 0.1)),
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

    @staticmethod
    def _has_attachment_or_source(value: Any) -> bool:
        if isinstance(value, dict):
            for key in ("attachment_id", "attachments", "source_id", "source_ids", "citation_ids"):
                if value.get(key):
                    return True
            return any(ContextManager._has_attachment_or_source(item) for item in value.values())
        if isinstance(value, list):
            return any(ContextManager._has_attachment_or_source(item) for item in value)
        return False

    @staticmethod
    def _pending_tool_call_ids(history: list[dict]) -> set[str]:
        requested: set[str] = set()
        resolved: set[str] = set()
        for message in history:
            for tool_call in message.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                call_id = str(tool_call.get("id") or "").strip()
                if call_id:
                    requested.add(call_id)
            tool_call_id = str(message.get("tool_call_id") or "").strip()
            if tool_call_id:
                resolved.add(tool_call_id)
        return requested - resolved

    def build_context_breakdown(
        self,
        *,
        session_history_before_turn: list[dict],
        current_turn_messages: list[dict],
        auto_memory_message: dict | None,
        policy_messages: list[dict],
        proprioception_message: dict | None,
        conversation_summary_message: dict | None = None,
        context_pool_message: dict | None = None,
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

        context_pool_tokens = self.estimate_message_tokens(context_pool_message or {})
        memory_tokens = (
            self.estimate_message_tokens(auto_memory_message or {})
            + self.estimate_message_tokens(conversation_summary_message or {})
        )
        policy_tokens = self.estimate_tokens(policy_messages)
        current_input_tokens = self.estimate_tokens(current_turn_messages)
        proprioception_tokens = self.estimate_message_tokens(proprioception_message or {})

        total = (
            system_tokens
            + history_tokens
            + tool_history_tokens
            + context_pool_tokens
            + memory_tokens
            + policy_tokens
            + current_input_tokens
            + proprioception_tokens
        )
        return {
            "system": system_tokens,
            "history": history_tokens,
            "tool_history": tool_history_tokens,
            "context_pool": context_pool_tokens,
            "memory_context": memory_tokens,
            "policy": policy_tokens,
            "current_input": current_input_tokens,
            "proprioception": proprioception_tokens,
            "total": total,
        }

    async def _build_context_pool_message(
        self,
        *,
        current_turn_messages: list[dict],
        route_context: dict[str, Any],
    ) -> dict | None:
        service = self._context_pool_service
        principal_getter = self._context_pool_principal_getter
        if service is None or principal_getter is None:
            return None
        query_parts = []
        for message in current_turn_messages:
            if str(message.get("role") or "") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                query_parts.append(content.strip())
        query_text = "\n".join(query_parts).strip()
        if not query_text:
            return None
        event_context = get_event_context()
        workspace = route_context.get("workspace") if isinstance(route_context.get("workspace"), dict) else {}
        active_workspace_id = str(
            event_context.get("active_workspace_id")
            or event_context.get("workspace_id")
            or workspace.get("workspace_id")
            or ""
        ).strip()
        try:
            principal_id = principal_getter()
            rows = service.query_by_public_ids(
                principal_id=principal_id,
                query_text=query_text,
                thread_id=str(event_context.get("thread_id") or "").strip(),
                session_id=str(event_context.get("session_id") or "").strip(),
                active_workspace_id=active_workspace_id,
                limit=6,
            )
        except Exception as exc:
            logger.warning("ContextPool recall failed: %s", exc)
            return None
        if not rows:
            return None
        return {
            "role": "system",
            "content": (
                "[ContextPool]\n"
                "下面是跨 Client 会话池召回的短中期上下文。它不是长期事实；若与当前用户输入冲突，以当前输入为准。\n"
                + json.dumps({"items": rows}, ensure_ascii=False)
            ),
            "metadata": {"context_layer": "context_pool", "transient": True},
        }

    @staticmethod
    def _thread_message_metadata(row) -> dict[str, Any]:
        metadata = dict(getattr(row, "meta", {}) or {})
        metadata.update(
            {
                "context_layer": "thread_history",
                "persisted_thread_history": True,
                "thread_context_message_id": str(getattr(row, "message_id", "") or ""),
            }
        )
        active_workspace_id = getattr(row, "active_workspace_id", None)
        if active_workspace_id is not None:
            metadata["active_workspace_row_id"] = str(active_workspace_id)
        return metadata

    @classmethod
    def _thread_message_to_model_message(cls, row) -> dict[str, Any]:
        return {
            "role": str(getattr(row, "role", "") or "user"),
            "content": str(getattr(row, "content", "") or ""),
            "metadata": cls._thread_message_metadata(row),
        }

    @classmethod
    def _rows_to_summary_messages(cls, rows: list[Any]) -> list[dict[str, Any]]:
        return [
            cls._thread_message_to_model_message(row)
            for row in rows
            if str(getattr(row, "content", "") or "").strip()
            and str(getattr(row, "role", "") or "") in {"user", "assistant"}
        ]

    @staticmethod
    def _thread_summary_meta(*, older_count: int, summarized_count: int, message_limit: int) -> dict[str, Any]:
        return {
            "context_summary": {
                "older_message_count": max(0, int(older_count or 0)),
                "summarized_message_count": max(0, int(summarized_count or 0)),
                "summary_message_limit": max(1, int(message_limit or DEFAULT_THREAD_SUMMARY_MESSAGE_LIMIT)),
                "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            }
        }

    async def hydrate_thread_context(
        self,
        *,
        session_id: str = "",
        thread_id: str = "",
        current_message_id: str = "",
        current_endpoint_message_id: str = "",
        exact_message_limit: int = DEFAULT_THREAD_CONTEXT_MESSAGE_LIMIT,
        summary_message_limit: int = DEFAULT_THREAD_SUMMARY_MESSAGE_LIMIT,
        summary_session=None,
        api_url: str = "",
        api_key: str = "",
        model: str = "",
    ) -> dict[str, Any]:
        del session_id
        thread_service = self._thread_service
        message_service = self._message_service
        public_thread_id = str(thread_id or "").strip()
        if not public_thread_id or thread_service is None or message_service is None:
            return {}

        thread = thread_service.get_by_thread_id(public_thread_id)
        if thread is None:
            return {}
        thread_row_id = getattr(thread, "id", None)
        if thread_row_id is None:
            return {}

        exact_limit = max(1, int(exact_message_limit or DEFAULT_THREAD_CONTEXT_MESSAGE_LIMIT))
        summary_limit = max(1, int(summary_message_limit or DEFAULT_THREAD_SUMMARY_MESSAGE_LIMIT))
        window_loader = getattr(message_service, "load_thread_context_window", None)
        if not callable(window_loader):
            return {}
        window = window_loader(
            thread_id=thread_row_id,
            before_message_id=current_message_id,
            exclude_endpoint_message_id=current_endpoint_message_id,
            limit=exact_limit,
        )
        recent_rows = list((window or {}).get("messages") or [])
        older_count = int((window or {}).get("older_count", 0) or 0)
        exact_messages = self._rows_to_summary_messages(recent_rows)

        summary = str(getattr(thread, "summary", "") or "").strip()
        meta = dict(getattr(thread, "meta", {}) or {})
        summary_meta = meta.get("context_summary") if isinstance(meta.get("context_summary"), dict) else {}
        summarized_count = int((summary_meta or {}).get("summarized_message_count", 0) or 0)
        summary_stale = bool(older_count > 0 and (not summary or summarized_count < older_count))
        if summary_stale:
            older_loader = getattr(message_service, "list_older_thread_context_messages", None)
            older_rows = (
                older_loader(
                    thread_id=thread_row_id,
                    before_message_id=current_message_id,
                    exclude_endpoint_message_id=current_endpoint_message_id,
                    offset=exact_limit,
                    limit=summary_limit,
                )
                if callable(older_loader)
                else []
            )
            older_messages = self._rows_to_summary_messages(list(older_rows or []))
            if older_messages:
                try:
                    next_summary, _ = await self._summarize(
                        older_messages,
                        summary_session,
                        api_url,
                        api_key,
                        model,
                        existing_summary=summary,
                    )
                    next_summary = self._normalize_conversation_summary(next_summary)
                except Exception:
                    logger.warning("Thread context summary generation failed", exc_info=True)
                    next_summary = ""
                if next_summary:
                    summary = next_summary
                    updater = getattr(thread_service, "update_summary", None)
                    if callable(updater):
                        try:
                            updater(
                                thread_row_id=thread_row_id,
                                summary=summary,
                                metadata=self._thread_summary_meta(
                                    older_count=older_count,
                                    summarized_count=max(older_count, summarized_count),
                                    message_limit=summary_limit,
                                ),
                            )
                        except Exception:
                            logger.warning("Thread context summary persistence failed", exc_info=True)

        return {
            "thread_id": public_thread_id,
            "summary": summary,
            "messages": exact_messages,
            "older_count": older_count,
            "hydrated_message_count": len(exact_messages),
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
        context_pool_message = await self._build_context_pool_message(
            current_turn_messages=current_turn_messages,
            route_context=route_context,
        )

        system_history = [dict(message) for message in session_history_before_turn if message.get("role") == "system"]
        non_system_history = [dict(message) for message in session_history_before_turn if message.get("role") != "system"]
        selected_history = list(non_system_history)
        pending_tool_call_ids = self._pending_tool_call_ids(selected_history)

        def pinned_indexes_for_current_history() -> set[int]:
            pinned_indexes: set[int] = set()
            if not pending_tool_call_ids:
                return pinned_indexes
            for idx, message in enumerate(selected_history):
                tool_call_id = str(message.get("tool_call_id") or "").strip()
                if tool_call_id and tool_call_id in pending_tool_call_ids:
                    pinned_indexes.add(idx)
                    if idx > 0:
                        pinned_indexes.add(idx - 1)
                for tool_call in message.get("tool_calls") or []:
                    call_id = str((tool_call or {}).get("id") or "").strip()
                    if call_id and call_id in pending_tool_call_ids:
                        pinned_indexes.add(idx)
            return pinned_indexes

        def compose_messages() -> list[dict]:
            messages = list(system_history)
            if summary_message:
                messages.append(summary_message)
            if context_pool_message:
                messages.append(context_pool_message)
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
            pinned_indexes = pinned_indexes_for_current_history()
            removal_index = 0
            removable_prefix = max(len(selected_history) - recent_history_turns, 0)
            if removable_prefix > 0:
                candidate_window = [msg for idx, msg in enumerate(selected_history[:removable_prefix]) if idx not in pinned_indexes]
                candidate_scores = [self._trim_priority(message) for message in candidate_window]
                if not candidate_window:
                    break
                removal_index = min(range(len(candidate_window)), key=lambda idx: candidate_scores[idx])
                source_msg = candidate_window[removal_index]
                removal_index = selected_history.index(source_msg)
            else:
                removable_roles = [
                    idx
                    for idx, message in enumerate(selected_history)
                    if (message.get("role") == "tool" or message.get("tool_calls")) and idx not in pinned_indexes
                ]
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
            context_pool_message=context_pool_message,
        )
        return {
            "messages": messages,
            "length_policy": length_policy,
            "breakdown": breakdown,
            "layers": {
                "conversation_summary": bool(summary_message),
                "context_pool": bool(context_pool_message),
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

    async def compact_history_for_idle_heartbeat(
        self,
        chat_history: list[dict],
        *,
        model: str,
        session,
        api_url: str,
        api_key: str,
        session_id: str = "",
        provider_name: str = "",
        preserve_message_count: int = 1,
        recent_message_count: int = 6,
    ) -> dict:
        preserve_count = max(int(preserve_message_count), 0)
        recent_count = max(int(recent_message_count), 2)
        current_tokens = self.estimate_tokens(chat_history)
        result = {
            "summary_usage": None,
            "current_tokens": current_tokens,
            "conversation_summary": "",
            "trimmed_messages": 0,
            "compression": {
                "triggered": False,
                "level": "none",
                "reason": "idle_heartbeat",
                "trimmed_messages": 0,
                "before_tokens": current_tokens,
                "after_tokens": current_tokens,
                "summary_tokens": 0,
            },
        }

        preserved = list(chat_history[:preserve_count])
        tail = list(chat_history[preserve_count:])
        if len(tail) <= recent_count:
            return result

        def _is_meaningful(message: dict) -> bool:
            metadata = dict(message.get("metadata") or {})
            if metadata.get("transient"):
                return False
            content = message.get("content")
            return bool(str(content or "").strip()) or bool(message.get("tool_calls")) or bool(message.get("provider_items"))

        messages_to_summarize = [message for message in tail[:-recent_count] if _is_meaningful(message)]
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
        normalized_summary = self._normalize_conversation_summary(summary)
        if normalized_summary:
            await self.update_context(normalized_summary, session_id=session_id)

        chat_history[:] = preserved + tail[-recent_count:]
        after_tokens = self.estimate_tokens(chat_history)
        result["summary_usage"] = summary_usage
        result["current_tokens"] = after_tokens
        result["conversation_summary"] = normalized_summary
        result["trimmed_messages"] = len(messages_to_summarize)
        result["compression"] = {
            "triggered": True,
            "level": "idle_heartbeat_summary",
            "reason": "idle_heartbeat",
            "trimmed_messages": len(messages_to_summarize),
            "before_tokens": current_tokens,
            "after_tokens": after_tokens,
            "summary_tokens": self.estimate_text_tokens(normalized_summary),
            "provider_name": str(provider_name or ""),
        }
        logger.info(
            "Idle heartbeat context compaction complete: compressed %s messages for session %s",
            len(messages_to_summarize),
            session_id,
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
        content_value = message.get("content")
        content_line = self._summary_line("content", content_value)
        if content_line:
            if self.estimate_text_tokens(content_line) > 256:
                lines.append(content_line[:640] + " ...[truncated_for_summary]")
            else:
                lines.append(content_line)
        if self._has_attachment_or_source(content_value):
            lines.append("traceability: attachment/source id detected in content")
        tool_calls_line = self._summary_line("tool_calls", message.get("tool_calls"))
        if tool_calls_line:
            lines.append(tool_calls_line)
        provider_items_line = self._summary_line("provider_items", message.get("provider_items"))
        if provider_items_line:
            lines.append(provider_items_line)
        if self._has_attachment_or_source(message.get("provider_items")):
            lines.append("traceability: attachment/source id detected in provider_items")
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
