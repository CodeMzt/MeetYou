"""
Main conversational orchestration.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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
from core.runtime_context import get_event_context
from core.status import ContextBreakdown, RuntimeStatus, UsageCounters, utcnow_iso

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


@dataclass
class _ModeSwitchResult:
    message: str
    route_context: dict[str, Any]
    switch_count: int
    origin: str
    from_mode: str
    to_mode: str
    applied: bool = False


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

    async def init_brain(self, sys_prompt: str):
        self._base_messages = [{"role": "system", "content": sys_prompt}]
        context = await self._context_manager.load_context()
        self._base_messages.append({"role": "system", "content": context})
        self._http_session = aiohttp.ClientSession() if aiohttp is not None else _FallbackClientSession()
        logger.info("Brain initialized")

    async def _refresh_session_context(self, session: BrainSession):
        context = await self._context_manager.load_context(session.session_id)
        context_message = {"role": "system", "content": context}
        if len(session.chat_history) >= 2:
            session.chat_history[1] = context_message
        else:
            session.chat_history.append(context_message)

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
        self._base_messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "system", "content": persisted_context},
        ]
        for session in self._sessions.values():
            preserved = [message for message in session.chat_history[2:]]
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

    def discard_trailing_transient_messages(self, session_id: str):
        session = self._sessions.get(session_id)
        if session is None:
            return
        while len(session.chat_history) > 2:
            metadata = dict(session.chat_history[-1].get("metadata") or {})
            if not bool(metadata.get("transient")):
                break
            session.chat_history.pop()

    async def close_session(self, session_id: str):
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await self._save_session_context(session)

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
        ).to_dict()

    @staticmethod
    def _normalize_mode_name(value: Any, fallback: str = ASSISTANT_MODE_AUTO) -> str:
        normalized = str(value or "").strip().lower()
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

    def _apply_route_metadata_overrides(self, route_context: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        route_dict = dict(route_context or {})
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
                    "Switch to another assistant mode for the next round when the next immediate step fits "
                    "another mode better. Call this by itself, wait for the tool result, then continue with "
                    "tools from the new mode."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": list(ASSISTANT_MODES),
                            "description": "The target assistant mode to activate next.",
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
                "Call switch_assistant_mode by itself. After the tool result confirms the switch, continue in the next round.",
            ]
        else:
            lines = [
                "[Mode Switching]",
                "If the next immediate step belongs to another mode, call switch_assistant_mode before using tools from that mode.",
                "Call switch_assistant_mode by itself. After the tool result confirms the switch, continue in the next round.",
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
                message=f"Error: mode is locked for this turn; staying in {current_mode}.",
                route_context=dict(route_context),
                switch_count=switch_count,
                origin="switch_tool_locked",
                from_mode=current_mode,
                to_mode=current_mode,
            )

        if not bool(router_config.get("allow_in_turn_switch", True)):
            return _ModeSwitchResult(
                message=f"Error: in-turn mode switching is disabled; staying in {current_mode}.",
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
                message=f'Error: invalid assistant mode "{raw_mode}".',
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

        max_switches = int(router_config.get("max_switches_per_turn", 2) or 0)
        if switch_count >= max_switches:
            return _ModeSwitchResult(
                message=f"Error: max_switches_per_turn={max_switches} reached; staying in {current_mode}.",
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
    ) -> str:
        if bool(route_context.get("disable_tools")):
            return f"Error: tool not allowed in the current route: {tool_name}"
        caller = getattr(self._tools_manager, "call_tool")
        try:
            return await caller(
                tool_name,
                tool_args,
                session_id=session_id,
                source=source,
                tool_activity_callback=tool_activity_callback,
                route_context=route_context,
            )
        except TypeError:
            return await caller(
                tool_name,
                tool_args,
                session_id=session_id,
                source=source,
                tool_activity_callback=tool_activity_callback,
            )

    def _get_action_risk_for_tools(self, tool_names: list[str]) -> str:
        getter = getattr(self._tools_manager, "get_action_risk_for_tools", None)
        if callable(getter):
            return str(getter(tool_names))
        return "read"

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
                        tool_result = f"Error: tool {tool_call.name} failed: {exc}"

                    history.append(
                        {
                            "role": "tool",
                            "content": tool_result if isinstance(tool_result, str) else str(tool_result),
                            "tool_call_id": tool_call.id,
                        }
                    )

            return {
                "status": "error",
                "content": "Error: background task exceeded max tool rounds.",
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
        if len(session.chat_history) <= 2:
            return ""
        recent = [
            message
            for message in session.chat_history[2:]
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
            payload = json.loads(result)
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
        memory_trigger_message = self._build_memory_trigger_message(input_info)
        await self._store_turn_episode(session_id, input_info, transient_turn=transient_turn)
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
                ) or {}
            except TypeError:
                trim_result = await self._context_manager.trim_history(
                    session.chat_history,
                    model,
                    self._http_session,
                    api_url,
                    api_key,
                ) or {}
        summary_usage = self._normalize_usage(trim_result.get("summary_usage"))
        if summary_usage:
            turn_usage.add(summary_usage)
            session.usage_snapshot.session_totals.add(summary_usage)
            usage_source = "provider"

        adapter_options = self._build_adapter_options(model_options)
        turn_counted = False

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
            messages = (
                session.chat_history[:turn_input_index]
                + ([auto_memory_message] if auto_memory_message else [])
                + policy_messages
                + current_turn_messages
                + [proprioception_message]
            )
            context_breakdown = self._build_context_breakdown(
                session_history_before_turn=session.chat_history[:turn_input_index],
                current_turn_messages=current_turn_messages,
                auto_memory_message=auto_memory_message,
                policy_messages=policy_messages,
                proprioception_message=proprioception_message,
            )

            tools = self._get_tools_for_route(route_context, requested_mode=requested_mode)
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

            async for event in self._adapter.stream_chat(
                self._http_session,
                api_url,
                api_key,
                model,
                messages,
                tools,
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

            if assistant_content:
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
                turn_usage=turn_usage,
                usage_source=usage_source,
                context_limit_info=context_limit_info,
            )
            yield BrainOutputEvent(type="usage", usage=usage_payload)

            if not tool_calls:
                if transient_turn and len(session.chat_history) > turn_input_index:
                    del session.chat_history[turn_input_index:]
                elif not transient_turn:
                    await self._persist_session_context(session)
                break

            session.chat_history.append(
                {
                    "role": "assistant",
                    "content": None,
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
            )

            mode_switch_calls = [tc for tc in tool_calls if tc.name == _INTERNAL_MODE_SWITCH_TOOL_NAME]
            visible_tool_calls = [tc for tc in tool_calls if tc.name != _INTERNAL_MODE_SWITCH_TOOL_NAME]
            visible_tool_names = [tc.name for tc in visible_tool_calls]
            if visible_tool_calls and not mode_switch_calls and phase_callback:
                self.set_session_runtime_state(
                    session_id,
                    RuntimeStatus.TOOL_CALLING.value,
                    detail=", ".join(visible_tool_names),
                    active_tools=visible_tool_names,
                    current_mode=route_context.get("current_mode", ""),
                    route_reason=route_context.get("route_reason", ""),
                    action_risk=self._get_action_risk_for_tools(visible_tool_names),
                    source_profile=route_context.get("source_profile", ""),
                )
                await phase_callback(
                    RuntimeStatus.TOOL_CALLING.value,
                    ", ".join(visible_tool_names),
                    active_tools=visible_tool_names,
                )

            if mode_switch_calls:
                primary_switch = mode_switch_calls[0]
                try:
                    switch_args = primary_switch.arguments
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
                        "tool_call_id": primary_switch.id,
                    }
                )
                for extra_switch in mode_switch_calls[1:]:
                    session.chat_history.append(
                        {
                            "role": "tool",
                            "content": "Ignored: switch_assistant_mode can only be called once per round.",
                            "tool_call_id": extra_switch.id,
                        }
                    )
                for skipped_tool in visible_tool_calls:
                    session.chat_history.append(
                        {
                            "role": "tool",
                            "content": (
                                "Skipped: switch_assistant_mode must be handled in its own round. "
                                "Call this tool again after the mode switch."
                            ),
                            "tool_call_id": skipped_tool.id,
                        }
                    )
            else:
                for tc in visible_tool_calls:
                    try:
                        args = tc.arguments
                    except Exception:
                        args = {}

                    try:
                        context = get_event_context()
                        result = await self._call_tool_with_route(
                            tc.name,
                            args,
                            session_id=context.get("session_id", session_id),
                            source=context.get("source"),
                            tool_activity_callback=tool_activity_callback,
                            route_context=route_context,
                        )
                    except Exception as exc:
                        result = f"Error: tool {tc.name} failed: {exc}"

                    session.chat_history.append(
                        {
                            "role": "tool",
                            "content": result if isinstance(result, str) else str(result),
                            "tool_call_id": tc.id,
                        }
                    )
                self._store_route_context(session, route_context)
                self._sync_runtime_route_state(session_id, session, route_context)

            if tool_activity_callback and not mode_switch_calls and any(
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
