"""
Main conversational orchestration.
"""

from __future__ import annotations

import json
import asyncio
import logging
import re
from copy import deepcopy
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

try:
    import aiohttp
except ImportError:  # pragma: no cover - optional dependency
    aiohttp = None

from core.assistant_modes import (
    ASSISTANT_MODE_AUTO,
    ASSISTANT_MODE_NORMAL,
    ASSISTANT_MODES,
    ASSISTANT_SPECIALIZED_MODES,
    RouteDecision,
)
from core.brain_session import BrainSession
from core.public_contract import to_internal_assistant_mode
from core.runtime_context import bind_event_context, get_event_context, reset_event_context
from core.model_capabilities import ModelContextBudgetResolver
from core.status import ContextBreakdown, RuntimeStateSnapshot, RuntimeStatus, SessionUsageTotals, UsageCounters, UsageSnapshot, utcnow_iso
from core.tool_runtime import ToolCallResult, ToolErrorCategory, ToolSourceType, normalize_tool_result
from tools.object_operations import redacted_object_debug_entry

logger = logging.getLogger("meetyou.brain")

_INTERNAL_MODE_SWITCH_TOOL_NAME = "switch_assistant_mode"
_MODE_SWITCH_REASON_LIMIT = 160


class _FallbackClientSession:
    async def close(self):
        return None

TOOL_JUDGMENT_POLICY_MESSAGE = (
    "[Tool Judgment Policy]\n"
    "Decide proactively whether tools are needed; do not wait for the user to explicitly name a tool.\n"
    "Choose the smallest high-level chain tool that matches the user's job.\n"
    "Do not use tools for simple chit-chat or facts already fully available in the current conversation.\n"
    "Prefer a single high-level tool over manually stitching together multiple low-level steps."
)

WEB_RESEARCH_POLICY_MESSAGE = (
    "[Scenario Chain Policy]\n"
    "Use research_topic for current information, recommendations, comparisons, and open-ended web research.\n"
    "Use inspect_page when the user provides a direct URL or asks to inspect a specific page, PDF, or webpage.\n"
    "Switch to research mode only when the next step clearly needs source tracking, evidence-heavy analysis, or research-style report work.\n"
    "Use search_knowledge for prior conversations, user preferences, project history, or Notion knowledge.\n"
    "Use manage_tasks for explicit to-do management: create, list, update, and complete.\n"
    "Do not try to recreate the chain yourself with raw browser, Tavily, or memory primitives; the high-level tools already orchestrate that.\n"
    "When web-backed chain tools return source ids, answer first and cite sourced claims inline like [1], [2]."
)

MEMORY_POLICY_MESSAGE = (
    "[Memory Policy]\n"
    "Relevant long-term memory is often preloaded automatically.\n"
    "Use search_knowledge when the answer depends on prior conversations, user identity, preferences, ongoing tasks, unfinished commitments, or private workspace knowledge.\n"
    "Use remember_knowledge after answering when the user reveals a durable profile fact, stable preference, durable relationship, ongoing project state change, or commitment that will matter later.\n"
    "Do not use remember_knowledge for short acknowledgements, temporary emotions, obvious one-off small talk, or information that only matters in the current turn.\n"
    "High-signal sentence families that often deserve memory: self-introduction, stable bio facts, likes and dislikes, recurring habits, family or partner information, project ownership, blockers, deadlines, and explicit requests to remember something later.\n"
    "Low-signal sentence families that usually do not deserve memory: fleeting moods, one-off greetings, temporary states, throwaway examples, jokes, and facts relevant only to the current turn.\n"
    "Use manage_tasks instead of free-form memory when the user is asking to track or update a to-do.\n"
    "Do not try to call low-level memory tools directly unless a backend-internal message explicitly asks for it.\n"
    "Do not call update_context; working context is persisted automatically.\n"
    "If the current user message conflicts with memory, trust the current user message."
)

AUTO_MEMORY_SKIP_TOKENS = {
    "y",
    "yes",
    "n",
    "no",
    "ok",
    "好的",
    "嗯",
    "确认",
    "同意",
    "拒绝",
    "取消",
}

MEMORY_HINT_SUPPRESS_PATTERNS = (
    re.compile(r"^\s*(do you remember|can you remember|do you know)\b", re.IGNORECASE),
    re.compile(r"^\s*(你记得|你还记得|你知道)"),
)

MEMORY_TRIGGER_RULES = (
    {
        "category": "profile",
        "label": "durable profile facts",
        "description": "name, residence, origin, role, company, school, background, timezone",
        "patterns": (
            re.compile(
                r"\b(my name is|i am from|i'm from|i live in|i work at|i work as|i am a|i'm a|i study at|i'm based in)\b",
                re.IGNORECASE,
            ),
            re.compile(r"(我叫|我来自|我住在|我定居在|我在.+(工作|上班|读书)|我是)"),
        ),
    },
    {
        "category": "preference",
        "label": "stable preferences or habits",
        "description": "likes, dislikes, usual choices, recurring habits, routines",
        "patterns": (
            re.compile(r"\b(i like|i love|i prefer|i dislike|i hate|i usually|i always|i tend to|i normally)\b", re.IGNORECASE),
            re.compile(r"(喜欢|偏好|更喜欢|不喜欢|讨厌|习惯|通常|一般|总是)"),
        ),
    },
    {
        "category": "relationship",
        "label": "durable relationship facts",
        "description": "partner, spouse, children, parents, family structure, important close relations",
        "patterns": (
            re.compile(
                r"\b(my wife|my husband|my girlfriend|my boyfriend|my partner|my son|my daughter|my mom|my mother|my dad|my father|my kid|my child)\b",
                re.IGNORECASE,
            ),
            re.compile(r"(老婆|妻子|老公|对象|女朋友|男朋友|儿子|女儿|妈妈|母亲|爸爸|父亲|孩子)"),
        ),
    },
    {
        "category": "project",
        "label": "ongoing project state",
        "description": "what the user is working on, responsible for, blocked by, shipping, or maintaining",
        "patterns": (
            re.compile(
                r"\b(i am working on|i'm working on|i am still working on|i own|i am responsible for|i'm responsible for|blocker|deadline|shipping|maintaining)\b",
                re.IGNORECASE,
            ),
            re.compile(r"(最近.+(做|修|推进)|负责|维护|项目|版本|上线|需求|卡在|阻塞|截止日期)"),
        ),
    },
    {
        "category": "commitment",
        "label": "commitments worth remembering",
        "description": "explicit reminders, promises, future follow-through, remember-this requests",
        "patterns": (
            re.compile(
                r"\b(please remember|remember that|don't let me forget|remind me|i promised|i will remember|i need to remember)\b",
                re.IGNORECASE,
            ),
            re.compile(r"(记得|别忘了|提醒我|我答应了|我承诺|我要记住|下次提醒我|之后提醒我)"),
        ),
    },
)


@dataclass
class BrainOutputEvent:
    type: str
    text: str | None = None
    usage: dict | None = None
    payload: dict | None = None


@dataclass
class _ModeSwitchResult:
    message: str
    route_context: dict[str, Any]
    switch_count: int
    origin: str
    from_mode: str
    to_mode: str
    applied: bool = False


@dataclass
class _ToolExecutionPlanItem:
    index: int
    tool_call: Any
    args: dict[str, Any]
    policy: dict[str, Any]


