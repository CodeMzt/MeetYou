"""
Semantic routing utilities for modes, reusable skills, and context preload decisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from math import sqrt
from typing import Any, Protocol

from core.source_catalog import normalize_source_profile_name

ASSISTANT_MODE_GENERAL = "general"
ASSISTANT_MODE_AUTOMATION = "automation"
ASSISTANT_MODE_RESEARCH = "research"
ASSISTANT_MODES = (
    ASSISTANT_MODE_GENERAL,
    ASSISTANT_MODE_AUTOMATION,
    ASSISTANT_MODE_RESEARCH,
)

_PUBLIC_MODE_ALIASES = {
    "general": ASSISTANT_MODE_GENERAL,
    "normal": ASSISTANT_MODE_GENERAL,
    "auto": ASSISTANT_MODE_GENERAL,
    "documents": ASSISTANT_MODE_GENERAL,
    "research": ASSISTANT_MODE_RESEARCH,
    "study": ASSISTANT_MODE_GENERAL,
    "automation": ASSISTANT_MODE_AUTOMATION,
    "office": ASSISTANT_MODE_AUTOMATION,
}

_BOOLEAN_FALLBACK_ORDER = (ASSISTANT_MODE_GENERAL, ASSISTANT_MODE_AUTOMATION)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_PATH_RE = re.compile(
    r"(?i)(?:[a-z]:[\\/][^\s]+|(?:\.{1,2}[\\/]|[\\/])?[^\s]+\.(?:md|txt|pdf|docx|xlsx|pptx|csv|json|py|ts|tsx|js|jsx|html))"
)
_WORD_RE = re.compile(r"[a-z0-9_]+")
_CJK_BLOCK_RE = re.compile(r"[\u4e00-\u9fff]+")

_DOCUMENT_INTENTS = (
    "analyze workspace",
    "directory tree",
    "repo structure",
    "project structure",
    "read file",
    "rewrite file",
    "edit document",
    "summarize folder",
    "workspace",
    "repository",
    "repo",
    "folder",
    "directory",
    "local file",
    "markdown",
    "pdf",
    "docx",
    "xlsx",
    "pptx",
    "csv",
    "json",
    "文件",
    "文档",
    "目录",
    "文件夹",
    "工作区",
    "项目结构",
    "代码仓",
    "分析目录",
    "本地文件",
    "路径",
    "改写文档",
    "写入文档",
)
_RESEARCH_INTENTS = (
    "research report",
    "with citations",
    "citation",
    "citations",
    "evidence",
    "evidence table",
    "official source",
    "verify with sources",
    "source verification",
    "track updates",
    "source updates",
    "monitor",
    "monitoring",
    "policy change",
    "deep research",
    "hot topic",
    "hotspot",
    "trending topic",
    "breaking event",
    "研究报告",
    "引用",
    "引文",
    "证据",
    "来源核验",
    "核验来源",
    "更新跟踪",
    "来源更新",
    "严格引用",
    "热点",
    "时政热点",
    "热搜",
    "事件追踪",
    "舆情",
)
_OFFICE_INTENTS = (
    "meeting",
    "agenda",
    "minutes",
    "schedule",
    "calendar",
    "invite",
    "attendee",
    "follow-up email",
    "draft email",
    "draft message",
    "sync notes",
    "meeting brief",
    "会议",
    "议程",
    "纪要",
    "日程",
    "日历",
    "邀请",
    "参会人",
    "邮件",
    "消息",
    "草稿",
    "同步笔记",
)
_COMMAND_INTENTS = (
    "command",
    "shell",
    "terminal",
    "powershell",
    "run command",
    "run a command",
    "execute command",
    "execute a command",
    "命令",
    "终端",
    "运行命令",
)
_STUDY_INTENTS = (
    "study plan",
    "learn",
    "learning",
    "course",
    "exam",
    "quiz me",
    "flashcard",
    "flashcards",
    "mastery",
    "review chapter",
    "syllabus",
    "lesson",
    "practice problems",
    "学习",
    "复习",
    "课程",
    "考试",
    "测验",
    "题目",
    "知识点",
    "闪卡",
    "掌握度",
    "练习",
    "讲义",
)
_LIGHT_WEB_INTENTS = (
    "what does this page say",
    "look up",
    "search online",
    "web search",
    "latest",
    "recent",
    "today",
    "news",
    "recommend",
    "compare",
    "review",
    "最新",
    "最近",
    "今天",
    "新闻",
    "推荐",
    "比较",
    "评测",
    "查一下",
    "搜一下",
    "上网查",
)
_TASK_MANAGEMENT_INTENTS = (
    "todo",
    "to-do",
    "task",
    "tasks",
    "reminder",
    "remind me",
    "deadline",
    "follow up",
    "follow-up",
    "blocker",
    "blocked",
    "complete",
    "completed",
    "next steps",
    "action items",
    "记一下",
    "待办",
    "任务",
    "提醒我",
    "提醒",
    "截止",
    "到期",
    "跟进",
    "阻塞",
    "卡住",
    "完成",
    "下一步",
)
_CONTEXT_INTENTS = (
    "what did we",
    "previous",
    "earlier",
    "remember",
    "project history",
    "notion",
    "spec",
    "last time",
    "之前",
    "上次",
    "以前",
    "记得",
    "聊过",
    "讨论过",
    "方案",
    "需求",
    "会议",
)
_SOURCE_PROFILE_INTENTS: dict[str, tuple[str, ...]] = {
    "academic_research": (
        "arxiv",
        "ieee",
        "paper",
        "preprint",
        "journal",
        "robotics",
        "electrical engineering",
        "论文",
        "预印本",
        "文献",
        "人工智能",
        "机器人",
    ),
    "code_engineering": (
        "github",
        "trending",
        "repo",
        "repository",
        "topic",
        "embedded",
        "freertos",
        "stm32",
        "esp32",
        "firmware",
        "开源",
        "仓库",
        "嵌入式",
        "固件",
        "开发板",
    ),
    "world_affairs": (
        "reuters",
        "associated press",
        "ap news",
        "xinhua",
        "geopolitics",
        "supply chain",
        "world affairs",
        "路透",
        "美联社",
        "新华网",
        "时政",
        "国际局势",
        "地缘政治",
    ),
    "frontier_tech": (
        "hugging face",
        "daily papers",
        "multimodal",
        "edge ai",
        "frontier tech",
        "technology review",
        "deployment",
        "多模态",
        "端侧",
        "前沿科技",
        "大模型",
        "部署",
    ),
    "academic_biomed": (
        "paper",
        "doi",
        "pubmed",
        "journal",
        "trial",
        "study",
        "论文",
        "文献",
        "医学",
        "研究",
    ),
    "policy_global": (
        "policy",
        "regulation",
        "government",
        "fda",
        "sec",
        "who",
        "law",
        "监管",
    ),
    "finance_macro": (
        "finance",
        "stock",
        "earnings",
        "macro",
        "inflation",
        "gdp",
        "财报",
        "股价",
        "宏观",
        "经济",
    ),
    "cyber_threat": (
        "cve",
        "kev",
        "vulnerability",
        "exploit",
        "漏洞",
        "安全",
        "威胁",
    ),
    "policy_cn": (
        "gov.cn",
        "政策",
        "法规",
        "统计",
        "国务院",
        "国家统计局",
    ),
}

_MODE_EXAMPLES: dict[str, tuple[tuple[str, str], ...]] = {
    ASSISTANT_MODE_GENERAL: (
        ("general_planning", "help me think through my plan for tomorrow and break it into a few simple options"),
        ("light_web_lookup", "look up the latest page, compare a couple options, and summarize what changed today"),
        ("everyday_help", "give me quick general help without turning this into a formal research report"),
        ("workspace_analysis", "analyze the repository structure, inspect the workspace, and explain the directory tree"),
        ("document_editing", "read a local markdown file, rewrite the document, and summarize the folder contents"),
        ("local_artifacts", "open a local path and generate a report from files in the project workspace"),
        ("learning_support", "quiz me on the course material, generate flashcards, and explain key learning points"),
        ("study_planning", "build a study plan, review a chapter, and track mastery for an upcoming exam"),
        ("practice_session", "teach me the lesson, create practice problems, and coach me through the material"),
    ),
    ASSISTANT_MODE_RESEARCH: (
        ("evidence_report", "create a research report with citations, evidence tables, and official sources"),
        ("update_monitoring", "track source updates, monitor policy changes, and verify information with sources"),
        ("deep_verification", "do deep research, cite the sources, and keep the answer evidence-heavy"),
        ("literature_review", "review academic papers, arxiv preprints, doi records, and synthesize a cited literature review"),
    ),
    ASSISTANT_MODE_AUTOMATION: (
        ("meeting_coordination", "draft a meeting agenda, schedule sync, attendee note, and follow-up email"),
        ("workplace_coordination", "prepare minutes, calendar invites, action items, and message drafts"),
        ("notes_sync", "sync notes from a meeting and turn them into coordination updates"),
        ("core_command", "run a whitelisted command in the Core terminal shell and return structured output"),
    ),
}

_SOURCE_PROFILE_EXAMPLES: dict[str, tuple[tuple[str, str], ...]] = {
    "academic_research": (
        ("arxiv_ieee", "summarize recent arxiv and IEEE papers on multimodal models, robotics, and electrical engineering"),
        ("research_digest", "追踪最新论文、预印本和学术研究进展，并给出引用"),
    ),
    "code_engineering": (
        ("github_embedded", "review GitHub topics, trending repos, firmware releases, and embedded engineering discussions"),
        ("hardware_projects", "关注 STM32、ESP32、FreeRTOS 和硬件实战项目的代码动态与社区讨论"),
    ),
    "world_affairs": (
        ("global_news", "compare Reuters, AP, and Xinhua coverage on geopolitics and supply chain developments"),
        ("world_briefing", "核验国际局势、宏观事件和全球新闻快讯"),
    ),
    "frontier_tech": (
        ("ai_frontier", "review Hugging Face daily papers and MIT Technology Review coverage on frontier AI"),
        ("deployment_watch", "追踪多模态、大模型架构和端侧部署的最新进展"),
    ),
    "academic_biomed": (
        ("paper_citations", "summarize the paper, cite the doi, compare journal evidence, and check pubmed trials"),
        ("biomedical_research", "review biomedical studies, clinical trials, and medical literature"),
    ),
    "policy_global": (
        ("regulatory_updates", "track policy changes, official regulation updates, and government guidance"),
        ("global_regulators", "verify the latest FDA, SEC, WHO, and legal requirements from official sources"),
        ("policy_briefing", "create a cited research report about policy changes, regulation updates, and government actions"),
    ),
    "finance_macro": (
        ("market_updates", "analyze macro conditions, inflation, gdp, earnings, and stock market signals"),
        ("investor_materials", "review finance reports, stock disclosures, and macroeconomic updates"),
    ),
    "cyber_threat": (
        ("vulnerability_tracking", "track cve updates, vulnerability details, exploits, and active threat reports"),
        ("security_advisory", "verify the latest security exploit notes and threat intelligence"),
    ),
    "policy_cn": (
        ("china_policy", "梳理政策法规、国务院通知、国家统计局数据和 gov.cn 官方口径"),
        ("china_regulation", "追踪中国监管政策更新并核验官方来源"),
    ),
    "tech_updates": (
        ("official_docs", "review official docs, release notes, standards updates, and vendor changelogs"),
        ("product_changes", "check the latest technical product updates from documentation and repositories"),
    ),
}

_SKILL_EXAMPLES: dict[str, tuple[tuple[str, str], ...]] = {
    "task_recognition": (
        ("task_management", "remember this task, set a reminder, capture next steps, and note the blocker"),
        ("follow_up_tracking", "create action items, track deadlines, and follow up later"),
    ),
    "research_grounding": (
        ("evidence_first", "use citations, evidence tables, official sources, and rigorous verification"),
        ("research_report", "write a research report and monitor source updates"),
    ),
    "study_coaching": (
        ("learning_coach", "quiz me, generate flashcards, explain concepts, and track mastery"),
        ("study_plan", "create a study plan and coach me through the lesson"),
    ),
    "knowledge_synthesis": (
        ("structured_summary", "summarize this material into a clean outline, organize the notes, and surface key takeaways"),
        ("note_rewrite", "整理这些笔记，提炼重点，并改写成结构化摘要"),
    ),
    "office_coordination": (
        ("meeting_actions", "turn these meeting notes into action items, owners, and a follow-up brief"),
        ("coordination_digest", "整理会议纪要、同步事项和后续消息草稿"),
    ),
    "hotspot_tracking": (
        ("trend_watch", "track hot topics, compare breaking developments, and produce a sourced summary"),
        ("news_digest", "追踪时政热点、交叉核验来源并输出摘要"),
    ),
}

_CONTEXT_EXAMPLES = (
    ("history_lookup", "what did we decide earlier and what happened in the previous discussion"),
    ("project_memory", "remember the project history, notion notes, and spec from last time"),
    ("prior_context", "复用之前聊过的方案、上次的需求和之前的会议结论"),
)

_LIVE_WEB_EXAMPLES = (
    ("fresh_updates", "search online for the latest update, recent news, and what changed today"),
    ("page_lookup", "look up this web page, inspect the site, and summarize the live content"),
    ("web_research", "上网查一下最新消息并比较几个在线来源"),
)


def _contains_any(text: str, items: tuple[str, ...]) -> list[str]:
    matched: list[str] = []
    for item in items:
        if item in text:
            matched.append(item)
    return matched


def _normalize_route_mode(value: Any, *, fallback: str = ASSISTANT_MODE_GENERAL) -> str:
    normalized = str(value or "").strip().lower()
    normalized = _PUBLIC_MODE_ALIASES.get(normalized, normalized)
    if normalized in ASSISTANT_MODES:
        return normalized
    fallback_normalized = _PUBLIC_MODE_ALIASES.get(str(fallback or "").strip().lower(), str(fallback or "").strip().lower())
    if fallback_normalized in ASSISTANT_MODES:
        return fallback_normalized
    return ASSISTANT_MODE_GENERAL


def _score(matches: list[str], *, weight: int = 2) -> int:
    return len(matches) * weight


def _unique_strings(items: list[str] | tuple[str, ...]) -> list[str]:
    return [item for item in dict.fromkeys(str(item).strip() for item in items if str(item).strip())]


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))


def _tokenize(text: str) -> set[str]:
    raw = str(text or "")
    lowered = raw.lower()
    tokens = set(_WORD_RE.findall(lowered))
    for block in _CJK_BLOCK_RE.findall(raw):
        block = block.strip()
        if not block:
            continue
        tokens.update(block)
        for size in (2, 3):
            if len(block) < size:
                continue
            for index in range(len(block) - size + 1):
                tokens.add(block[index : index + size])
    return {token for token in tokens if token}


def _semantic_similarity(query: str, sample: str) -> float:
    query_tokens = _tokenize(query)
    sample_tokens = _tokenize(sample)
    if not query_tokens or not sample_tokens:
        return 0.0
    overlap = len(query_tokens & sample_tokens) / sqrt(len(query_tokens) * len(sample_tokens))
    phrase = SequenceMatcher(None, str(query or "").lower(), str(sample or "").lower()).ratio()
    return min(1.0, 0.72 * overlap + 0.28 * phrase)


def _confidence_from_score(score: float, *, high: float = 0.78, medium: float = 0.46) -> str:
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    return "low"


def _has_local_path(text: str) -> bool:
    raw = str(text or "")
    url_spans = [match.span() for match in _URL_RE.finditer(raw)]
    for match in _PATH_RE.finditer(raw):
        if any(start <= match.start() < end for start, end in url_spans):
            continue
        return True
    return False


@dataclass(frozen=True)
class SemanticRouteRequest:
    content: str
    current_mode: str = ""
    source_kind: str = ""
    sticky_current_mode: bool = True


@dataclass(frozen=True)
class SemanticDecisionResult:
    value: str | bool
    confidence: str
    score: float
    reason: str
    signals: list[str]
    adapter_name: str


@dataclass
class SemanticRouteDecision:
    mode: str
    confidence: str
    reason: str
    source_profile: str
    active_skills: list[str]
    should_preload_context: bool
    prefer_live_web: bool
    signals: list[str]
    adapter_name: str = ""
    used_keyword_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "confidence": self.confidence,
            "reason": self.reason,
            "source_profile": self.source_profile,
            "active_skills": list(self.active_skills),
            "should_preload_context": self.should_preload_context,
            "prefer_live_web": self.prefer_live_web,
            "signals": list(self.signals),
            "adapter_name": self.adapter_name,
            "used_keyword_fallback": self.used_keyword_fallback,
        }


class SemanticDecisionAdapter(Protocol):
    adapter_name: str

    def analyze_route(self, request: SemanticRouteRequest) -> SemanticDecisionResult: ...

    def classify_source_profile(self, text: str) -> SemanticDecisionResult: ...

    def should_preload_context(self, query: str, goal: str = "") -> SemanticDecisionResult: ...

    def is_live_web_query(self, query: str) -> SemanticDecisionResult: ...

    def should_activate_skill(self, skill_name: str, content: str, *, mode: str = "") -> SemanticDecisionResult: ...


class ExampleSemanticAdapter:
    adapter_name = "semantic_example_adapter"

    def _best_example_match(self, text: str, examples: tuple[tuple[str, str], ...]) -> tuple[float, list[str]]:
        best_score = 0.0
        signals: list[str] = []
        for signal, sample in examples:
            score = _semantic_similarity(text, sample)
            if score <= 0:
                continue
            if score > best_score + 0.02:
                best_score = score
                signals = [signal]
            elif abs(score - best_score) <= 0.02 and signal not in signals:
                signals.append(signal)
        return best_score, signals[:3]

    def analyze_route(self, request: SemanticRouteRequest) -> SemanticDecisionResult:
        content = str(request.content or "").strip()
        current_mode = str(request.current_mode or "").strip().lower()
        source_kind = str(request.source_kind or "").strip().lower()
        scores = {mode: 0.0 for mode in ASSISTANT_MODES}
        reasons: dict[str, list[str]] = {mode: [] for mode in ASSISTANT_MODES}

        for mode, examples in _MODE_EXAMPLES.items():
            example_score, example_signals = self._best_example_match(content, examples)
            scores[mode] += example_score
            reasons[mode].extend(example_signals)

        if _has_local_path(content):
            scores[ASSISTANT_MODE_GENERAL] += 0.58
            reasons[ASSISTANT_MODE_GENERAL].append("local_path")
        if _URL_RE.search(content):
            scores[ASSISTANT_MODE_GENERAL] += 0.24
            reasons[ASSISTANT_MODE_GENERAL].append("direct_url")
        if source_kind in {"feishu", "email", "im"}:
            scores[ASSISTANT_MODE_AUTOMATION] += 0.28
            reasons[ASSISTANT_MODE_AUTOMATION].append(f"source:{source_kind}")
        command_matches = _contains_any(content.lower(), _COMMAND_INTENTS)
        if command_matches:
            scores[ASSISTANT_MODE_AUTOMATION] += min(0.72, 0.24 * len(command_matches))
            reasons[ASSISTANT_MODE_AUTOMATION].extend(command_matches[:4])
        if request.sticky_current_mode and current_mode in ASSISTANT_MODES:
            scores[current_mode] += 0.08
            reasons[current_mode].append("sticky_context")

        best_mode = max(scores.items(), key=lambda item: (item[1], item[0]))[0]
        best_score = scores[best_mode]
        confidence = _confidence_from_score(best_score)
        signals = _unique_strings(reasons[best_mode])[:4]
        if best_score < 0.22:
            fallback_mode = current_mode if current_mode in ASSISTANT_MODES else ASSISTANT_MODE_GENERAL
            reason = (
                f"Semantic adapter found no strong specialist route and reused {fallback_mode}."
                if current_mode in ASSISTANT_MODES
                else "Semantic adapter found no strong specialist route and defaulted to general."
            )
            return SemanticDecisionResult(
                value=fallback_mode,
                confidence="low",
                score=best_score,
                reason=reason,
                signals=signals,
                adapter_name=self.adapter_name,
            )
        signal_text = ", ".join(signals) or "semantic_match"
        return SemanticDecisionResult(
            value=best_mode,
            confidence=confidence,
            score=best_score,
            reason=f"Semantic adapter selected {best_mode}: {signal_text}",
            signals=signals,
            adapter_name=self.adapter_name,
        )

    def classify_source_profile(self, text: str) -> SemanticDecisionResult:
        content = str(text or "").strip()
        scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}
        for profile_name, examples in _SOURCE_PROFILE_EXAMPLES.items():
            score, signals = self._best_example_match(content, examples)
            scores[profile_name] = score
            reasons[profile_name] = signals
        best_profile = max(scores.items(), key=lambda item: (item[1], item[0]))[0]
        best_score = scores[best_profile]
        confidence = _confidence_from_score(best_score, high=0.72, medium=0.42)
        signals = _unique_strings(reasons.get(best_profile, []))[:3]
        if best_score < 0.20:
            default_profile = "policy_cn" if _contains_cjk(content) else "tech_updates"
            return SemanticDecisionResult(
                value=default_profile,
                confidence="low",
                score=best_score,
                reason=f"Semantic adapter found weak source-profile evidence and defaulted to {default_profile}.",
                signals=signals,
                adapter_name=self.adapter_name,
            )
        return SemanticDecisionResult(
            value=best_profile,
            confidence=confidence,
            score=best_score,
            reason=f"Semantic adapter selected source profile {best_profile}.",
            signals=signals,
            adapter_name=self.adapter_name,
        )

    def should_preload_context(self, query: str, goal: str = "") -> SemanticDecisionResult:
        content = f"{query}\n{goal}".strip()
        score, signals = self._best_example_match(content, _CONTEXT_EXAMPLES)
        value = score >= 0.40
        confidence = _confidence_from_score(score, high=0.72, medium=0.40)
        return SemanticDecisionResult(
            value=value,
            confidence=confidence,
            score=score,
            reason=f"Semantic adapter {'will' if value else 'will not'} preload prior context.",
            signals=signals,
            adapter_name=self.adapter_name,
        )

    def is_live_web_query(self, query: str) -> SemanticDecisionResult:
        content = str(query or "").strip()
        score, signals = self._best_example_match(content, _LIVE_WEB_EXAMPLES)
        if _URL_RE.search(content):
            score = min(1.0, score + 0.40)
            signals = _unique_strings([*signals, "direct_url"])
        value = score >= 0.42
        confidence = _confidence_from_score(score, high=0.74, medium=0.42)
        return SemanticDecisionResult(
            value=value,
            confidence=confidence,
            score=score,
            reason=f"Semantic adapter {'prefers' if value else 'does not prefer'} live web grounding.",
            signals=signals[:3],
            adapter_name=self.adapter_name,
        )

    def should_activate_skill(self, skill_name: str, content: str, *, mode: str = "") -> SemanticDecisionResult:
        normalized_name = str(skill_name or "").strip()
        normalized_mode = str(mode or "").strip().lower()
        raw_content = str(content or "").strip()
        if normalized_name == "office_coordination" and normalized_mode == ASSISTANT_MODE_AUTOMATION:
            return SemanticDecisionResult(
                value=True,
                confidence="high",
                score=1.0,
                reason="Semantic adapter activated office_coordination from automation mode.",
                signals=["mode:automation"],
                adapter_name=self.adapter_name,
            )
        examples = _SKILL_EXAMPLES.get(normalized_name, ())
        score, signals = self._best_example_match(raw_content, examples)
        value = score >= 0.42
        confidence = _confidence_from_score(score, high=0.74, medium=0.42)
        return SemanticDecisionResult(
            value=value,
            confidence=confidence,
            score=score,
            reason=f"Semantic adapter {'activated' if value else 'did not activate'} {normalized_name}.",
            signals=signals,
            adapter_name=self.adapter_name,
        )


class KeywordFallbackAdapter:
    adapter_name = "keyword_fallback_adapter"

    def analyze_route(self, request: SemanticRouteRequest) -> SemanticDecisionResult:
        content = str(request.content or "").strip()
        lowered = content.lower()
        source_kind = str(request.source_kind or "").strip().lower()
        current_mode = str(request.current_mode or "").strip().lower()
        scores = {mode: 0 for mode in ASSISTANT_MODES}
        reasons: dict[str, list[str]] = {mode: [] for mode in ASSISTANT_MODES}

        document_matches = _contains_any(lowered, _DOCUMENT_INTENTS)
        research_matches = _contains_any(lowered, _RESEARCH_INTENTS)
        office_matches = _contains_any(lowered, _OFFICE_INTENTS)
        command_matches = _contains_any(lowered, _COMMAND_INTENTS)
        study_matches = _contains_any(lowered, _STUDY_INTENTS)
        light_web_matches = _contains_any(lowered, _LIGHT_WEB_INTENTS)
        task_matches = _contains_any(lowered, _TASK_MANAGEMENT_INTENTS)

        if document_matches:
            scores[ASSISTANT_MODE_GENERAL] += _score(document_matches)
            reasons[ASSISTANT_MODE_GENERAL].extend(document_matches[:4])
        if research_matches:
            scores[ASSISTANT_MODE_RESEARCH] += _score(research_matches, weight=3)
            reasons[ASSISTANT_MODE_RESEARCH].extend(research_matches[:4])
        if office_matches:
            scores[ASSISTANT_MODE_AUTOMATION] += _score(office_matches)
            reasons[ASSISTANT_MODE_AUTOMATION].extend(office_matches[:4])
        if command_matches:
            scores[ASSISTANT_MODE_AUTOMATION] += _score(command_matches, weight=2)
            reasons[ASSISTANT_MODE_AUTOMATION].extend(command_matches[:4])
        if study_matches:
            scores[ASSISTANT_MODE_GENERAL] += _score(study_matches)
            reasons[ASSISTANT_MODE_GENERAL].extend(study_matches[:4])
        if light_web_matches:
            scores[ASSISTANT_MODE_GENERAL] += _score(light_web_matches)
            reasons[ASSISTANT_MODE_GENERAL].extend(light_web_matches[:4])
        if task_matches:
            for candidate in _BOOLEAN_FALLBACK_ORDER:
                scores[candidate] += 1

        if _has_local_path(content):
            scores[ASSISTANT_MODE_GENERAL] += 5
            reasons[ASSISTANT_MODE_GENERAL].append("local_path")
        if _URL_RE.search(content):
            scores[ASSISTANT_MODE_GENERAL] += 4
            reasons[ASSISTANT_MODE_GENERAL].append("direct_url")
        if source_kind in {"feishu", "email", "im"}:
            scores[ASSISTANT_MODE_AUTOMATION] += 2
            reasons[ASSISTANT_MODE_AUTOMATION].append(f"source:{source_kind}")
        if request.sticky_current_mode and current_mode in ASSISTANT_MODES:
            scores[current_mode] += 1
            reasons[current_mode].append("sticky_context")

        best_mode = max(scores.items(), key=lambda item: (item[1], item[0]))[0]
        best_score = scores[best_mode]
        confidence = "high" if best_score >= 6 else "medium" if best_score >= 3 else "low"
        if best_score <= 0:
            fallback_mode = current_mode if current_mode in ASSISTANT_MODES else ASSISTANT_MODE_GENERAL
            reason = (
                f"Keyword fallback found no strong routing signal and reused {fallback_mode}."
                if current_mode in ASSISTANT_MODES
                else "Keyword fallback found no strong routing signal and defaulted to general."
            )
            return SemanticDecisionResult(
                value=fallback_mode,
                confidence="low",
                score=0.0,
                reason=reason,
                signals=[],
                adapter_name=self.adapter_name,
            )
        signals = _unique_strings(reasons[best_mode])[:4]
        return SemanticDecisionResult(
            value=best_mode,
            confidence=confidence,
            score=float(best_score),
            reason=f"Keyword fallback selected {best_mode}: {', '.join(signals) or 'keyword_match'}",
            signals=signals,
            adapter_name=self.adapter_name,
        )

    def classify_source_profile(self, text: str) -> SemanticDecisionResult:
        lowered = str(text or "").lower()
        for profile_name, intents in _SOURCE_PROFILE_INTENTS.items():
            matches = _contains_any(lowered, intents)
            if matches:
                return SemanticDecisionResult(
                    value=profile_name,
                    confidence="high",
                    score=float(len(matches)),
                    reason=f"Keyword fallback selected source profile {profile_name}.",
                    signals=matches[:3],
                    adapter_name=self.adapter_name,
                )
        default_profile = "policy_cn" if _contains_cjk(text) else "tech_updates"
        return SemanticDecisionResult(
            value=default_profile,
            confidence="low",
            score=0.0,
            reason=f"Keyword fallback defaulted source profile to {default_profile}.",
            signals=[],
            adapter_name=self.adapter_name,
        )

    def should_preload_context(self, query: str, goal: str = "") -> SemanticDecisionResult:
        lowered = f"{query}\n{goal}".lower()
        matches = _contains_any(lowered, _CONTEXT_INTENTS)
        return SemanticDecisionResult(
            value=bool(matches),
            confidence="high" if matches else "low",
            score=float(len(matches)),
            reason=f"Keyword fallback {'will' if matches else 'will not'} preload prior context.",
            signals=matches[:3],
            adapter_name=self.adapter_name,
        )

    def is_live_web_query(self, query: str) -> SemanticDecisionResult:
        lowered = str(query or "").lower()
        matches = _contains_any(lowered, _LIGHT_WEB_INTENTS)
        signals = list(matches[:3])
        if _URL_RE.search(lowered):
            signals.append("direct_url")
        value = bool(_URL_RE.search(lowered) or matches)
        return SemanticDecisionResult(
            value=value,
            confidence="high" if value else "low",
            score=float(len(signals)),
            reason=f"Keyword fallback {'prefers' if value else 'does not prefer'} live web grounding.",
            signals=_unique_strings(signals)[:3],
            adapter_name=self.adapter_name,
        )

    def should_activate_skill(self, skill_name: str, content: str, *, mode: str = "") -> SemanticDecisionResult:
        lowered = str(content or "").lower()
        normalized_name = str(skill_name or "").strip()
        normalized_mode = str(mode or "").strip().lower()
        matches: list[str] = []
        value = False
        if normalized_name == "task_recognition":
            matches = _contains_any(lowered, _TASK_MANAGEMENT_INTENTS)
            value = bool(matches)
        elif normalized_name == "research_grounding":
            matches = _contains_any(lowered, _RESEARCH_INTENTS)
            value = bool(matches)
        elif normalized_name == "study_coaching":
            matches = _contains_any(lowered, _STUDY_INTENTS)
            value = bool(matches)
        elif normalized_name == "knowledge_synthesis":
            matches = _contains_any(
                lowered,
                (
                    "summarize",
                    "summary",
                    "outline",
                    "organize notes",
                    "action items",
                    "takeaways",
                    "整理",
                    "提炼",
                    "归纳",
                    "摘要",
                    "结构化",
                    "纪要",
                ),
            )
            value = bool(matches)
        elif normalized_name == "office_coordination":
            matches = _contains_any(lowered, (*_OFFICE_INTENTS, "action items", "owner", "follow-up"))
            value = normalized_mode == ASSISTANT_MODE_AUTOMATION or bool(matches)
            if normalized_mode == ASSISTANT_MODE_AUTOMATION:
                matches = ["mode:automation", *matches]
        elif normalized_name == "hotspot_tracking":
            matches = _contains_any(
                lowered,
                (
                    "hotspot",
                    "hot topic",
                    "trending",
                    "breaking",
                    "news",
                    "热点",
                    "时政热点",
                    "热搜",
                    "事件追踪",
                    "舆情",
                ),
            )
            value = bool(matches)
        return SemanticDecisionResult(
            value=value,
            confidence="high" if value else "low",
            score=float(len(matches)),
            reason=f"Keyword fallback {'activated' if value else 'did not activate'} {normalized_name}.",
            signals=_unique_strings(matches)[:3],
            adapter_name=self.adapter_name,
        )


class SemanticRouterAgent:
    def __init__(
        self,
        route_adapters: list[SemanticDecisionAdapter] | None = None,
        fallback_adapter: SemanticDecisionAdapter | None = None,
    ):
        self._route_adapters = list(route_adapters or [ExampleSemanticAdapter()])
        self._fallback_adapter = fallback_adapter or KeywordFallbackAdapter()

    def _route_request(
        self,
        content: str,
        *,
        current_mode: str = "",
        source_kind: str = "",
        sticky_current_mode: bool = True,
    ) -> SemanticRouteRequest:
        return SemanticRouteRequest(
            content=str(content or "").strip(),
            current_mode=_normalize_route_mode(current_mode, fallback=""),
            source_kind=str(source_kind or "").strip().lower(),
            sticky_current_mode=bool(sticky_current_mode),
        )

    def _choose_primary_route(self, request: SemanticRouteRequest) -> SemanticDecisionResult:
        best_decision: SemanticDecisionResult | None = None
        for adapter in self._route_adapters:
            decision = adapter.analyze_route(request)
            if best_decision is None or decision.score > best_decision.score:
                best_decision = decision
            if decision.confidence in {"high", "medium"}:
                return decision
        if best_decision is not None:
            return best_decision
        return SemanticDecisionResult(
            value=request.current_mode if request.current_mode in ASSISTANT_MODES else ASSISTANT_MODE_GENERAL,
            confidence="low",
            score=0.0,
            reason="Semantic router has no configured adapter and defaulted to general.",
            signals=[],
            adapter_name="unconfigured_semantic_router",
        )

    def _choose_signal(
        self,
        primary_getter,
        fallback_getter,
        *,
        enable_keyword_fallback: bool,
    ) -> SemanticDecisionResult:
        primary = primary_getter()
        if enable_keyword_fallback and primary.confidence == "low":
            fallback = fallback_getter()
            if fallback.confidence != "low" or fallback.value != primary.value:
                return fallback
        return primary

    def classify_source_profile(self, text: str, *, enable_keyword_fallback: bool = True) -> str:
        decision = self._choose_signal(
            lambda: self._route_adapters[0].classify_source_profile(text),
            lambda: self._fallback_adapter.classify_source_profile(text),
            enable_keyword_fallback=enable_keyword_fallback,
        )
        return normalize_source_profile_name(str(decision.value or "tech_updates"), fallback="tech_updates")

    def should_preload_context(self, query: str, goal: str = "", *, enable_keyword_fallback: bool = True) -> bool:
        decision = self._choose_signal(
            lambda: self._route_adapters[0].should_preload_context(query, goal),
            lambda: self._fallback_adapter.should_preload_context(query, goal),
            enable_keyword_fallback=enable_keyword_fallback,
        )
        return bool(decision.value)

    def is_live_web_query(self, query: str, *, enable_keyword_fallback: bool = True) -> bool:
        decision = self._choose_signal(
            lambda: self._route_adapters[0].is_live_web_query(query),
            lambda: self._fallback_adapter.is_live_web_query(query),
            enable_keyword_fallback=enable_keyword_fallback,
        )
        return bool(decision.value)

    def should_activate_skill(
        self,
        skill_name: str,
        content: str,
        *,
        mode: str = "",
        enable_keyword_fallback: bool = True,
    ) -> bool:
        decision = self.evaluate_skill_activation(
            skill_name,
            content,
            mode=mode,
            enable_keyword_fallback=enable_keyword_fallback,
        )
        return bool(decision.value)

    def evaluate_skill_activation(
        self,
        skill_name: str,
        content: str,
        *,
        mode: str = "",
        enable_keyword_fallback: bool = True,
    ) -> SemanticDecisionResult:
        decision = self._choose_signal(
            lambda: self._route_adapters[0].should_activate_skill(skill_name, content, mode=mode),
            lambda: self._fallback_adapter.should_activate_skill(skill_name, content, mode=mode),
            enable_keyword_fallback=enable_keyword_fallback,
        )
        return decision

    def analyze(
        self,
        content: str,
        *,
        current_mode: str = "",
        source_kind: str = "",
        sticky_current_mode: bool = True,
        enable_keyword_fallback: bool = True,
    ) -> SemanticRouteDecision:
        request = self._route_request(
            content,
            current_mode=current_mode,
            source_kind=source_kind,
            sticky_current_mode=sticky_current_mode,
        )
        primary = self._choose_primary_route(request)
        selected = primary
        reason = primary.reason
        used_keyword_fallback = False
        if enable_keyword_fallback and primary.confidence == "low":
            fallback = self._fallback_adapter.analyze_route(request)
            if fallback.confidence != "low" or fallback.value != primary.value:
                selected = fallback
                used_keyword_fallback = True
                reason = f"{primary.reason} {fallback.reason}".strip()
        raw_mode = str(selected.value or ASSISTANT_MODE_GENERAL).strip().lower()
        best_mode = _normalize_route_mode(raw_mode, fallback=request.current_mode or ASSISTANT_MODE_GENERAL)
        if raw_mode and raw_mode != best_mode and raw_mode not in _PUBLIC_MODE_ALIASES:
            reason = f"{reason} V4 normalized unsupported route mode {raw_mode} to {best_mode}.".strip()
        active_skills: list[str] = []
        for skill_name in (
            "task_recognition",
            "research_grounding",
            "study_coaching",
            "knowledge_synthesis",
            "office_coordination",
            "hotspot_tracking",
        ):
            decision = self.evaluate_skill_activation(
                skill_name,
                request.content,
                mode=best_mode,
                enable_keyword_fallback=enable_keyword_fallback,
            )
            if decision.value:
                active_skills.append(skill_name)
        lowered_content = request.content.lower()
        if _contains_any(lowered_content, _RESEARCH_INTENTS):
            source_profile = self.classify_source_profile(request.content, enable_keyword_fallback=enable_keyword_fallback)
        elif _contains_any(lowered_content, _STUDY_INTENTS):
            source_profile = "study_materials"
        else:
            source_profile = "workspace_local"
        return SemanticRouteDecision(
            mode=best_mode,
            confidence=selected.confidence,
            reason=reason,
            source_profile=source_profile,
            active_skills=_unique_strings(active_skills),
            should_preload_context=self.should_preload_context(
                request.content,
                enable_keyword_fallback=enable_keyword_fallback,
            ),
            prefer_live_web=self.is_live_web_query(
                request.content,
                enable_keyword_fallback=enable_keyword_fallback,
            ),
            signals=list(selected.signals),
            adapter_name=selected.adapter_name,
            used_keyword_fallback=used_keyword_fallback,
        )
