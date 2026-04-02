"""
Main conversational orchestration.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import aiohttp

from core.brain_session import BrainSession
from core.runtime_context import get_event_context
from core.status import ContextBreakdown, RuntimeStatus, UsageCounters, utcnow_iso

logger = logging.getLogger("meetyou.brain")

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


class Brain:
    def __init__(self, adapter, tools_manager, context_manager, event_bus, exception_router):
        self._adapter = adapter
        self._tools_manager = tools_manager
        self._context_manager = context_manager
        self._event_bus = event_bus
        self._exception_router = exception_router
        self._base_messages: list[dict] = []
        self._sessions: dict[str, BrainSession] = {}
        self._http_session: aiohttp.ClientSession | None = None

    async def init_brain(self, sys_prompt: str):
        self._base_messages = [{"role": "system", "content": sys_prompt}]
        context = await self._context_manager.load_context()
        self._base_messages.append({"role": "system", "content": context})
        self._http_session = aiohttp.ClientSession()
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

    async def close_session(self, session_id: str):
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await self._save_session_context(session)

    async def _save_session_context(self, session: BrainSession):
        await self._persist_session_context(session)

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
        stream_id: str | None = None,
        turn_id: str | None = None,
    ) -> dict:
        session = self.get_or_create_session(session_id)
        return session.runtime_state.update(
            status=status,
            detail=detail,
            active_tools=active_tools,
            stream_id=stream_id,
            turn_id=turn_id,
        ).to_dict()

    def _build_recent_context_summary(self, session: BrainSession) -> str:
        if len(session.chat_history) <= 2:
            return ""
        recent = session.chat_history[2:]
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
    ) -> dict:
        session.usage_snapshot.context_limit_tokens = self._get_context_limit(model)
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
        tool_activity_callback=None,
        model_options: dict | None = None,
        phase_callback=None,
    ):
        if self._http_session is None:
            raise RuntimeError("Brain HTTP session not initialized. Call init_brain() first.")

        session = self.get_or_create_session(session_id)
        await self._refresh_session_context(session)
        turn_input_index = len(session.chat_history)
        auto_memory_message = await self._build_auto_memory_message(session_id, input_info)
        memory_trigger_message = self._build_memory_trigger_message(input_info)
        session.chat_history.append(input_info)
        session.touch()

        turn_usage = UsageCounters()
        usage_source = "estimated"
        session.usage_snapshot.last_turn_usage = UsageCounters()

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

        policy_messages = [
            {"role": "system", "content": TOOL_JUDGMENT_POLICY_MESSAGE},
            {"role": "system", "content": MEMORY_POLICY_MESSAGE},
        ]
        if memory_trigger_message:
            policy_messages.append(memory_trigger_message)
        policy_messages.append({"role": "system", "content": WEB_RESEARCH_POLICY_MESSAGE})

        adapter_options = self._build_adapter_options(model_options)
        turn_counted = False

        while True:
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

            tools = self._tools_manager.get_all_tools()
            assistant_content = ""
            reasoning_content = ""
            tool_calls = []
            provider_items = []
            call_usage = None
            provider_usage_seen = False
            answer_started = False

            if phase_callback:
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
                session.chat_history.append({"role": "assistant", "content": assistant_content})

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
            )
            yield BrainOutputEvent(type="usage", usage=usage_payload)

            if not tool_calls:
                await self._persist_session_context(session)
                break

            session.chat_history.append(
                {
                    "role": "assistant",
                    "content": None,
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

            tool_names = [tc.name for tc in tool_calls]
            if phase_callback:
                await phase_callback(
                    RuntimeStatus.TOOL_CALLING.value,
                    ", ".join(tool_names),
                    active_tools=tool_names,
                )

            for tc in tool_calls:
                try:
                    args = tc.arguments
                except Exception:
                    args = {}

                try:
                    context = get_event_context()
                    result = await self._tools_manager.call_tool(
                        tc.name,
                        args,
                        session_id=context.get("session_id", session_id),
                        source=context.get("source"),
                        tool_activity_callback=tool_activity_callback,
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

            if tool_activity_callback and any(
                tc.name in {
                    "research_topic",
                    "inspect_page",
                    "search_knowledge",
                    "manage_tasks",
                    "search_web",
                    "read_web_page",
                }
                for tc in tool_calls
            ):
                await tool_activity_callback(
                    "synthesizing",
                    "Synthesizing final answer",
                    {"tool_names": tool_names},
                )

        yield BrainOutputEvent(type="done")