class Brain:
    def __init__(self, adapter, tools_manager, context_manager, event_bus, exception_router, mode_manager=None):
        self._adapter = adapter
        self._tools_manager = tools_manager
        self._context_manager = context_manager
        self._event_bus = event_bus
        self._exception_router = exception_router
        self._mode_manager = mode_manager
        self._base_messages: list[dict] = []
        self._sessions: dict[str, BrainSession] = {}
        self._http_session: Any | None = None
        self._provider_name: str = ""
        self._global_context: str = ""
        self._model_context_budget_resolver = ModelContextBudgetResolver()

    async def init_brain(self, sys_prompt: str):
        self._base_messages = [{"role": "system", "content": sys_prompt}]
        self._global_context = await self._context_manager.load_context()
        self._http_session = aiohttp.ClientSession() if aiohttp is not None else _FallbackClientSession()
        logger.info("Brain initialized")

    def _base_message_count(self) -> int:
        return len(self._base_messages)

    async def _refresh_session_context(self, session: BrainSession):
        context = await self._context_manager.load_context(session.session_id)
        session.metadata["conversation_summary"] = str(context or "").strip()

    async def close_brain(self):
        for session in self._sessions.values():
            await self._save_session_context(session)
        if self._http_session is not None:
            await self._http_session.close()
            self._http_session = None
        logger.info("Brain closed")

    @property
    def is_initialized(self) -> bool:
        return self._http_session is not None

    def set_adapter(self, adapter):
        self._adapter = adapter

    def set_provider_name(self, provider_name: str):
        self._provider_name = str(provider_name or "").strip()

    def set_mode_manager(self, mode_manager):
        self._mode_manager = mode_manager

    async def refresh_base_prompt(self, sys_prompt: str, persisted_context: str):
        self._base_messages = [{"role": "system", "content": sys_prompt}]
        self._global_context = str(persisted_context or "").strip()
        for session in self._sessions.values():
            preserved = [message for message in session.chat_history[self._base_message_count() :]]
            session.chat_history = [dict(message) for message in self._base_messages] + preserved
        logger.info("Brain base prompt refreshed")

    def get_or_create_session(self, session_id: str) -> BrainSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = BrainSession(
                session_id=session_id,
                chat_history=[dict(message) for message in self._base_messages],
            )
            self._sessions[session_id] = session
        session.touch()
        return session

    def _recent_idle_poke_messages(self, session: BrainSession, *, limit: int = 6) -> list[str]:
        messages: list[str] = []
        for item in reversed(session.chat_history[self._base_message_count() :]):
            metadata = dict(item.get("metadata") or {})
            if metadata.get("heartbeat_signal_kind") != "idle_poke":
                continue
            content = str(item.get("content") or "").strip()
            if content:
                messages.append(content)
            if len(messages) >= limit:
                break
        return messages

    def compose_idle_poke_message(self, session_id: str, *, observed_issue: str = "") -> str:
        session = self.get_or_create_session(session_id)
        recent = set(self._recent_idle_poke_messages(session, limit=8))
        variants = [
            "我还在这儿，等你回来我们可以接着把刚才的事收完。",
            "我刚整理了一下状态，随时可以陪你继续推进。",
            "我这边空下来了，轻轻冒个泡，看看你要不要继续。",
            "如果你回来了，我可以接着陪你把手头这段往下走。",
            "我还在线，等你想继续的时候我们就从刚才那里接上。",
            "这边没有紧急状况，我先安静等你回来继续。",
        ]
        for offset in range(len(variants)):
            index = (len(recent) + offset) % len(variants)
            candidate = variants[index]
            if candidate not in recent:
                return candidate
        return f"我还在这儿，等你回来我们可以继续。({len(recent) + 1})"

    async def compact_session_for_idle_heartbeat(
        self,
        session_id: str,
        *,
        api_key: str,
        api_url: str,
        model: str,
        provider_name: str = "",
    ) -> dict[str, Any]:
        session = self.get_or_create_session(session_id)
        await self._refresh_session_context(session)
        if session.metadata.get("heartbeat_context_compacted_at"):
            return {
                "triggered": False,
                "reason": "already_compacted",
                "heartbeat_context_compacted_at": session.metadata.get("heartbeat_context_compacted_at"),
            }
        compactor = getattr(self._context_manager, "compact_history_for_idle_heartbeat", None)
        if not callable(compactor):
            return {"triggered": False, "reason": "compactor_unavailable"}
        result = await compactor(
            session.chat_history,
            model=model,
            session=session,
            api_url=api_url,
            api_key=api_key,
            session_id=session_id,
            provider_name=provider_name,
            preserve_message_count=self._base_message_count(),
            recent_message_count=6,
        )
        compression = dict(result.get("compression") or {})
        if compression.get("triggered"):
            compacted_at = utcnow_iso()
            session.metadata["heartbeat_context_compacted_at"] = compacted_at
            session.metadata["last_compaction_reason"] = "idle_heartbeat"
            session.metadata["last_compression"] = compression
            summary = str(result.get("conversation_summary") or "").strip()
            if summary:
                session.metadata["conversation_summary"] = summary
            await self._persist_session_context(session)
        return result

    async def record_proactive_assistant_message(
        self,
        session_id: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        text = str(content or "").strip()
        if not text:
            return
        session = self.get_or_create_session(session_id)
        session.chat_history.append(
            {
                "role": "assistant",
                "content": text,
                "metadata": {
                    "proactive": True,
                    "heartbeat_signal_kind": "idle_poke",
                    "created_at": utcnow_iso(),
                    **dict(metadata or {}),
                },
            }
        )
        session.touch()
        await self._persist_session_context(session)

    def discard_trailing_transient_messages(self, session_id: str):
        session = self._sessions.get(session_id)
        if session is None:
            return
        while len(session.chat_history) > self._base_message_count():
            metadata = dict(session.chat_history[-1].get("metadata") or {})
            if not bool(metadata.get("transient")):
                break
            session.chat_history.pop()

    async def close_session(self, session_id: str):
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await self._save_session_context(session)

    def clear_all_conversation_state(self) -> dict[str, Any]:
        base_history = [dict(message) for message in self._base_messages]
        cleared_session_count = 0
        active_session_count = 0
        for session in self._sessions.values():
            if (
                len(session.chat_history) > self._base_message_count()
                or bool(session.metadata)
                or bool(session.active_stream_id)
                or bool(session.usage_snapshot.session_totals.turn_count)
            ):
                cleared_session_count += 1
            if str(session.runtime_state.status or RuntimeStatus.IDLE.value) not in {
                RuntimeStatus.IDLE.value,
                RuntimeStatus.HEARTBEAT.value,
            }:
                active_session_count += 1
            session.chat_history = [dict(message) for message in base_history]
            session.active_stream_id = ""
            session.metadata = {}
            session.runtime_state = RuntimeStateSnapshot(session_id=session.session_id)
            session.usage_snapshot = UsageSnapshot(session_id=session.session_id)
            session.touch()
        self._global_context = ""
        return {
            "cleared_session_count": cleared_session_count,
            "active_session_count": active_session_count,
        }

    async def _save_session_context(self, session: BrainSession):
        await self._persist_session_context(session)

    def _build_time_context_message(self) -> dict[str, str]:
        local_now = datetime.now().astimezone()
        utc_now = local_now.astimezone(timezone.utc)
        payload = {
            "current_time_local": local_now.isoformat(timespec="seconds"),
            "current_time_utc": utc_now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "timezone": str(local_now.tzinfo or "UTC"),
            "local_date": local_now.strftime("%Y-%m-%d"),
            "local_time": local_now.strftime("%H:%M:%S"),
            "weekday": local_now.strftime("%A"),
            "iso_weekday": local_now.isoweekday(),
        }
        return {
            "role": "system",
            "content": "当前时间上下文：" + json.dumps(payload, ensure_ascii=False),
        }

    def get_session_runtime_snapshot(self, session_id: str) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return session.runtime_state.to_dict()

    def get_session_usage_snapshot(self, session_id: str) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return session.usage_snapshot.to_dict()

    def get_session_debug_snapshot(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")
        route_context = session.metadata.get("current_route") if isinstance(session.metadata.get("current_route"), dict) else {}
        return {
            "session_id": session_id,
            "route": self._sanitize_route_context(route_context),
            "route_history": [
                dict(item)
                for item in session.metadata.get("route_history", [])
                if isinstance(item, dict)
            ],
            "context_plan": dict(session.metadata.get("last_context_plan") or {}),
            "memory_scope": dict(session.metadata.get("last_memory_scope") or {}),
            "authorization": {
                "recent_decisions": [
                    dict(item)
                    for item in session.metadata.get("last_authorization_decisions", [])
                    if isinstance(item, dict)
                ],
            },
            "object_operations": [
                redacted_object_debug_entry(item)
                for item in session.metadata.get("last_object_operations", [])
                if isinstance(item, dict)
            ],
            "runtime_state": session.runtime_state.to_dict(),
            "reply_control": self.get_reply_control_snapshot(session_id),
            "checkpoints": self.list_reply_checkpoints(session_id),
            "usage": session.usage_snapshot.to_dict(),
            "request": dict(session.metadata.get("last_request_debug") or {}),
            "compression": dict(session.metadata.get("last_compression") or {}),
            "last_failure": dict(session.metadata.get("last_failure") or {}),
            "updated_at": session.runtime_state.updated_at,
        }

    def set_session_runtime_state(
        self,
        session_id: str,
        status: str | RuntimeStatus,
        detail: str = "",
        active_tools: list[str] | None = None,
        current_mode: str | None = None,
        route_reason: str | None = None,
        action_risk: str | None = None,
        source_profile: str | None = None,
        stream_id: str | None = None,
        turn_id: str | None = None,
        finish_reason: str | None = None,
        reply_control: dict | None = None,
    ) -> dict:
        session = self.get_or_create_session(session_id)
        return session.runtime_state.update(
            status=status,
            detail=detail,
            active_tools=active_tools,
            current_mode=current_mode,
            route_reason=route_reason,
            action_risk=action_risk,
            source_profile=source_profile,
            stream_id=stream_id,
            turn_id=turn_id,
            finish_reason=finish_reason,
            reply_control=reply_control,
        ).to_dict()

    @staticmethod
    def _sanitize_control_text(text: Any) -> dict[str, Any]:
        value = str(text or "").strip()
        if not value:
            return {"present": False, "length": 0, "preview": ""}
        preview = value[:120]
        if len(value) > 120:
            preview += "…"
        return {"present": True, "length": len(value), "preview": preview}

    def _reply_control_state(self, session: BrainSession) -> dict[str, Any]:
        state = session.metadata.get("reply_control")
        if not isinstance(state, dict):
            state = {}
            session.metadata["reply_control"] = state
        state.setdefault("active_turn", None)
        state.setdefault("pending_command", None)
        state.setdefault("last_command", {})
        state.setdefault("last_completed_command", {})
        state.setdefault("last_finish_reason", "")
        state.setdefault("latest_replay_input", None)
        return state

    def _reply_checkpoints(self, session: BrainSession) -> list[dict[str, Any]]:
        checkpoints = session.metadata.get("reply_checkpoints")
        if not isinstance(checkpoints, list):
            checkpoints = []
            session.metadata["reply_checkpoints"] = checkpoints
        return checkpoints

    def _reply_control_runtime_snapshot(self, session: BrainSession) -> dict[str, Any]:
        state = self._reply_control_state(session)
        active_turn = state.get("active_turn") if isinstance(state.get("active_turn"), dict) else None
        pending_command = state.get("pending_command") if isinstance(state.get("pending_command"), dict) else None
        return {
            "active": active_turn is not None,
            "state": str(active_turn.get("state") or "idle") if active_turn else "idle",
            "turn_id": str(active_turn.get("turn_id") or "") if active_turn else "",
            "stream_id": str(active_turn.get("stream_id") or "") if active_turn else "",
            "pending_action": str(pending_command.get("action") or "") if pending_command else "",
            "last_action": str((state.get("last_command") or {}).get("action") or ""),
            "last_action_status": str((state.get("last_completed_command") or {}).get("status") or ""),
            "checkpoint_count": len(self._reply_checkpoints(session)),
            "replay_ready": bool(state.get("latest_replay_input")),
        }

    def _sync_reply_control_runtime_state(self, session_id: str, session: BrainSession) -> None:
        session.runtime_state.update(
            status=session.runtime_state.status,
            detail=session.runtime_state.detail,
            active_tools=list(session.runtime_state.active_tools),
            current_mode=session.runtime_state.current_mode,
            route_reason=session.runtime_state.route_reason,
            action_risk=session.runtime_state.action_risk,
            source_profile=session.runtime_state.source_profile,
            stream_id=session.runtime_state.stream_id,
            turn_id=session.runtime_state.turn_id,
            finish_reason=str(self._reply_control_state(session).get("last_finish_reason") or ""),
            reply_control=self._reply_control_runtime_snapshot(session),
        )

    def _sanitize_reply_checkpoint(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        runtime = dict(checkpoint.get("runtime") or {})
        usage = dict(checkpoint.get("usage_snapshot") or {})
        return {
            "checkpoint_id": str(checkpoint.get("checkpoint_id") or ""),
            "kind": str(checkpoint.get("kind") or "turn_start"),
            "created_at": str(checkpoint.get("created_at") or ""),
            "turn_id": str(checkpoint.get("turn_id") or ""),
            "history_length": int(checkpoint.get("history_length", 0) or 0),
            "stream_id": str(runtime.get("stream_id") or ""),
            "usage_ready": bool(usage.get("usage_ready", False)),
            "input": dict(checkpoint.get("input_summary") or {}),
        }

    def list_reply_checkpoints(self, session_id: str) -> list[dict[str, Any]]:
        session = self.get_or_create_session(session_id)
        return [self._sanitize_reply_checkpoint(item) for item in self._reply_checkpoints(session)]

    def get_reply_control_snapshot(self, session_id: str) -> dict[str, Any]:
        session = self.get_or_create_session(session_id)
        state = self._reply_control_state(session)
        active_turn = state.get("active_turn") if isinstance(state.get("active_turn"), dict) else None
        pending_command = state.get("pending_command") if isinstance(state.get("pending_command"), dict) else None
        latest_replay = state.get("latest_replay_input") if isinstance(state.get("latest_replay_input"), dict) else None
        return {
            "active_turn": {
                "state": str(active_turn.get("state") or "idle"),
                "turn_id": str(active_turn.get("turn_id") or ""),
                "stream_id": str(active_turn.get("stream_id") or ""),
                "checkpoint_id": str(active_turn.get("checkpoint_id") or ""),
                "started_at": str(active_turn.get("started_at") or ""),
                "input": dict(active_turn.get("input_summary") or {}),
            } if active_turn else None,
            "pending_command": {
                "action": str(pending_command.get("action") or ""),
                "request_id": str(pending_command.get("request_id") or ""),
                "checkpoint_id": str(pending_command.get("checkpoint_id") or ""),
                "created_at": str(pending_command.get("created_at") or ""),
            } if pending_command else None,
            "last_command": dict(state.get("last_command") or {}),
            "last_completed_command": dict(state.get("last_completed_command") or {}),
            "last_finish_reason": str(state.get("last_finish_reason") or ""),
            "checkpoint_count": len(self._reply_checkpoints(session)),
            "latest_replay_input": {
                "turn_id": str(latest_replay.get("turn_id") or ""),
                "checkpoint_id": str(latest_replay.get("checkpoint_id") or ""),
                "created_at": str(latest_replay.get("created_at") or ""),
                "input": dict(latest_replay.get("input_summary") or {}),
            } if latest_replay else None,
        }

    def _create_reply_checkpoint(
        self,
        session: BrainSession,
        *,
        turn_id: str,
        input_info: dict[str, Any],
        history_length: int,
    ) -> dict[str, Any]:
        checkpoint = {
            "checkpoint_id": uuid4().hex,
            "kind": "turn_start",
            "created_at": utcnow_iso(),
            "turn_id": str(turn_id or ""),
            "history_length": int(history_length),
            "runtime": {
                "stream_id": session.runtime_state.stream_id,
                "turn_id": session.runtime_state.turn_id,
            },
            "usage_snapshot": session.usage_snapshot.to_dict(),
            "input_summary": self._sanitize_control_text(input_info.get("content")),
        }
        checkpoints = self._reply_checkpoints(session)
        checkpoints.append(checkpoint)
        if len(checkpoints) > 12:
            del checkpoints[:-12]
        return checkpoint

    def _restore_usage_snapshot(self, session: BrainSession, snapshot: dict[str, Any]) -> None:
        session.usage_snapshot.session_id = session.session_id
        session.usage_snapshot.usage_ready = bool(snapshot.get("usage_ready", False))
        session.usage_snapshot.context_limit_tokens = int(snapshot.get("context_limit_tokens", 0) or 0)
        session.usage_snapshot.context_limit_source = str(snapshot.get("context_limit_source") or "")
        session.usage_snapshot.context_limit_model = str(snapshot.get("context_limit_model") or "")
        session.usage_snapshot.context_limit_confidence = str(snapshot.get("context_limit_confidence") or "")
        session.usage_snapshot.current_context_tokens_estimated = int(
            snapshot.get("current_context_tokens_estimated", 0) or 0
        )
        session.usage_snapshot.context_breakdown = ContextBreakdown.from_mapping(snapshot.get("context_breakdown") or {})
        session.usage_snapshot.context_budget_breakdown = dict(snapshot.get("context_budget_breakdown") or {})
        totals = dict(snapshot.get("session_totals") or {})
        session.usage_snapshot.last_turn_usage = UsageCounters(
            prompt_tokens=int((snapshot.get("last_turn_usage") or {}).get("prompt_tokens", 0) or 0),
            completion_tokens=int((snapshot.get("last_turn_usage") or {}).get("completion_tokens", 0) or 0),
            reasoning_tokens=int((snapshot.get("last_turn_usage") or {}).get("reasoning_tokens", 0) or 0),
            total_tokens=int((snapshot.get("last_turn_usage") or {}).get("total_tokens", 0) or 0),
        )
        session.usage_snapshot.session_totals = SessionUsageTotals(
            prompt_tokens=int(totals.get("prompt_tokens", 0) or 0),
            completion_tokens=int(totals.get("completion_tokens", 0) or 0),
            reasoning_tokens=int(totals.get("reasoning_tokens", 0) or 0),
            total_tokens=int(totals.get("total_tokens", 0) or 0),
            turn_count=int(totals.get("turn_count", 0) or 0),
        )
        session.usage_snapshot.usage_source = str(snapshot.get("usage_source") or "estimated")
        session.usage_snapshot.updated_at = str(snapshot.get("updated_at") or utcnow_iso())

    def _restore_reply_checkpoint(self, session: BrainSession, checkpoint_id: str) -> dict[str, Any]:
        checkpoints = self._reply_checkpoints(session)
        checkpoint = next(
            (item for item in reversed(checkpoints) if str(item.get("checkpoint_id") or "") == str(checkpoint_id or "")),
            None,
        )
        if checkpoint is None:
            raise ValueError("检查点不存在或已失效。")
        history_length = int(checkpoint.get("history_length", 0) or 0)
        if history_length < len(session.chat_history):
            del session.chat_history[history_length:]
        self._restore_usage_snapshot(session, dict(checkpoint.get("usage_snapshot") or {}))
        state = self._reply_control_state(session)
        state["active_turn"] = None
        state["pending_command"] = None
        checkpoints[:] = [
            item
            for item in checkpoints
            if int(item.get("history_length", 0) or 0) <= history_length
        ]
        return checkpoint

    @staticmethod
    def _merged_guidance_input(input_info: dict[str, Any], guidance: str) -> dict[str, Any]:
        merged = deepcopy(dict(input_info or {}))
        base_content = str(merged.get("content") or "").strip()
        guidance_text = str(guidance or "").strip()
        merged["content"] = base_content if not guidance_text else f"{base_content}\n\n补充要求：{guidance_text}"
        metadata = dict(merged.get("metadata") or {})
        metadata["reply_control_replay"] = "append_guidance"
        metadata["reply_control_guidance"] = True
        merged["metadata"] = metadata
        return merged

    def request_reply_control(
        self,
        session_id: str,
        *,
        action: str,
        request_id: str,
        guidance: str = "",
        checkpoint_id: str = "",
        turn_id: str = "",
        stream_id: str = "",
    ) -> dict[str, Any]:
        session = self.get_or_create_session(session_id)
        state = self._reply_control_state(session)
        active_turn = state.get("active_turn") if isinstance(state.get("active_turn"), dict) else None
        normalized_action = str(action or "").strip().lower()
        if active_turn is not None:
            active_turn_id = str(active_turn.get("turn_id") or "")
            active_stream_id = str(active_turn.get("stream_id") or "")
            if turn_id and turn_id != active_turn_id:
                return {"action": normalized_action, "status": "rejected", "reason": "turn_id 不匹配。"}
            if stream_id and stream_id != active_stream_id:
                return {"action": normalized_action, "status": "rejected", "reason": "stream_id 不匹配。"}
        if normalized_action == "list_checkpoints":
            result = {
                "action": normalized_action,
                "status": "completed",
                "checkpoints": self.list_reply_checkpoints(session_id),
            }
            state["last_completed_command"] = {"action": normalized_action, "status": "completed", "request_id": request_id}
            self._sync_reply_control_runtime_state(session_id, session)
            return result
        if normalized_action == "stop":
            if active_turn is None:
                return {"action": normalized_action, "status": "rejected", "reason": "当前没有进行中的回复。"}
            active_turn["state"] = "canceling"
            state["pending_command"] = {
                "action": normalized_action,
                "request_id": request_id,
                "checkpoint_id": str(active_turn.get("checkpoint_id") or ""),
                "created_at": utcnow_iso(),
            }
            state["last_command"] = {"action": normalized_action, "status": "accepted", "request_id": request_id}
            self._sync_reply_control_runtime_state(session_id, session)
            return {"action": normalized_action, "status": "accepted"}
        if normalized_action == "append_guidance":
            if active_turn is None:
                return {"action": normalized_action, "status": "rejected", "reason": "当前没有可追加引导的进行中回复。"}
            guidance_text = str(guidance or "").strip()
            if not guidance_text:
                return {"action": normalized_action, "status": "rejected", "reason": "guidance 不能为空。"}
            active_turn["state"] = "replaying"
            state["pending_command"] = {
                "action": normalized_action,
                "request_id": request_id,
                "guidance": guidance_text,
                "checkpoint_id": str(active_turn.get("checkpoint_id") or ""),
                "created_at": utcnow_iso(),
            }
            state["last_command"] = {"action": normalized_action, "status": "accepted", "request_id": request_id}
            self._sync_reply_control_runtime_state(session_id, session)
            return {"action": normalized_action, "status": "accepted"}
        if normalized_action == "regenerate":
            if active_turn is not None:
                active_turn["state"] = "replaying"
                state["pending_command"] = {
                    "action": normalized_action,
                    "request_id": request_id,
                    "checkpoint_id": str(active_turn.get("checkpoint_id") or ""),
                    "created_at": utcnow_iso(),
                }
                state["last_command"] = {"action": normalized_action, "status": "accepted", "request_id": request_id}
                self._sync_reply_control_runtime_state(session_id, session)
                return {"action": normalized_action, "status": "accepted"}
            latest_replay_input = state.get("latest_replay_input") if isinstance(state.get("latest_replay_input"), dict) else None
            if latest_replay_input is None:
                return {"action": normalized_action, "status": "rejected", "reason": "当前没有可重新回复的最近输入。"}
            checkpoint_ref = str(latest_replay_input.get("checkpoint_id") or "")
            if not checkpoint_ref:
                return {"action": normalized_action, "status": "rejected", "reason": "最近输入缺少可恢复检查点。"}
            try:
                restored = self._restore_reply_checkpoint(session, checkpoint_ref)
            except ValueError as exc:
                return {"action": normalized_action, "status": "rejected", "reason": str(exc)}
            replay_input = deepcopy(dict(latest_replay_input.get("input_info") or {}))
            state["last_completed_command"] = {"action": normalized_action, "status": "completed", "request_id": request_id}
            self._sync_reply_control_runtime_state(session_id, session)
            return {
                "action": normalized_action,
                "status": "completed",
                "replay_input": replay_input,
                "checkpoint": self._sanitize_reply_checkpoint(restored),
            }
        if normalized_action == "rollback":
            if not checkpoint_id:
                return {"action": normalized_action, "status": "rejected", "reason": "checkpoint_id 为必填字段。"}
            if not any(str(item.get("checkpoint_id") or "") == checkpoint_id for item in self._reply_checkpoints(session)):
                return {"action": normalized_action, "status": "rejected", "reason": "检查点不存在或已失效。"}
            if active_turn is not None:
                active_turn["state"] = "rolled_back"
                state["pending_command"] = {
                    "action": normalized_action,
                    "request_id": request_id,
                    "checkpoint_id": checkpoint_id,
                    "created_at": utcnow_iso(),
                }
                state["last_command"] = {"action": normalized_action, "status": "accepted", "request_id": request_id}
                self._sync_reply_control_runtime_state(session_id, session)
                return {"action": normalized_action, "status": "accepted"}
            restored = self._restore_reply_checkpoint(session, checkpoint_id)
            state["last_completed_command"] = {"action": normalized_action, "status": "completed", "request_id": request_id}
            state["last_finish_reason"] = "rolled_back"
            self._sync_reply_control_runtime_state(session_id, session)
            return {
                "action": normalized_action,
                "status": "completed",
                "checkpoint": self._sanitize_reply_checkpoint(restored),
            }
        return {"action": normalized_action, "status": "rejected", "reason": "不支持的控制动作。"}

    def finalize_reply_control(self, session_id: str, *, turn_id: str, interrupted: bool) -> dict[str, Any]:
        session = self.get_or_create_session(session_id)
        state = self._reply_control_state(session)
        active_turn = state.get("active_turn") if isinstance(state.get("active_turn"), dict) else None
        pending_command = state.get("pending_command") if isinstance(state.get("pending_command"), dict) else None
        if active_turn is None or str(active_turn.get("turn_id") or "") != str(turn_id or ""):
            return {"finish_reason": str(state.get("last_finish_reason") or ""), "replay_input": None, "control_result": None}
        replay_input = None
        control_result = None
        finish_reason = "completed"
        if interrupted and pending_command:
            action = str(pending_command.get("action") or "")
            finish_reason = {
                "stop": "stopped",
                "append_guidance": "replayed",
                "regenerate": "replayed",
                "rollback": "rolled_back",
            }.get(action, "stopped")
            checkpoint_ref = str(pending_command.get("checkpoint_id") or active_turn.get("checkpoint_id") or "")
            if action in {"append_guidance", "regenerate"}:
                restored = self._restore_reply_checkpoint(session, checkpoint_ref)
                latest_replay = state.get("latest_replay_input") if isinstance(state.get("latest_replay_input"), dict) else None
                base_input = deepcopy(
                    dict(
                        active_turn.get("input_info")
                        or (latest_replay.get("input_info") if isinstance(latest_replay, dict) else {})
                        or {}
                    )
                )
                if action == "append_guidance":
                    replay_input = self._merged_guidance_input(base_input, str(pending_command.get("guidance") or ""))
                else:
                    replay_input = base_input
                control_result = {
                    "action": action,
                    "status": "completed",
                    "checkpoint": self._sanitize_reply_checkpoint(restored),
                }
            elif action == "rollback":
                restored = self._restore_reply_checkpoint(session, str(pending_command.get("checkpoint_id") or ""))
                control_result = {
                    "action": action,
                    "status": "completed",
                    "checkpoint": self._sanitize_reply_checkpoint(restored),
                }
            else:
                control_result = {"action": action, "status": "completed"}
            state["last_completed_command"] = {
                "action": action,
                "status": "completed",
                "request_id": str(pending_command.get("request_id") or ""),
            }
            state["pending_command"] = None
        elif interrupted:
            finish_reason = "stopped"
        state["active_turn"] = None
        state["last_finish_reason"] = finish_reason
        self._sync_reply_control_runtime_state(session_id, session)
        return {"finish_reason": finish_reason, "replay_input": replay_input, "control_result": control_result}

    def mark_reply_turn_failed(self, session_id: str, *, turn_id: str) -> None:
        session = self.get_or_create_session(session_id)
        state = self._reply_control_state(session)
        active_turn = state.get("active_turn") if isinstance(state.get("active_turn"), dict) else None
        if active_turn is not None and str(active_turn.get("turn_id") or "") == str(turn_id or ""):
            checkpoint_id = str(active_turn.get("checkpoint_id") or "")
            if checkpoint_id:
                try:
                    self._restore_reply_checkpoint(session, checkpoint_id)
                except ValueError:
                    pass
            state["active_turn"] = None
            state["pending_command"] = None
            state["last_finish_reason"] = "failed"
            self._sync_reply_control_runtime_state(session_id, session)

    @staticmethod
    def _sanitize_runtime_error_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(payload or {})
        details = dict(payload.get("details") or {})
        safe_details = {
            key: value
            for key, value in details.items()
            if key not in {"headers", "request_body", "raw_request", "raw_response", "api_key", "authorization"}
        }
        return {
            "code": str(payload.get("code") or "runtime_unhandled"),
            "category": str(payload.get("category") or "runtime"),
            "message": str(payload.get("message") or "Runtime error"),
            "retryable": bool(payload.get("retryable", False)),
            "details": safe_details,
            "occurred_at": str(payload.get("occurred_at") or utcnow_iso()),
        }

    @staticmethod
    def _api_target_snapshot(api_url: str) -> dict[str, str]:
        parsed = urlparse(str(api_url or "").strip())
        return {
            "host": (parsed.hostname or "").lower(),
            "path": parsed.path or "",
        }

    def _adapter_transport_mode(self, api_url: str) -> str:
        adapter_name = type(self._adapter).__name__.lower()
        host = self._api_target_snapshot(api_url).get("host", "")
        if adapter_name == "openaiadapter":
            return "official_openai_responses" if host == "api.openai.com" else "openai_compatible_chat"
        return adapter_name or "unknown"

    def _build_request_debug_snapshot(
        self,
        *,
        provider_name: str,
        model: str,
        api_url: str,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        context_plan: dict[str, Any],
        context_breakdown: dict[str, int],
        context_limit_info: dict[str, Any],
        context_budget_breakdown: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        length_policy = dict(context_plan.get("length_policy") or {})
        layers = dict(context_plan.get("layers") or {})
        request_tokens_estimated = int(
            getattr(self._context_manager, "estimate_tokens")(messages)
            if callable(getattr(self._context_manager, "estimate_tokens", None))
            else sum(self._estimate_message_tokens(message) for message in messages)
        )
        context_limit_tokens = int(context_limit_info.get("context_limit_tokens", 0) or self._get_context_limit(model))
        pressure_ratio = (
            round(request_tokens_estimated / context_limit_tokens, 4)
            if context_limit_tokens > 0
            else 0.0
        )
        target = self._api_target_snapshot(api_url)
        return {
            "provider_name": str(provider_name or self._provider_name or ""),
            "model": str(model or ""),
            "api_target": target,
            "transport_mode": self._adapter_transport_mode(api_url),
            "message_count": len(messages),
            "tool_count": len(tools or []),
            "request_tokens_estimated": request_tokens_estimated,
            "context_limit_tokens": context_limit_tokens,
            "pressure_ratio": pressure_ratio,
            "near_limit": bool(context_limit_tokens and pressure_ratio >= 0.85),
            "length_policy": {
                "provider_family": str(length_policy.get("provider_family") or ""),
                "target_input_tokens": int(length_policy.get("target_input_tokens", 0) or 0),
                "reserved_response_tokens": int(length_policy.get("reserved_response_tokens", 0) or 0),
                "reserve_ratio": float(length_policy.get("reserve_ratio", 0) or 0),
            },
            "budget": {
                "context_limit_tokens": context_limit_tokens,
                "target_input_tokens": int(length_policy.get("target_input_tokens", 0) or 0),
                "reserved_response_tokens": int(length_policy.get("reserved_response_tokens", 0) or 0),
                "breakdown_total": int(context_breakdown.get("total", 0) or 0),
                "context_budget_breakdown": dict(context_budget_breakdown or {}),
            },
            "layers": {
                "conversation_summary": bool(layers.get("conversation_summary")),
                "memory_recall": bool(layers.get("memory_recall")),
                "session_preload": bool(layers.get("session_preload")),
                "prefer_live_web": bool(layers.get("prefer_live_web")),
                "history_message_count": int(layers.get("history_message_count", 0) or 0),
            },
        }

    async def _attempt_compaction_for_budget(
        self,
        *,
        session: BrainSession,
        model: str,
        api_url: str,
        api_key: str,
        provider_name: str,
        context_limit_info: dict[str, Any],
        reserve_ratio: float,
        turn_usage: UsageCounters | None = None,
    ) -> dict[str, Any]:
        try:
            result = await self._context_manager.trim_history(
                session.chat_history,
                model,
                self._http_session,
                api_url,
                api_key,
                reserve_ratio=reserve_ratio,
                context_limit_override=int(context_limit_info.get("context_limit_tokens", 0) or 0),
                session_id=session.session_id,
                provider_name=provider_name,
                preserve_message_count=self._base_message_count(),
            ) or {}
        except TypeError:
            result = await self._context_manager.trim_history(
                session.chat_history,
                model,
                self._http_session,
                api_url,
                api_key,
            ) or {}
        trimmed_summary = str(result.get("conversation_summary") or "").strip()
        if trimmed_summary:
            session.metadata["conversation_summary"] = trimmed_summary
        compression_snapshot = dict(result.get("compression") or {})
        if compression_snapshot:
            session.metadata["last_compression"] = compression_snapshot
        summary_usage = self._normalize_usage(result.get("summary_usage"))
        if summary_usage and turn_usage is not None:
            turn_usage.add(summary_usage)
            session.usage_snapshot.session_totals.add(summary_usage)
        return result

    def _build_failure_payload_from_exception(
        self,
        exc: Exception,
        *,
        request_debug: dict[str, Any],
        compression: dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(getattr(exc, "runtime_error_payload", None), dict):
            payload = self._sanitize_runtime_error_payload(getattr(exc, "runtime_error_payload"))
        else:
            payload = self._sanitize_runtime_error_payload(
                {
                    "code": "conversation_request_failed",
                    "category": "runtime",
                    "message": str(exc) or type(exc).__name__,
                    "retryable": False,
                    "details": {"exception_type": type(exc).__name__},
                }
            )
        details = dict(payload.get("details") or {})
        details.setdefault("provider_name", str(request_debug.get("provider_name") or ""))
        details.setdefault("model", str(request_debug.get("model") or ""))
        details.setdefault("transport_mode", str(request_debug.get("transport_mode") or ""))
        details.setdefault("request_tokens_estimated", int(request_debug.get("request_tokens_estimated", 0) or 0))
        details.setdefault("context_limit_tokens", int(request_debug.get("context_limit_tokens", 0) or 0))
        details.setdefault("compression_triggered", bool(compression.get("triggered", False)))
        details.setdefault("compression_level", str(compression.get("level") or "none"))
        payload["details"] = details
        return self._sanitize_runtime_error_payload(payload)

    def _record_session_failure(self, session: BrainSession, payload: dict[str, Any] | None) -> dict[str, Any]:
        sanitized = self._sanitize_runtime_error_payload(payload)
        session.metadata["last_failure"] = sanitized
        return sanitized

    @staticmethod
    def _normalize_mode_name(value: Any, fallback: str = ASSISTANT_MODE_AUTO) -> str:
        normalized = to_internal_assistant_mode(value, fallback=fallback)
        if normalized in ASSISTANT_MODES or normalized == ASSISTANT_MODE_AUTO:
            return normalized
        return fallback

    def _route_to_dict(self, route: RouteDecision | dict[str, Any] | None) -> dict[str, Any]:
        if isinstance(route, RouteDecision):
            return route.to_dict()
        return dict(route or {})

    def _build_default_route(
        self,
        session: BrainSession,
        *,
        requested_mode: str = ASSISTANT_MODE_NORMAL,
        mode: str = ASSISTANT_MODE_NORMAL,
        reason: str = "",
    ) -> dict[str, Any]:
        current_mode = self._normalize_mode_name(mode, fallback=ASSISTANT_MODE_NORMAL)
        source_profile = "workspace_local"
        if current_mode == "research":
            source_profile = "tech_updates"
        elif current_mode == "study":
            source_profile = "study_materials"
        return {
            "requested_mode": self._normalize_mode_name(requested_mode, fallback=ASSISTANT_MODE_NORMAL),
            "current_mode": current_mode or session.metadata.get("current_mode", "") or ASSISTANT_MODE_NORMAL,
            "route_reason": reason or "Assistant mode manager unavailable; using default normal mode.",
            "source_profile": source_profile,
            "tool_bundle": [],
            "mcp_servers": [],
            "prompt_bundle": current_mode or ASSISTANT_MODE_NORMAL,
            "active_skills": [],
            "loaded_skills": list((session.metadata.get("current_route") or {}).get("loaded_skills") or []),
        }

    @staticmethod
    def _first_source_profile(values: Any) -> str:
        if not isinstance(values, list):
            return ""
        for item in values:
            normalized = str(item or "").strip()
            if normalized:
                return normalized
        return ""

    def _resolve_governed_source_profile(self, route_context: dict[str, Any]) -> tuple[str, str]:
        effective_procedure = route_context.get("effective_procedure")
        if isinstance(effective_procedure, dict):
            profile = self._first_source_profile(effective_procedure.get("recommended_source_profiles"))
            if profile:
                return profile, f"Effective procedure source profile preference: {profile}"

        pinned_procedure = route_context.get("pinned_procedure")
        if isinstance(pinned_procedure, dict):
            profile = self._first_source_profile(pinned_procedure.get("recommended_source_profiles"))
            if profile:
                return profile, f"Pinned procedure source profile preference: {profile}"

        workspace = route_context.get("workspace")
        if isinstance(workspace, dict):
            current_source_profile = str(route_context.get("source_profile") or "").strip()
            if current_source_profile and current_source_profile not in {"workspace_local", "study_materials"}:
                return "", ""
            profile = self._first_source_profile(workspace.get("preferred_source_profiles"))
            if profile:
                return profile, f"Workspace source profile preference: {profile}"

        return "", ""

    def _apply_route_metadata_overrides(self, route_context: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        route_dict = dict(route_context or {})
        workspace_id = str(metadata.get("workspace_id") or "").strip()
        workspace_title = str(metadata.get("workspace_title") or "").strip()
        workspace_base_mode = str(metadata.get("workspace_base_mode") or "").strip()
        workspace_prompt_overlay = str(metadata.get("workspace_prompt_overlay") or "").strip()
        workspace_default_execution_target = str(metadata.get("workspace_default_execution_target") or "").strip()
        workspace_preferred_source_profiles = [
            str(item).strip() for item in metadata.get("workspace_preferred_source_profiles", []) if str(item).strip()
        ]
        workspace_memory_ranking_policy = str(metadata.get("workspace_memory_ranking_policy") or "").strip()
        if any(
            [
                workspace_id,
                workspace_title,
                workspace_base_mode,
                workspace_prompt_overlay,
                workspace_default_execution_target,
                workspace_preferred_source_profiles,
                workspace_memory_ranking_policy,
            ]
        ):
            route_dict["workspace"] = {
                "workspace_id": workspace_id,
                "title": workspace_title,
                "base_mode": workspace_base_mode,
                "prompt_overlay": workspace_prompt_overlay,
                "default_execution_target": workspace_default_execution_target,
                "preferred_source_profiles": workspace_preferred_source_profiles,
                "memory_ranking_policy": workspace_memory_ranking_policy,
            }
        procedure_payload = metadata.get("pinned_procedure")
        procedure_id = str(metadata.get("pinned_procedure_id") or "").strip()
        if isinstance(procedure_payload, dict) and procedure_id:
            normalized_procedure = {
                "procedure_id": procedure_id,
                "title": str(procedure_payload.get("title") or "").strip(),
                "description": str(procedure_payload.get("description") or "").strip(),
                "prompt_overlay": str(procedure_payload.get("prompt_overlay") or "").strip(),
                "applicable_modes": [str(item).strip() for item in procedure_payload.get("applicable_modes", []) if str(item).strip()],
                "recommended_capabilities": [
                    str(item).strip() for item in procedure_payload.get("recommended_capabilities", []) if str(item).strip()
                ],
                "recommended_source_profiles": [
                    str(item).strip() for item in procedure_payload.get("recommended_source_profiles", []) if str(item).strip()
                ],
                "default_execution_target": str(procedure_payload.get("default_execution_target") or "").strip(),
                "risk_profile": str(procedure_payload.get("risk_profile") or "").strip(),
                "status": str(procedure_payload.get("status") or "").strip(),
            }
            route_dict["pinned_procedure"] = normalized_procedure
            existing_reason = str(route_dict.get("route_reason") or "").strip()
            procedure_reason = f"Pinned procedure: {procedure_id}"
            if procedure_reason not in existing_reason:
                route_dict["route_reason"] = (
                    f"{existing_reason} {procedure_reason}".strip()
                    if existing_reason
                    else procedure_reason
                )
        effective_procedure_payload = metadata.get("effective_procedure")
        effective_procedure_source = str(metadata.get("effective_procedure_source") or "").strip()
        if isinstance(effective_procedure_payload, dict):
            route_dict["effective_procedure"] = {
                "procedure_id": str(effective_procedure_payload.get("procedure_id") or "").strip(),
                "title": str(effective_procedure_payload.get("title") or "").strip(),
                "description": str(effective_procedure_payload.get("description") or "").strip(),
                "prompt_overlay": str(effective_procedure_payload.get("prompt_overlay") or "").strip(),
                "applicable_modes": [
                    str(item).strip() for item in effective_procedure_payload.get("applicable_modes", []) if str(item).strip()
                ],
                "recommended_capabilities": [
                    str(item).strip()
                    for item in effective_procedure_payload.get("recommended_capabilities", [])
                    if str(item).strip()
                ],
                "recommended_source_profiles": [
                    str(item).strip()
                    for item in effective_procedure_payload.get("recommended_source_profiles", [])
                    if str(item).strip()
                ],
                "default_execution_target": str(effective_procedure_payload.get("default_execution_target") or "").strip(),
                "risk_profile": str(effective_procedure_payload.get("risk_profile") or "").strip(),
                "status": str(effective_procedure_payload.get("status") or "").strip(),
                "source": effective_procedure_source,
            }
            if effective_procedure_source == "inferred":
                existing_reason = str(route_dict.get("route_reason") or "").strip()
                inferred_reason = f"Inferred procedure: {route_dict['effective_procedure']['procedure_id']}"
                if inferred_reason not in existing_reason:
                    route_dict["route_reason"] = (
                        f"{existing_reason} {inferred_reason}".strip()
                        if existing_reason
                        else inferred_reason
                    )
        route_dict["disable_tools"] = bool(metadata.get("disable_tools"))
        if metadata.get("disable_tools"):
            route_dict["tool_bundle"] = []
            route_dict["mcp_servers"] = []
            existing_reason = str(route_dict.get("route_reason") or "").strip()
            route_dict["route_reason"] = (
                f"{existing_reason} Tools disabled for transient internal signal.".strip()
                if existing_reason
                else "Transient internal signal; tools disabled."
            )
        governed_source_profile, source_profile_reason = self._resolve_governed_source_profile(route_dict)
        if governed_source_profile:
            route_dict["source_profile"] = governed_source_profile
            existing_reason = str(route_dict.get("route_reason") or "").strip()
            if source_profile_reason and source_profile_reason not in existing_reason:
                route_dict["route_reason"] = (
                    f"{existing_reason} {source_profile_reason}".strip()
                    if existing_reason
                    else source_profile_reason
                )
        return route_dict

    def _resolve_route(self, input_info: dict, session: BrainSession, *, reason_prefix: str = "") -> dict[str, Any]:
        metadata = dict(input_info.get("metadata") or {}) if isinstance(input_info, dict) else {}
        content = str(input_info.get("content") or "").strip() if isinstance(input_info, dict) else ""
        if self._mode_manager is None:
            route = self._build_default_route(
                session,
                requested_mode=self._normalize_mode_name(
                    (
                        ((input_info.get("metadata") or {}).get("preferred_mode"))
                        if isinstance(input_info, dict)
                        else ""
                    )
                    or (input_info.get("preferred_mode") if isinstance(input_info, dict) else ""),
                    fallback=ASSISTANT_MODE_NORMAL,
                ),
            )
            if reason_prefix:
                route["route_reason"] = f"{reason_prefix} {route['route_reason']}".strip()
            route["content"] = content
            return self._apply_route_metadata_overrides(route, metadata)

        route = self._mode_manager.route(
            input_info,
            session_metadata=session.metadata,
            source=get_event_context().get("source"),
        )
        route_dict = self._route_to_dict(route)
        if reason_prefix:
            existing_reason = str(route_dict.get("route_reason") or "").strip()
            route_dict["route_reason"] = (
                f"{reason_prefix} {existing_reason}".strip() if existing_reason else reason_prefix.strip()
            )
        route_dict["content"] = content
        return self._apply_route_metadata_overrides(route_dict, metadata)

    def _build_locked_route(self, input_info: dict, session: BrainSession, requested_mode: str) -> dict[str, Any]:
        normalized_mode = self._normalize_mode_name(requested_mode, fallback=ASSISTANT_MODE_AUTO)
        return self._build_route_for_mode(
            input_info,
            session,
            normalized_mode,
            requested_mode=normalized_mode,
            reason=f"User locked mode: {normalized_mode}",
        )

    def _get_requested_mode(self, input_info: dict) -> str:
        metadata = dict(input_info.get("metadata") or {}) if isinstance(input_info, dict) else {}
        raw_mode = metadata.get("preferred_mode")
        if raw_mode is None and isinstance(input_info, dict):
            raw_mode = input_info.get("preferred_mode")
        if raw_mode is None and self._mode_manager is not None:
            raw_mode = self._mode_manager.get_mode_router_config().get("default_mode")
        return self._normalize_mode_name(raw_mode, fallback=ASSISTANT_MODE_NORMAL)

    def _get_explicit_requested_mode(self, input_info: dict) -> str:
        metadata = dict(input_info.get("metadata") or {}) if isinstance(input_info, dict) else {}
        raw_mode = metadata.get("preferred_mode")
        if raw_mode is None and isinstance(input_info, dict):
            raw_mode = input_info.get("preferred_mode")
        return self._normalize_mode_name(raw_mode, fallback="")

    @staticmethod
    def _summarize_text(value: Any, *, limit: int = _MODE_SWITCH_REASON_LIMIT) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return f"{text[: max(0, limit - 3)].rstrip()}..."

    def _get_router_config(self) -> dict[str, Any]:
        if self._mode_manager is None:
            return {}
        getter = getattr(self._mode_manager, "get_mode_router_config", None)
        if not callable(getter):
            return {}
        return dict(getter())

    def _get_router_limit(self, key: str, *, default: int = 0) -> int | None:
        raw_value = self._get_router_config().get(key, default)
        try:
            normalized = int(raw_value)
        except (TypeError, ValueError):
            normalized = default
        if normalized <= 0:
            return None
        return normalized

    def _should_lock_requested_mode(self, requested_mode: str) -> bool:
        if requested_mode not in ASSISTANT_SPECIALIZED_MODES:
            return False
        return bool(self._get_router_config().get("allow_preferred_override", True))

    def _build_route_for_mode(
        self,
        input_info: dict,
        session: BrainSession,
        mode: str,
        *,
        requested_mode: str = ASSISTANT_MODE_AUTO,
        reason: str = "",
    ) -> dict[str, Any]:
        metadata = dict(input_info.get("metadata") or {}) if isinstance(input_info, dict) else {}
        content = str(input_info.get("content") or "").strip() if isinstance(input_info, dict) else ""
        if self._mode_manager is None:
            route = self._build_default_route(
                session,
                requested_mode=requested_mode,
                mode=mode,
                reason=reason,
            )
        else:
            route = self._mode_manager.build_route_for_mode(
                mode,
                requested_mode=requested_mode,
                reason=reason,
                content=content,
            )
        route_dict = self._route_to_dict(route)
        route_dict["content"] = content
        return self._apply_route_metadata_overrides(route_dict, metadata)

    def _initialize_route_for_turn(
        self,
        input_info: dict,
        session: BrainSession,
        requested_mode: str,
    ) -> tuple[dict[str, Any], str]:
        if self._should_lock_requested_mode(requested_mode):
            return self._build_locked_route(input_info, session, requested_mode), "manual_lock"
        if self._get_explicit_requested_mode(input_info) == ASSISTANT_MODE_NORMAL:
            return self._build_route_for_mode(
                input_info,
                session,
                ASSISTANT_MODE_NORMAL,
                requested_mode=ASSISTANT_MODE_NORMAL,
                reason="Preferred mode selected: normal",
            ), "preferred_normal"
        return self._resolve_route(input_info, session), "heuristic"

    def _should_expose_mode_switch_tool(self, requested_mode: str) -> bool:
        if requested_mode not in {ASSISTANT_MODE_AUTO, ASSISTANT_MODE_NORMAL}:
            return False
        return bool(self._get_router_config().get("allow_in_turn_switch", True))

    def _build_mode_switch_tool_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": _INTERNAL_MODE_SWITCH_TOOL_NAME,
                "description": (
                    "Switch to another assistant mode immediately when the next step fits another mode better. "
                    "The route runtime is rebuilt in the same turn, so subsequent tool calls in the same round "
                    "run under the new mode."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": list(ASSISTANT_MODES),
                            "description": "The target assistant mode to activate immediately.",
                        },
                        "reason": {
                            "type": "string",
                            "description": "A short reason for the switch.",
                        },
                    },
                    "required": ["mode", "reason"],
                },
            },
        }

    def _build_mode_switch_policy_messages(self, requested_mode: str) -> list[dict]:
        if not self._should_expose_mode_switch_tool(requested_mode):
            return []
        if requested_mode == ASSISTANT_MODE_NORMAL:
            lines = [
                "[Mode Switching]",
                "The user's preference is normal mode. Treat it as the default working style for ordinary conversation, lightweight planning, and basic web search or direct page reading.",
                "Switch only when the next immediate step clearly needs file tools, deep research constraints, office coordination tools, or study-specific tools.",
                "Call switch_assistant_mode as soon as the next step needs another mode. After the switch, continue the same turn with tools from the rebuilt route runtime.",
            ]
        else:
            lines = [
                "[Mode Switching]",
                "If the next immediate step belongs to another mode, call switch_assistant_mode before using tools from that mode.",
                "Once the switch succeeds, continue the same turn under the rebuilt mode, prompt, and tool bundle.",
            ]
        if self._mode_manager is not None:
            glossary = str(self._mode_manager.get_auto_router_prompt() or "").strip()
            if glossary:
                lines.append(glossary)
        return [{"role": "system", "content": "\n".join(lines)}]

    def _store_route_context(self, session: BrainSession, route_context: dict[str, Any]) -> None:
        session.metadata["current_route"] = dict(route_context)
        session.metadata["current_mode"] = route_context.get("current_mode", "")
        session.metadata["route_reason"] = route_context.get("route_reason", "")
        session.metadata["source_profile"] = route_context.get("source_profile", "")
        session.metadata["loaded_skills"] = list(route_context.get("loaded_skills") or [])

    def _append_route_history_entry(
        self,
        session: BrainSession,
        route_history: list[dict[str, Any]],
        *,
        round_index: int,
        route_context: dict[str, Any],
        origin: str,
        switch_count: int,
        from_mode: str = "",
        to_mode: str = "",
        reason: str | None = None,
    ) -> None:
        current_mode = str(route_context.get("current_mode") or "").strip()
        route_history.append(
            {
                "round": round_index,
                "mode": current_mode,
                "from_mode": from_mode,
                "to_mode": to_mode or current_mode,
                "reason": str(reason if reason is not None else route_context.get("route_reason") or ""),
                "source_profile": route_context.get("source_profile", ""),
                "origin": origin,
                "switch_count": switch_count,
            }
        )
        session.metadata["route_history"] = list(route_history)

    def _sync_runtime_route_state(self, session_id: str, session: BrainSession, route_context: dict[str, Any]) -> None:
        runtime_state = session.runtime_state
        self.set_session_runtime_state(
            session_id,
            runtime_state.status or RuntimeStatus.IDLE.value,
            detail=runtime_state.detail,
            active_tools=list(runtime_state.active_tools),
            current_mode=route_context.get("current_mode", ""),
            route_reason=route_context.get("route_reason", ""),
            action_risk=runtime_state.action_risk or "read",
            source_profile=route_context.get("source_profile", ""),
            stream_id=runtime_state.stream_id,
            turn_id=runtime_state.turn_id,
        )

    def _execute_mode_switch_tool(
        self,
        *,
        tool_args: dict[str, Any],
        input_info: dict,
        session: BrainSession,
        route_context: dict[str, Any],
        requested_mode: str,
        switch_count: int,
    ) -> _ModeSwitchResult:
        current_mode = str(route_context.get("current_mode") or "").strip() or ASSISTANT_MODE_NORMAL
        normalized_reason = self._summarize_text((tool_args or {}).get("reason"), limit=_MODE_SWITCH_REASON_LIMIT)
        router_config = self._get_router_config()

        if requested_mode in ASSISTANT_SPECIALIZED_MODES:
            return _ModeSwitchResult(
                message=f"Mode is locked for this turn; staying in {current_mode}.",
                route_context=dict(route_context),
                switch_count=switch_count,
                origin="switch_tool_locked",
                from_mode=current_mode,
                to_mode=current_mode,
            )

        if not bool(router_config.get("allow_in_turn_switch", True)):
            return _ModeSwitchResult(
                message=f"In-turn mode switching is disabled; staying in {current_mode}.",
                route_context=dict(route_context),
                switch_count=switch_count,
                origin="switch_tool_disabled",
                from_mode=current_mode,
                to_mode=current_mode,
            )

        raw_mode = (tool_args or {}).get("mode")
        target_mode = self._normalize_mode_name(raw_mode, fallback="")
        if target_mode not in ASSISTANT_MODES:
            return _ModeSwitchResult(
                message=f'Invalid assistant mode "{raw_mode}".',
                route_context=dict(route_context),
                switch_count=switch_count,
                origin="switch_tool_invalid",
                from_mode=current_mode,
                to_mode=current_mode,
            )

        if target_mode == current_mode:
            return _ModeSwitchResult(
                message=f"Already in {current_mode}; no switch needed.",
                route_context=dict(route_context),
                switch_count=switch_count,
                origin="switch_tool_noop",
                from_mode=current_mode,
                to_mode=current_mode,
            )

        max_switches = self._get_router_limit("max_switches_per_turn")
        if max_switches is not None and switch_count >= max_switches:
            return _ModeSwitchResult(
                message=f"max_switches_per_turn={max_switches} reached; staying in {current_mode}.",
                route_context=dict(route_context),
                switch_count=switch_count,
                origin="switch_tool_limit",
                from_mode=current_mode,
                to_mode=current_mode,
            )

        reason = normalized_reason or f"Switching from {current_mode} to {target_mode}"
        new_route = self._build_route_for_mode(
            input_info,
            session,
            target_mode,
            requested_mode=requested_mode,
            reason=f"Brain switched mode: {reason}",
        )
        return _ModeSwitchResult(
            message=f"Switched mode to {target_mode} because {reason}.",
            route_context=new_route,
            switch_count=switch_count + 1,
            origin="switch_tool",
            from_mode=current_mode,
            to_mode=target_mode,
            applied=True,
        )

    def _build_mode_policy_messages(self, route_context: dict[str, Any], *, requested_mode: str) -> list[dict]:
        mode = str(route_context.get("current_mode") or "").strip()
        if not mode:
            return []

        route_reason = str(route_context.get("route_reason") or "").strip()
        source_profile = str(route_context.get("source_profile") or "").strip()
        header = (
            "[Assistant Mode]\n"
            f"Current mode: {mode}\n"
            f"Routing reason: {route_reason or 'n/a'}\n"
            f"Source profile: {source_profile or 'n/a'}"
        )
        messages = [{"role": "system", "content": header}]
        if self._mode_manager is not None:
            assembler = getattr(self._mode_manager, "assemble_prompt_for_route", None)
            if callable(assembler):
                prompt_text = assembler(route_context)
            else:
                prompt_text = self._mode_manager.get_prompt_for_mode(mode)
            if prompt_text:
                messages.append({"role": "system", "content": prompt_text})
        messages.extend(self._build_mode_switch_policy_messages(requested_mode))
        return messages

    def _get_tools_for_route(self, route_context: dict[str, Any], *, requested_mode: str) -> list[dict]:
        tools: list[dict] = []
        if not bool(route_context.get("disable_tools")):
            getter = getattr(self._tools_manager, "get_all_tools", None)
            if callable(getter):
                try:
                    tools = list(getter(route_context=route_context))
                except TypeError:
                    tools = list(getter())
        if self._should_expose_mode_switch_tool(requested_mode) and not any(
            tool.get("function", {}).get("name") == _INTERNAL_MODE_SWITCH_TOOL_NAME
            for tool in tools
        ):
            tools.append(self._build_mode_switch_tool_schema())
        return tools

    async def _call_tool_with_route(
        self,
        tool_name: str,
        tool_args: dict,
        *,
        session_id: str,
        source,
        tool_activity_callback,
        route_context: dict[str, Any],
    ) -> ToolCallResult:
        if bool(route_context.get("disable_tools")):
            action_risk = self._get_action_risk_for_tools([tool_name])
            return ToolCallResult.failure(
                tool_name=tool_name,
                source=ToolSourceType.UNKNOWN,
                action_risk=action_risk,
                code="tool_not_allowed",
                category=ToolErrorCategory.PERMISSION,
                message="Tool call was denied by the current route policy.",
                details={
                    "tool_name": tool_name,
                    "current_mode": route_context.get("current_mode"),
                },
            )
        caller = getattr(self._tools_manager, "call_tool")
        try:
            raw_result = await caller(
                tool_name,
                tool_args,
                session_id=session_id,
                source=source,
                tool_activity_callback=tool_activity_callback,
                route_context=route_context,
            )
        except TypeError:
            raw_result = await caller(
                tool_name,
                tool_args,
                session_id=session_id,
                source=source,
                tool_activity_callback=tool_activity_callback,
            )
        return normalize_tool_result(
            raw_result,
            tool_name=tool_name,
            source=ToolSourceType.UNKNOWN,
            action_risk=self._get_action_risk_for_tools([tool_name]),
        )

    @staticmethod
    def _tool_message_content(result: ToolCallResult) -> str:
        return result.as_message_content()

    @staticmethod
    def _tool_result_payload(result: ToolCallResult) -> Any:
        payload = result.content.data
        if payload is not None:
            return payload
        if not result.content.text:
            return None
        try:
            return json.loads(result.content.text)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _sanitize_memory_scope(payload: dict[str, Any] | None, *, session_id: str) -> dict[str, Any]:
        payload = payload or {}
        return {
            "session_id": session_id,
            "prefetched": bool(payload),
            "found": bool(payload.get("found", False)),
            "profile_count": len(payload.get("profile", [])) if isinstance(payload.get("profile"), list) else 0,
            "fact_count": len(payload.get("facts", [])) if isinstance(payload.get("facts"), list) else 0,
            "recent_event_count": (
                len(payload.get("recent_events", []))
                if isinstance(payload.get("recent_events"), list)
                else 0
            ),
        }

    @staticmethod
    def _sanitize_authorization_decision(payload: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(payload or {})
        details = dict(payload.get("details") or {})
        redacted_details = {
            key: value
            for key, value in details.items()
            if key not in {"command", "path", "trusted_write_roots"}
        }
        return {
            "tool_name": str(payload.get("tool_name") or ""),
            "allowed": bool(payload.get("allowed", False)),
            "visibility": str(payload.get("visibility") or ""),
            "action_risk": str(payload.get("action_risk") or ""),
            "read_only": bool(payload.get("read_only", False)),
            "requires_confirmation": bool(payload.get("requires_confirmation", False)),
            "confirmation_kind": str(payload.get("confirmation_kind") or ""),
            "write_boundary": str(payload.get("write_boundary") or ""),
            "trusted_root": payload.get("trusted_root"),
            "policy_sources": [
                str(item).strip()
                for item in payload.get("policy_sources", [])
                if str(item).strip()
            ],
            "reason_code": str(payload.get("reason_code") or ""),
            "reason_message": str(payload.get("reason_message") or ""),
            "details": redacted_details,
        }

    def _record_authorization_result(self, session: BrainSession, result: ToolCallResult) -> None:
        authorization = result.metadata.get("authorization") if isinstance(result.metadata, dict) else None
        object_operation = self._tool_result_payload(result)
        snapshot = {
            "tool_name": result.tool_name,
            "ok": bool(result.ok),
            "action_risk": result.action_risk,
            "authorization": self._sanitize_authorization_decision(authorization if isinstance(authorization, dict) else {}),
            "error": result.error.model_dump(mode="json") if result.error is not None else None,
            "object_operation": (
                redacted_object_debug_entry(object_operation)
                if isinstance(object_operation, dict) and object_operation.get("kind") == "object_operation"
                else None
            ),
        }
        history = [
            dict(item)
            for item in session.metadata.get("last_authorization_decisions", [])
            if isinstance(item, dict)
        ]
        history.append(snapshot)
        session.metadata["last_authorization_decisions"] = history[-12:]
        if isinstance(object_operation, dict) and object_operation.get("kind") == "object_operation":
            operations = [
                dict(item)
                for item in session.metadata.get("last_object_operations", [])
                if isinstance(item, dict)
            ]
            operations.append(redacted_object_debug_entry(object_operation))
            session.metadata["last_object_operations"] = operations[-12:]

    @staticmethod
    def _sanitize_route_context(route_context: dict[str, Any] | None) -> dict[str, Any]:
        route_context = route_context or {}
        authorization_policy = route_context.get("authorization_policy")
        return {
            "requested_mode": str(route_context.get("requested_mode") or ""),
            "current_mode": str(route_context.get("current_mode") or ""),
            "route_reason": str(route_context.get("route_reason") or ""),
            "source_profile": str(route_context.get("source_profile") or ""),
            "tool_bundle": [
                str(item).strip()
                for item in route_context.get("tool_bundle", [])
                if str(item).strip()
            ],
            "mcp_servers": [
                str(item).strip()
                for item in route_context.get("mcp_servers", [])
                if str(item).strip()
            ],
            "prompt_bundle": str(route_context.get("prompt_bundle") or ""),
            "active_skills": [
                str(item).strip()
                for item in route_context.get("active_skills", [])
                if str(item).strip()
            ],
            "loaded_skills": [
                str(item).strip()
                for item in route_context.get("loaded_skills", [])
                if str(item).strip()
            ],
            "confidence": str(route_context.get("confidence") or ""),
            "should_preload_context": bool(route_context.get("should_preload_context", False)),
            "prefer_live_web": bool(route_context.get("prefer_live_web", False)),
            "signals": [
                str(item).strip()
                for item in route_context.get("signals", [])
                if str(item).strip()
            ],
            "adapter_name": str(route_context.get("adapter_name") or ""),
            "used_keyword_fallback": bool(route_context.get("used_keyword_fallback", False)),
            "authorization_policy": dict(authorization_policy or {}) if isinstance(authorization_policy, dict) else {},
            "disable_tools": bool(route_context.get("disable_tools", False)),
        }

    async def _execute_visible_tool_calls(
        self,
        *,
        visible_tool_calls: list[Any],
        session: BrainSession,
        session_id: str,
        route_context: dict[str, Any],
        tool_activity_callback,
    ) -> None:
        plan_items: list[_ToolExecutionPlanItem] = []
        for index, tool_call in enumerate(visible_tool_calls):
            try:
                args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
            except Exception:
                args = {}
            plan_items.append(
                _ToolExecutionPlanItem(
                    index=index,
                    tool_call=tool_call,
                    args=dict(args),
                    policy=self._get_tool_parallel_policy(tool_call.name, dict(args), route_context),
                )
            )

        max_parallel_tool_calls = self._resolve_max_parallel_tool_calls(route_context)
        ordered_results: dict[int, ToolCallResult] = {}
        pending_parallel_batch: list[_ToolExecutionPlanItem] = []

        async def _execute_plan_item(item: _ToolExecutionPlanItem) -> ToolCallResult:
            tool_call = item.tool_call
            tool_context = bind_event_context(tool_call_id=tool_call.id)
            try:
                context = get_event_context()
                return await self._call_tool_with_route(
                    tool_call.name,
                    item.args,
                    session_id=context.get("session_id", session_id),
                    source=context.get("source"),
                    tool_activity_callback=tool_activity_callback,
                    route_context=route_context,
                )
            except Exception as exc:
                return ToolCallResult.failure(
                    tool_name=tool_call.name,
                    source=ToolSourceType.UNKNOWN,
                    action_risk=self._get_action_risk_for_tools([tool_call.name]),
                    code="tool_dispatch_failed",
                    category=ToolErrorCategory.EXECUTION,
                    message="Tool dispatch failed before producing a result.",
                    details={
                        "tool_name": tool_call.name,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    },
                )
            finally:
                reset_event_context(tool_context)

        async def _flush_parallel_batch() -> None:
            nonlocal pending_parallel_batch
            if not pending_parallel_batch:
                return
            session.runtime_state.update(
                status=session.runtime_state.status,
                detail=session.runtime_state.detail,
                active_tools=[item.tool_call.name for item in pending_parallel_batch],
            )
            task_results = await asyncio.gather(*[_execute_plan_item(item) for item in pending_parallel_batch])
            for item, result in zip(pending_parallel_batch, task_results):
                ordered_results[item.index] = result
            pending_parallel_batch = []

        for item in plan_items:
            if not self._can_join_parallel_batch(
                item,
                current_batch=pending_parallel_batch,
                global_limit=max_parallel_tool_calls,
            ):
                await _flush_parallel_batch()
                if self._can_join_parallel_batch(item, current_batch=pending_parallel_batch, global_limit=max_parallel_tool_calls):
                    pending_parallel_batch.append(item)
                    continue
                session.runtime_state.update(
                    status=session.runtime_state.status,
                    detail=session.runtime_state.detail,
                    active_tools=[item.tool_call.name],
                )
                ordered_results[item.index] = await _execute_plan_item(item)
                continue
            pending_parallel_batch.append(item)
        await _flush_parallel_batch()

        for item in plan_items:
            result = ordered_results.get(item.index)
            if result is None:
                result = ToolCallResult.failure(
                    tool_name=item.tool_call.name,
                    source=ToolSourceType.UNKNOWN,
                    action_risk=self._get_action_risk_for_tools([item.tool_call.name]),
                    code="tool_result_missing",
                    category=ToolErrorCategory.EXECUTION,
                    message="Tool scheduler produced no result.",
                )
            self._record_authorization_result(session, result)
            session.chat_history.append(
                {
                    "role": "tool",
                    "content": self._tool_message_content(result),
                    "tool_call_id": item.tool_call.id,
                }
            )

    def _get_action_risk_for_tools(self, tool_names: list[str]) -> str:
        getter = getattr(self._tools_manager, "get_action_risk_for_tools", None)
        if callable(getter):
            return str(getter(tool_names))
        return "read"

    def _resolve_max_parallel_tool_calls(self, route_context: dict[str, Any]) -> int:
        route_limit = route_context.get("max_parallel_tool_calls")
        try:
            normalized_route_limit = int(route_limit)
        except (TypeError, ValueError):
            normalized_route_limit = 0
        if normalized_route_limit > 0:
            return normalized_route_limit
        router_limit = self._get_router_limit("max_parallel_tool_calls", default=3)
        return int(router_limit or 3)

    def _get_tool_parallel_policy(self, tool_name: str, tool_args: dict[str, Any], route_context: dict[str, Any]) -> dict[str, Any]:
        getter = getattr(self._tools_manager, "get_tool_parallel_metadata", None)
        if callable(getter):
            metadata = getter(tool_name, tool_args, route_context=route_context)
            if isinstance(metadata, dict):
                return dict(metadata)
        action_risk = self._get_action_risk_for_tools([tool_name])
        return {
            "safe_parallel": action_risk == "read",
            "parallel_group": action_risk,
            "resource_key": f"tool:{tool_name}",
            "mutates_state": action_risk != "read",
            "requires_order": action_risk != "read",
            "max_concurrency": 1 if action_risk != "read" else 3,
        }

    @staticmethod
    def _can_join_parallel_batch(
        item: _ToolExecutionPlanItem,
        *,
        current_batch: list[_ToolExecutionPlanItem],
        global_limit: int,
    ) -> bool:
        if len(current_batch) >= global_limit:
            return False
        policy = item.policy
        if not bool(policy.get("safe_parallel", False)):
            return False
        if bool(policy.get("requires_order", False)):
            return False

        resource_key = str(policy.get("resource_key") or "").strip()
        parallel_group = str(policy.get("parallel_group") or "").strip()
        try:
            max_concurrency = max(1, int(policy.get("max_concurrency", 1) or 1))
        except (TypeError, ValueError):
            max_concurrency = 1
        group_counter = Counter(
            str(existing.policy.get("parallel_group") or "").strip()
            for existing in current_batch
            if str(existing.policy.get("parallel_group") or "").strip()
        )
        if parallel_group and group_counter[parallel_group] >= max_concurrency:
            return False
        if resource_key and any(str(existing.policy.get("resource_key") or "").strip() == resource_key for existing in current_batch):
            return False
        return True

    async def run_background_turn(
        self,
        *,
        session_id: str,
        api_url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        source=None,
        route_context: dict[str, Any] | None = None,
        max_rounds: int = 6,
        adapter_options: dict[str, Any] | None = None,
        tool_activity_callback=None,
        phase_callback=None,
    ) -> dict[str, Any]:
        if self._http_session is None:
            raise RuntimeError("Brain HTTP session not initialized. Call init_brain() first.")

        normalized_session_id = str(session_id or "").strip() or "system:background"
        session = self.get_or_create_session(normalized_session_id)
        visible_tools = list(tools or [])
        resolved_route_context = dict(route_context or {})
        resolved_route_context.setdefault(
            "tool_bundle",
            [
                str(tool.get("function", {}).get("name", "")).strip()
                for tool in visible_tools
                if str(tool.get("function", {}).get("name", "")).strip()
            ],
        )
        resolved_route_context.setdefault("mcp_servers", [])
        resolved_route_context.setdefault("current_mode", "scheduled_task")
        resolved_route_context.setdefault("route_reason", "Running a scheduled background task.")
        resolved_route_context.setdefault("source_profile", "scheduled_tasks")
        self._store_route_context(session, resolved_route_context)
        self._sync_runtime_route_state(normalized_session_id, session, resolved_route_context)

        adapter_options = dict(adapter_options or {})
        history = [dict(message) for message in messages]
        last_content = ""
        last_tool_names: list[str] = []
        completed_task_keys: list[str] = []
        manage_task_actions: list[dict[str, Any]] = []

        try:
            for _ in range(max_rounds):
                if phase_callback:
                    self.set_session_runtime_state(
                        normalized_session_id,
                        RuntimeStatus.THINKING.value,
                        detail="Calling model",
                        active_tools=[],
                        current_mode=resolved_route_context.get("current_mode", ""),
                        route_reason=resolved_route_context.get("route_reason", ""),
                        action_risk="read",
                        source_profile=resolved_route_context.get("source_profile", ""),
                    )
                    await phase_callback(RuntimeStatus.THINKING.value, "Calling model")

                result = await self._adapter.chat(
                    self._http_session,
                    api_url,
                    api_key,
                    model,
                    history,
                    tools=visible_tools,
                    **adapter_options,
                )

                last_content = str(result.get("content") or "").strip()
                tool_calls = list(result.get("tool_calls") or [])
                assistant_message: dict[str, Any] = {"role": "assistant", "content": last_content or None}
                if tool_calls:
                    reasoning_content = str(result.get("reasoning_content") or "").strip()
                    if reasoning_content:
                        assistant_message["reasoning_content"] = reasoning_content
                    assistant_message["tool_calls"] = [
                        {
                            "type": "function",
                            "id": tc.id,
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments_str,
                            },
                        }
                        for tc in tool_calls
                    ]
                history.append(assistant_message)

                if not tool_calls:
                    return {
                        "status": "ok",
                        "content": last_content,
                        "tool_names": last_tool_names,
                        "completed_task_keys": list(dict.fromkeys(completed_task_keys)),
                        "manage_task_actions": manage_task_actions,
                        "history": history,
                    }

                last_tool_names = [tc.name for tc in tool_calls]
                action_risk = self._get_action_risk_for_tools(last_tool_names)
                self.set_session_runtime_state(
                    normalized_session_id,
                    RuntimeStatus.TOOL_CALLING.value,
                    detail=", ".join(last_tool_names),
                    active_tools=last_tool_names,
                    current_mode=resolved_route_context.get("current_mode", ""),
                    route_reason=resolved_route_context.get("route_reason", ""),
                    action_risk=action_risk,
                    source_profile=resolved_route_context.get("source_profile", ""),
                )
                if phase_callback:
                    await phase_callback(RuntimeStatus.TOOL_CALLING.value, ", ".join(last_tool_names), last_tool_names)

                for tool_call in tool_calls:
                    tool_args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
                    if tool_call.name in {"manage_tasks", "manage_scheduled_tasks"}:
                        action = str(tool_args.get("action") or "").strip().lower()
                        task_key = str(tool_args.get("task_key") or "").strip()
                        manage_task_actions.append(
                            {
                                "action": action,
                                "task_key": task_key,
                                "arguments": json.loads(json.dumps(tool_args, ensure_ascii=False, default=str)),
                            }
                        )
                        if action == "complete" and task_key:
                            completed_task_keys.append(task_key)
                    tool_context = bind_event_context(tool_call_id=tool_call.id)
                    try:
                        try:
                            tool_result = await self._call_tool_with_route(
                                tool_call.name,
                                tool_args,
                                session_id=normalized_session_id,
                                source=source,
                                tool_activity_callback=tool_activity_callback,
                                route_context=resolved_route_context,
                            )
                        except Exception as exc:
                            logger.error("Background tool call failed: %s", exc)
                            tool_result = ToolCallResult.failure(
                                tool_name=tool_call.name,
                                source=ToolSourceType.UNKNOWN,
                                action_risk=self._get_action_risk_for_tools([tool_call.name]),
                                code="tool_dispatch_failed",
                                category=ToolErrorCategory.EXECUTION,
                                message="Tool dispatch failed before producing a result.",
                                details={
                                    "tool_name": tool_call.name,
                                    "exception_type": type(exc).__name__,
                                    "exception_message": str(exc),
                                },
                            )
                    finally:
                        reset_event_context(tool_context)

                    history.append(
                        {
                            "role": "tool",
                            "content": self._tool_message_content(tool_result),
                            "tool_call_id": tool_call.id,
                        }
                    )

            return {
                "status": "error",
                "content": "Background task exceeded max tool rounds.",
                "tool_names": last_tool_names,
                "completed_task_keys": list(dict.fromkeys(completed_task_keys)),
                "manage_task_actions": manage_task_actions,
                "history": history,
            }
        finally:
            self.set_session_runtime_state(
                normalized_session_id,
                RuntimeStatus.IDLE.value,
                detail="",
                active_tools=[],
                current_mode=resolved_route_context.get("current_mode", ""),
                route_reason=resolved_route_context.get("route_reason", ""),
                action_risk="read",
                source_profile=resolved_route_context.get("source_profile", ""),
            )

    def _build_recent_context_summary(self, session: BrainSession) -> str:
        base_count = self._base_message_count()
        if len(session.chat_history) <= base_count:
            return ""
        recent = [
            message
            for message in session.chat_history[base_count:]
            if not bool(dict(message.get("metadata") or {}).get("transient"))
        ]
        lines = []
        for msg in recent[-6:]:
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                lines.append(f"[{msg.get('role', '')}]: {content[:200]}")
        return "\n".join(lines)

    async def _persist_session_context(self, session: BrainSession):
        summary = self._build_recent_context_summary(session)
        if not summary:
            return
        try:
            await self._context_manager.update_context(summary, session_id=session.session_id)
        except Exception as exc:
            logger.error("Failed to save context on close: %s", exc)

    def _should_prefetch_memory(self, input_info: dict) -> bool:
        if str(input_info.get("role") or "") != "user":
            return False
        content = input_info.get("content")
        if not isinstance(content, str):
            return False
        normalized = content.strip().lower()
        return bool(normalized) and normalized not in AUTO_MEMORY_SKIP_TOKENS

    async def _build_auto_memory_message(self, session_id: str, input_info: dict) -> dict | None:
        if not self._should_prefetch_memory(input_info):
            return None
        content = input_info.get("content")
        if not isinstance(content, str):
            return None

        context = get_event_context()
        try:
            result = await self._tools_manager.call_tool(
                "search_memory",
                {"query": content},
                session_id=context.get("session_id", session_id),
                source=context.get("source"),
            )
            normalized_result = normalize_tool_result(
                result,
                tool_name="search_memory",
                source=ToolSourceType.UNKNOWN,
                action_risk="read",
            )
            payload = self._tool_result_payload(normalized_result)
            if normalized_result.error is not None or not isinstance(payload, dict):
                return None
        except Exception as exc:
            logger.warning("Automatic memory prefetch failed: %s", exc)
            return None

        if not payload.get("found"):
            return None

        return {
            "role": "system",
            "content": (
                "[自动检索到的相关长期记忆]\n"
                "以下内容与当前输入可能相关，仅作为参考；如果与用户当前输入冲突，以当前输入为准。\n"
                + json.dumps(payload, ensure_ascii=False)
            ),
            "metadata": {
                "memory_scope": self._sanitize_memory_scope(payload, session_id=session_id),
            },
        }

    async def _store_turn_episode(self, session_id: str, input_info: dict, *, transient_turn: bool) -> None:
        if transient_turn:
            return
        if str(input_info.get("role") or "") != "user":
            return
        content = input_info.get("content")
        if not isinstance(content, str) or not content.strip():
            return
        memory = getattr(self._context_manager, "_memory", None)
        if memory is None:
            return
        context = get_event_context()
        try:
            await memory.save_memory(
                memory_text=content,
                session_id=context.get("session_id", session_id),
                source=context.get("source"),
            )
        except Exception as exc:
            logger.warning("Automatic episode write failed: %s", exc)

    def _detect_memory_trigger_categories(self, content: str) -> list[dict]:
        text = str(content or "").strip()
        if not text:
            return []
        for pattern in MEMORY_HINT_SUPPRESS_PATTERNS:
            if pattern.search(text):
                return []

        matched = []
        for rule in MEMORY_TRIGGER_RULES:
            if any(pattern.search(text) for pattern in rule["patterns"]):
                matched.append(
                    {
                        "category": rule["category"],
                        "label": rule["label"],
                        "description": rule["description"],
                    }
                )
        return matched

    def _build_memory_trigger_message(self, input_info: dict) -> dict | None:
        if str(input_info.get("role") or "") != "user":
            return None
        content = input_info.get("content")
        if not isinstance(content, str):
            return None

        matched = self._detect_memory_trigger_categories(content)
        if not matched:
            return None

        lines = [
            "[Memory Trigger Hint]",
            "The current user message likely contains durable personal information worth remembering after you answer.",
            "If you store memory, distill it into one concise proposition and use remember_knowledge once per important fact or commitment.",
            "Remember-worthy signals detected:",
        ]
        for item in matched:
            lines.append(f"- {item['category']}: {item['label']} ({item['description']})")
        lines.extend(
            [
                "Usually worth remembering:",
                '- "My name is Alex and I live in Hangzhou."',
                '- "I prefer black coffee and usually work late."',
                '- "I am still working on the payment callback bug."',
                '- "Remind me next week to ship the board back."',
                "Usually not worth remembering:",
                '- "I feel sleepy today."',
                '- "I just finished lunch."',
                '- "That meme is funny."',
            ]
        )
        return {"role": "system", "content": "\n".join(lines)}

    @staticmethod
    def _normalize_usage(raw_usage: dict | None) -> UsageCounters | None:
        if not raw_usage:
            return None
        prompt_tokens = int(raw_usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(raw_usage.get("completion_tokens", 0) or 0)
        reasoning_tokens = int(raw_usage.get("reasoning_tokens", 0) or 0)
        total_tokens = int(
            raw_usage.get("total_tokens", 0)
            or (prompt_tokens + completion_tokens + reasoning_tokens)
        )
        return UsageCounters(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
        )

    def _estimate_call_usage(
        self,
        *,
        context_breakdown: dict[str, int],
        assistant_content: str,
        reasoning_text: str,
        tool_calls: list,
        provider_items: list[dict[str, Any]] | None = None,
    ) -> UsageCounters:
        assistant_message = {"role": "assistant", "content": assistant_content}
        if tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "type": "function",
                    "id": tc.id,
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments_str,
                    },
                }
                for tc in tool_calls
            ]
        if provider_items:
            assistant_message["provider_items"] = list(provider_items)
        completion_tokens = self._estimate_message_tokens(assistant_message)
        reasoning_tokens = self._estimate_text_tokens(reasoning_text)
        prompt_tokens = int(context_breakdown.get("total", 0) or 0)
        return UsageCounters(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=prompt_tokens + completion_tokens + reasoning_tokens,
        )

    def _estimate_message_tokens(self, message: dict) -> int:
        estimator = getattr(self._context_manager, "estimate_message_tokens", None)
        if callable(estimator):
            return int(estimator(message))
        content = message.get("content", "")
        total_chars = len(content) if isinstance(content, str) else 0
        if message.get("tool_calls"):
            total_chars += len(json.dumps(message["tool_calls"], ensure_ascii=False))
        return int(total_chars / 1.8)

    def _estimate_text_tokens(self, text: str) -> int:
        estimator = getattr(self._context_manager, "estimate_text_tokens", None)
        if callable(estimator):
            return int(estimator(text))
        return int(len(str(text or "")) / 1.8)

    def _get_context_limit(self, model: str) -> int:
        getter = getattr(self._context_manager, "get_context_limit", None)
        if callable(getter):
            return int(getter(model))
        adapter_getter = getattr(self._adapter, "get_context_limit", None)
        if callable(adapter_getter):
            return int(adapter_getter(model))
        return 8192

    async def _resolve_context_limit_info(
        self,
        *,
        model: str,
        api_url: str,
        provider_name: str = "",
    ) -> dict[str, Any]:
        effective_provider = str(provider_name or self._provider_name or "").strip()
        resolver = getattr(self._mode_manager, "resolve_context_limit", None)
        if callable(resolver):
            try:
                payload = await resolver(
                    provider_name=effective_provider,
                    api_url=api_url,
                    model_name=model,
                    adapter=self._adapter,
                )
                if isinstance(payload, dict) and int(payload.get("context_limit_tokens", 0) or 0) > 0:
                    payload.setdefault("context_limit_source", "fallback")
                    payload.setdefault("context_limit_model", str(model or ""))
                    payload.setdefault("context_limit_confidence", "medium")
                    return payload
            except Exception as exc:
                logger.warning("Failed to resolve context limit for %s/%s: %s", effective_provider, model, exc)

        return {
            "context_limit_tokens": self._get_context_limit(model),
            "context_limit_source": "fallback",
            "context_limit_model": str(model or ""),
            "context_limit_confidence": "low",
        }

    def _build_context_breakdown(
        self,
        *,
        session_history_before_turn: list[dict],
        current_turn_messages: list[dict],
        auto_memory_message: dict | None,
        policy_messages: list[dict],
        proprioception_message: dict | None,
    ) -> dict[str, int]:
        builder = getattr(self._context_manager, "build_context_breakdown", None)
        if callable(builder):
            return builder(
                session_history_before_turn=session_history_before_turn,
                current_turn_messages=current_turn_messages,
                auto_memory_message=auto_memory_message,
                policy_messages=policy_messages,
                proprioception_message=proprioception_message,
            )

        def sum_tokens(messages: list[dict]) -> int:
            return sum(self._estimate_message_tokens(message) for message in messages)

        system_tokens = 0
        history_tokens = 0
        tool_history_tokens = 0
        for message in session_history_before_turn:
            tokens = self._estimate_message_tokens(message)
            if message.get("role") == "system":
                system_tokens += tokens
            elif message.get("role") == "tool" or message.get("tool_calls"):
                tool_history_tokens += tokens
            else:
                history_tokens += tokens

        memory_tokens = self._estimate_message_tokens(auto_memory_message or {})
        policy_tokens = sum_tokens(policy_messages)
        current_input_tokens = sum_tokens(current_turn_messages)
        proprioception_tokens = self._estimate_message_tokens(proprioception_message or {})
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

    def _conversation_summary_for_session(self, session: BrainSession) -> str:
        text = str(session.metadata.get("conversation_summary") or "").strip()
        if text:
            return text
        return str(self._global_context or "").strip()

    async def _build_context_plan(
        self,
        *,
        session: BrainSession,
        turn_input_index: int,
        current_turn_messages: list[dict],
        auto_memory_message: dict | None,
        policy_messages: list[dict],
        proprioception_message: dict | None,
        route_context: dict[str, Any],
        requested_mode: str,
        model: str,
        provider_name: str,
        api_url: str,
        context_limit_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        builder = getattr(self._context_manager, "build_context_plan", None)
        session_history_before_turn = session.chat_history[:turn_input_index]
        context_limit_override = int((context_limit_info or {}).get("context_limit_tokens", 0) or 0)
        if callable(builder):
            try:
                return await builder(
                    session_history_before_turn=session_history_before_turn,
                    current_turn_messages=current_turn_messages,
                    auto_memory_message=auto_memory_message,
                    policy_messages=policy_messages,
                    proprioception_message=proprioception_message,
                    conversation_summary=self._conversation_summary_for_session(session),
                    route_context=route_context,
                    requested_mode=requested_mode,
                    model=model,
                    provider_name=provider_name,
                    api_url=api_url,
                    context_limit_override=context_limit_override,
                )
            except TypeError:
                pass

        messages = (
            session_history_before_turn
            + ([auto_memory_message] if auto_memory_message else [])
            + policy_messages
            + current_turn_messages
            + ([proprioception_message] if proprioception_message else [])
        )
        return {
            "messages": messages,
            "breakdown": self._build_context_breakdown(
                session_history_before_turn=session_history_before_turn,
                current_turn_messages=current_turn_messages,
                auto_memory_message=auto_memory_message,
                policy_messages=policy_messages,
                proprioception_message=proprioception_message,
            ),
            "length_policy": {},
            "layers": {},
        }

    @staticmethod
    def _build_adapter_options(model_options: dict | None) -> dict:
        model_options = model_options or {}
        thinking = model_options.get("thinking") or {}
        return {
            "thinking": thinking.get("enabled"),
            "thinking_effort": thinking.get("effort"),
            "thinking_budget": thinking.get("budget_tokens"),
        }

    def _update_usage_snapshot(
        self,
        session: BrainSession,
        *,
        model: str,
        context_breakdown: dict[str, int],
        context_budget_breakdown: dict[str, Any] | None,
        turn_usage: UsageCounters,
        usage_source: str,
        context_limit_info: dict[str, Any] | None = None,
    ) -> dict:
        context_limit_info = context_limit_info or {}
        session.usage_snapshot.usage_ready = True
        session.usage_snapshot.context_limit_tokens = int(
            context_limit_info.get("context_limit_tokens", 0) or self._get_context_limit(model)
        )
        session.usage_snapshot.context_limit_source = str(
            context_limit_info.get("context_limit_source") or "fallback"
        )
        session.usage_snapshot.context_limit_model = str(
            context_limit_info.get("context_limit_model") or model or ""
        )
        session.usage_snapshot.context_limit_confidence = str(
            context_limit_info.get("context_limit_confidence") or "low"
        )
        session.usage_snapshot.context_breakdown = ContextBreakdown.from_mapping(context_breakdown)
        session.usage_snapshot.context_budget_breakdown = dict(context_budget_breakdown or {})
        session.usage_snapshot.current_context_tokens_estimated = session.usage_snapshot.context_breakdown.total
        session.usage_snapshot.last_turn_usage = UsageCounters(
            prompt_tokens=turn_usage.prompt_tokens,
            completion_tokens=turn_usage.completion_tokens,
            reasoning_tokens=turn_usage.reasoning_tokens,
            total_tokens=turn_usage.total_tokens,
        )
        session.usage_snapshot.usage_source = usage_source
        session.usage_snapshot.updated_at = utcnow_iso()
        session.metadata["last_context_snapshot"] = session.usage_snapshot.context_breakdown.to_dict()
        session.metadata["last_context_budget_breakdown"] = dict(session.usage_snapshot.context_budget_breakdown)
        session.metadata["last_turn_usage"] = session.usage_snapshot.last_turn_usage.to_dict()
        session.metadata["session_totals"] = session.usage_snapshot.session_totals.to_dict()
        session.metadata["usage_source"] = usage_source
        return session.usage_snapshot.to_dict()

    async def input_brain(
        self,
        session_id: str,
        input_info: dict,
        api_key: str,
        api_url: str,
        model: str,
        provider_name: str = "",
        tool_activity_callback=None,
        model_options: dict | None = None,
        phase_callback=None,
        cancel_event=None,
    ):
        if self._http_session is None:
            raise RuntimeError("Brain HTTP session not initialized. Call init_brain() first.")

        session = self.get_or_create_session(session_id)
        await self._refresh_session_context(session)
        requested_mode = self._get_requested_mode(input_info)
        route_history: list[dict[str, Any]] = []
        switch_count = 0
        round_index = 0
        session.metadata["route_history"] = route_history
        turn_input_index = len(session.chat_history)
        transient_turn = bool(dict(input_info.get("metadata") or {}).get("transient")) if isinstance(input_info, dict) else False
        auto_memory_message = await self._build_auto_memory_message(session_id, input_info)
        session.metadata["last_memory_scope"] = dict((auto_memory_message or {}).get("metadata", {}).get("memory_scope") or {})
        session.metadata["last_authorization_decisions"] = []
        session.metadata["last_object_operations"] = []
        session.metadata["last_failure"] = {}
        session.metadata["last_request_debug"] = {}
        memory_trigger_message = self._build_memory_trigger_message(input_info)
        await self._store_turn_episode(session_id, input_info, transient_turn=transient_turn)
        reply_control_state = self._reply_control_state(session)
        checkpoint = self._create_reply_checkpoint(
            session,
            turn_id=str(session.runtime_state.turn_id or ""),
            input_info=input_info,
            history_length=turn_input_index,
        )
        reply_control_state["active_turn"] = {
            "state": "active",
            "turn_id": str(session.runtime_state.turn_id or ""),
            "stream_id": str(session.runtime_state.stream_id or ""),
            "checkpoint_id": str(checkpoint.get("checkpoint_id") or ""),
            "started_at": utcnow_iso(),
            "input_info": deepcopy(dict(input_info or {})),
            "input_summary": self._sanitize_control_text(input_info.get("content")),
        }
        reply_control_state["pending_command"] = None
        self._sync_reply_control_runtime_state(session_id, session)
        session.chat_history.append(input_info)
        session.touch()
        route_context, route_origin = self._initialize_route_for_turn(input_info, session, requested_mode)
        self._store_route_context(session, route_context)
        self._append_route_history_entry(
            session,
            route_history,
            round_index=round_index,
            route_context=route_context,
            origin=route_origin,
            switch_count=switch_count,
            from_mode="",
            to_mode=route_context.get("current_mode", ""),
        )
        self._sync_runtime_route_state(session_id, session, route_context)

        turn_usage = UsageCounters()
        usage_source = "estimated"
        session.usage_snapshot.last_turn_usage = UsageCounters()
        context_limit_info = await self._resolve_context_limit_info(
            model=model,
            api_url=api_url,
            provider_name=provider_name,
        )
        if transient_turn:
            trim_result = {}
        else:
            try:
                trim_result = await self._context_manager.trim_history(
                    session.chat_history,
                    model,
                    self._http_session,
                    api_url,
                    api_key,
                    context_limit_override=int(context_limit_info.get("context_limit_tokens", 0) or 0),
                    session_id=session.session_id,
                    provider_name=provider_name,
                    preserve_message_count=self._base_message_count(),
                ) or {}
            except TypeError:
                trim_result = await self._context_manager.trim_history(
                    session.chat_history,
                    model,
                    self._http_session,
                    api_url,
                    api_key,
                ) or {}
        trimmed_summary = str(trim_result.get("conversation_summary") or "").strip()
        if trimmed_summary:
            session.metadata["conversation_summary"] = trimmed_summary
        compression_snapshot = dict(trim_result.get("compression") or {})
        if not compression_snapshot:
            compression_snapshot = {
                "triggered": False,
                "level": "none",
                "trimmed_messages": 0,
                "before_tokens": int(trim_result.get("current_tokens", 0) or 0),
                "after_tokens": int(trim_result.get("current_tokens", 0) or 0),
                "usable_tokens": 0,
                "summary_tokens": 0,
            }
        session.metadata["last_compression"] = compression_snapshot
        summary_usage = self._normalize_usage(trim_result.get("summary_usage"))
        if summary_usage:
            turn_usage.add(summary_usage)
            session.usage_snapshot.session_totals.add(summary_usage)

        adapter_options = self._build_adapter_options(model_options)
        turn_counted = False
        preflight_compaction_attempted = False
        provider_context_retry_attempted = False

        while True:
            policy_messages = self._build_mode_policy_messages(route_context, requested_mode=requested_mode) + [
                {"role": "system", "content": TOOL_JUDGMENT_POLICY_MESSAGE},
                {"role": "system", "content": MEMORY_POLICY_MESSAGE},
                self._build_time_context_message(),
            ]
            if memory_trigger_message:
                policy_messages.append(memory_trigger_message)
            policy_messages.append({"role": "system", "content": WEB_RESEARCH_POLICY_MESSAGE})
            proprioception_message = {
                "role": "system",
                "content": "当前用户电脑光标信息：" + json.dumps(
                    self._context_manager.proprioception_info,
                    ensure_ascii=False,
                ),
            }
            current_turn_messages = list(session.chat_history[turn_input_index:])
            context_plan = await self._build_context_plan(
                session=session,
                turn_input_index=turn_input_index,
                current_turn_messages=current_turn_messages,
                auto_memory_message=auto_memory_message,
                policy_messages=policy_messages,
                proprioception_message=proprioception_message,
                route_context=route_context,
                requested_mode=requested_mode,
                model=model,
                provider_name=provider_name,
                api_url=api_url,
                context_limit_info=context_limit_info,
            )
            messages = list(context_plan.get("messages") or [])
            context_breakdown = dict(context_plan.get("breakdown") or {})
            context_budget = self._model_context_budget_resolver.resolve(
                model=model,
                context_limit_info=context_limit_info,
                length_policy=dict(context_plan.get("length_policy") or {}),
                model_options=model_options,
            ).to_dict()
            request_tokens_estimated = int(
                getattr(self._context_manager, "estimate_tokens")(messages)
                if callable(getattr(self._context_manager, "estimate_tokens", None))
                else sum(self._estimate_message_tokens(message) for message in messages)
            )
            if (
                request_tokens_estimated > int(context_budget.get("input_budget", 0) or 0)
                and not transient_turn
                and not preflight_compaction_attempted
            ):
                preflight_compaction_attempted = True
                await self._attempt_compaction_for_budget(
                    session=session,
                    model=model,
                    api_url=api_url,
                    api_key=api_key,
                    provider_name=provider_name,
                    context_limit_info=context_limit_info,
                    reserve_ratio=0.62,
                    turn_usage=turn_usage,
                )
                continue
            session.metadata["last_context_plan"] = {
                "length_policy": dict(context_plan.get("length_policy") or {}),
                "layers": dict(context_plan.get("layers") or {}),
                "breakdown": dict(context_breakdown),
                "context_budget_breakdown": dict(context_budget),
            }

            tools = self._get_tools_for_route(route_context, requested_mode=requested_mode)
            request_debug = self._build_request_debug_snapshot(
                provider_name=provider_name,
                model=model,
                api_url=api_url,
                tools=tools,
                messages=messages,
                context_plan=context_plan,
                context_breakdown=context_breakdown,
                context_limit_info=context_limit_info,
                context_budget_breakdown=context_budget,
            )
            session.metadata["last_request_debug"] = request_debug
            assistant_content = ""
            reasoning_content = ""
            tool_calls = []
            provider_items = []
            call_usage = None
            provider_usage_seen = False
            answer_started = False

            if phase_callback:
                self.set_session_runtime_state(
                    session_id,
                    RuntimeStatus.THINKING.value,
                    detail="Calling model",
                    current_mode=route_context.get("current_mode", ""),
                    route_reason=route_context.get("route_reason", ""),
                    action_risk="read",
                    source_profile=route_context.get("source_profile", ""),
                )
                await phase_callback(RuntimeStatus.THINKING.value, "Calling model")

            try:
                async for event in self._adapter.stream_chat(
                    self._http_session,
                    api_url,
                    api_key,
                    model,
                    messages,
                    tools,
                    cancel_event=cancel_event,
                    **adapter_options,
                ):
                    if event.type == "text" and event.text:
                        assistant_content += event.text
                        if not answer_started and phase_callback:
                            await phase_callback(RuntimeStatus.ANSWERING.value, "Generating answer")
                            answer_started = True
                        yield BrainOutputEvent(type="answer_text", text=event.text)
                    elif event.type == "reasoning" and event.reasoning_text:
                        reasoning_content += event.reasoning_text
                        yield BrainOutputEvent(type="reasoning_text", text=event.reasoning_text)
                    elif event.type == "usage" and event.usage:
                        normalized_usage = self._normalize_usage(event.usage)
                        if normalized_usage:
                            call_usage = normalized_usage
                            provider_usage_seen = True
                    elif event.type == "provider_items" and event.provider_items:
                        provider_items = event.provider_items
                    elif event.type == "tool_calls" and event.tool_calls:
                        tool_calls = event.tool_calls
                    elif event.type == "error":
                        logger.error("Streaming adapter error: %s", event.error)
                        self._record_session_failure(
                            session,
                            {
                                "code": "streaming_adapter_error",
                                "category": "dependency",
                                "message": str(event.error or "Streaming adapter error"),
                                "retryable": False,
                                "details": {
                                    "provider_name": request_debug.get("provider_name"),
                                    "model": request_debug.get("model"),
                                    "transport_mode": request_debug.get("transport_mode"),
                                },
                            },
                        )
            except Exception as exc:
                failure_payload = self._build_failure_payload_from_exception(
                    exc,
                    request_debug=request_debug,
                    compression=compression_snapshot,
                )
                self._record_session_failure(session, failure_payload)
                if (
                    str(failure_payload.get("code") or "") == "provider_context_limit_exceeded"
                    and not provider_context_retry_attempted
                    and not transient_turn
                ):
                    provider_context_retry_attempted = True
                    await self._attempt_compaction_for_budget(
                        session=session,
                        model=model,
                        api_url=api_url,
                        api_key=api_key,
                        provider_name=provider_name,
                        context_limit_info=context_limit_info,
                        reserve_ratio=0.58,
                        turn_usage=turn_usage,
                    )
                    continue
                try:
                    setattr(exc, "runtime_error_payload", failure_payload)
                except Exception:
                    pass
                raise

            if reasoning_content:
                yield BrainOutputEvent(type="reasoning_end")

            if assistant_content and not tool_calls:
                assistant_message = {"role": "assistant", "content": assistant_content}
                if transient_turn:
                    assistant_message["metadata"] = {"transient": True}
                session.chat_history.append(assistant_message)

            if call_usage is None:
                call_usage = self._estimate_call_usage(
                    context_breakdown=context_breakdown,
                    assistant_content=assistant_content,
                    reasoning_text=reasoning_content,
                    tool_calls=tool_calls,
                    provider_items=provider_items,
                )
            elif provider_usage_seen:
                usage_source = "provider"

            turn_usage.add(call_usage)
            session.usage_snapshot.session_totals.add(call_usage)

            if not tool_calls and not turn_counted:
                session.usage_snapshot.session_totals.turn_count += 1
                turn_counted = True

            usage_payload = self._update_usage_snapshot(
                session,
                model=model,
                context_breakdown=context_breakdown,
                context_budget_breakdown=context_budget,
                turn_usage=turn_usage,
                usage_source=usage_source,
                context_limit_info=context_limit_info,
            )
            yield BrainOutputEvent(type="usage", usage=usage_payload)

            if not tool_calls:
                session.metadata["last_failure"] = {}
                latest_replay_input = {
                    "turn_id": str((reply_control_state.get("active_turn") or {}).get("turn_id") or session.runtime_state.turn_id or ""),
                    "checkpoint_id": str((reply_control_state.get("active_turn") or {}).get("checkpoint_id") or ""),
                    "created_at": utcnow_iso(),
                    "input_info": deepcopy(dict(input_info or {})),
                    "input_summary": self._sanitize_control_text(input_info.get("content")),
                }
                reply_control_state["latest_replay_input"] = latest_replay_input
                reply_control_state["active_turn"] = None
                reply_control_state["pending_command"] = None
                reply_control_state["last_finish_reason"] = "completed"
                self._sync_reply_control_runtime_state(session_id, session)
                if transient_turn and len(session.chat_history) > turn_input_index:
                    del session.chat_history[turn_input_index:]
                elif not transient_turn:
                    await self._persist_session_context(session)
                break

            tool_call_assistant_message = {
                "role": "assistant",
                "content": assistant_content or None,
                **({"metadata": {"transient": True}} if transient_turn else {}),
                "tool_calls": [
                    {
                        "type": "function",
                        "id": tc.id,
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments_str,
                        },
                    }
                    for tc in tool_calls
                ],
                "provider_items": provider_items,
            }
            if reasoning_content:
                tool_call_assistant_message["reasoning_content"] = reasoning_content
            session.chat_history.append(tool_call_assistant_message)

            mode_switch_calls = [tc for tc in tool_calls if tc.name == _INTERNAL_MODE_SWITCH_TOOL_NAME]
            visible_tool_calls = [tc for tc in tool_calls if tc.name != _INTERNAL_MODE_SWITCH_TOOL_NAME]
            visible_tool_names = [tc.name for tc in visible_tool_calls]

            if mode_switch_calls:
                max_switches_per_round = self._get_router_limit("max_switches_per_round")
                executable_switch_calls = (
                    mode_switch_calls[:max_switches_per_round]
                    if max_switches_per_round is not None
                    else mode_switch_calls
                )
                ignored_switch_calls = mode_switch_calls[len(executable_switch_calls):]
                for switch_call in executable_switch_calls:
                    try:
                        switch_args = switch_call.arguments
                    except Exception:
                        switch_args = {}
                    switch_result = self._execute_mode_switch_tool(
                        tool_args=switch_args,
                        input_info=input_info,
                        session=session,
                        route_context=route_context,
                        requested_mode=requested_mode,
                        switch_count=switch_count,
                    )
                    route_context = dict(switch_result.route_context)
                    if switch_result.applied:
                        switch_count = switch_result.switch_count
                        self._store_route_context(session, route_context)
                        self._append_route_history_entry(
                            session,
                            route_history,
                            round_index=round_index + 1,
                            route_context=route_context,
                            origin=switch_result.origin,
                            switch_count=switch_count,
                            from_mode=switch_result.from_mode,
                            to_mode=switch_result.to_mode,
                        )
                        self._sync_runtime_route_state(session_id, session, route_context)
                    else:
                        self._append_route_history_entry(
                            session,
                            route_history,
                            round_index=round_index + 1,
                            route_context=route_context,
                            origin=switch_result.origin,
                            switch_count=switch_count,
                            from_mode=switch_result.from_mode,
                            to_mode=switch_result.to_mode,
                            reason=switch_result.message,
                        )
                    session.chat_history.append(
                        {
                            "role": "tool",
                            "content": switch_result.message,
                            "tool_call_id": switch_call.id,
                        }
                    )
                for extra_switch in ignored_switch_calls:
                    session.chat_history.append(
                        {
                            "role": "tool",
                            "content": (
                                f"Ignored: max_switches_per_round={max_switches_per_round} reached."
                                if max_switches_per_round is not None
                                else "Ignored: switch_assistant_mode call was not executed."
                            ),
                            "tool_call_id": extra_switch.id,
                        }
                    )
            if visible_tool_calls:
                max_tool_calls_per_round = self._get_router_limit("max_tool_calls_per_round")
                executable_visible_tool_calls = (
                    visible_tool_calls[:max_tool_calls_per_round]
                    if max_tool_calls_per_round is not None
                    else visible_tool_calls
                )
                ignored_visible_tool_calls = visible_tool_calls[len(executable_visible_tool_calls):]
                executed_tool_names = [tc.name for tc in executable_visible_tool_calls]
                if phase_callback:
                    self.set_session_runtime_state(
                        session_id,
                        RuntimeStatus.TOOL_CALLING.value,
                        detail=", ".join(executed_tool_names),
                        active_tools=executed_tool_names,
                        current_mode=route_context.get("current_mode", ""),
                        route_reason=route_context.get("route_reason", ""),
                        action_risk=self._get_action_risk_for_tools(executed_tool_names),
                        source_profile=route_context.get("source_profile", ""),
                    )
                    await phase_callback(
                        RuntimeStatus.TOOL_CALLING.value,
                        ", ".join(executed_tool_names),
                        active_tools=executed_tool_names,
                    )
                if executable_visible_tool_calls:
                    await self._execute_visible_tool_calls(
                        visible_tool_calls=executable_visible_tool_calls,
                        session=session,
                        session_id=session_id,
                        route_context=route_context,
                        tool_activity_callback=tool_activity_callback,
                    )
                for ignored_tool_call in ignored_visible_tool_calls:
                    session.chat_history.append(
                        {
                            "role": "tool",
                            "content": f"Ignored: max_tool_calls_per_round={max_tool_calls_per_round} reached.",
                            "tool_call_id": ignored_tool_call.id,
                        }
                    )
                self._store_route_context(session, route_context)
                self._sync_runtime_route_state(session_id, session, route_context)

            if tool_activity_callback and any(
                tc.name in {
                    "research_topic",
                    "inspect_page",
                    "search_knowledge",
                    "manage_tasks",
                    "search_web",
                    "read_web_page",
                }
                for tc in visible_tool_calls
            ):
                await tool_activity_callback(
                    "synthesizing",
                    "Synthesizing final answer",
                    {"tool_names": visible_tool_names},
                )
            round_index += 1

        if transient_turn and len(session.chat_history) > turn_input_index:
            del session.chat_history[turn_input_index:]
        yield BrainOutputEvent(type="done")
