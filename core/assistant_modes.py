"""
Assistant mode routing, prompt bundles, and shared mode configuration.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.capability_registry import CapabilityRegistry
from core.public_contract import to_internal_assistant_mode
from core.prompt_assembler import PromptAssembler
from core.route_runtime import RouteRuntime
from core.semantic_router import SemanticRouterAgent
from core.skill_registry import SkillRegistryManager
from core.source_catalog import SourceCatalogManager

ASSISTANT_MODE_NORMAL = "normal"
ASSISTANT_MODE_AUTO = "auto"
ASSISTANT_MODE_DANXI = "danxi"
ASSISTANT_SPECIALIZED_MODES = ("documents", "research", "office", "study", "danxi")
ASSISTANT_MODES = (ASSISTANT_MODE_NORMAL, *ASSISTANT_SPECIALIZED_MODES)
VALID_ASSISTANT_MODES = (ASSISTANT_MODE_AUTO, *ASSISTANT_MODES)

ACTION_RISKS = ("read", "local_write", "external_write", "destructive")
ACTION_RISK_RANK = {name: index for index, name in enumerate(ACTION_RISKS)}

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_PATH_RE = re.compile(
    r"(?i)(?:[a-z]:[\\/][^\s]+|(?:\.{1,2}[\\/]|[\\/])?[^\s]+\.(?:md|txt|pdf|docx|xlsx|pptx|csv|json|py|ts|tsx|js|jsx|html))"
)

_MODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "documents": (
        "document",
        "docs",
        "file",
        "folder",
        "workspace",
        "directory",
        "repo",
        "repository",
        "project structure",
        "report",
        "summary file",
        "markdown",
        "pdf",
        "docx",
        "xlsx",
        "pptx",
        "csv",
        "json",
        "path",
        "local file",
        "local document",
        "read file",
        "write file",
        "rewrite file",
        "directory analysis",
        "directory tree",
        "文档",
        "文件",
        "目录",
        "文件夹",
        "工作区",
        "项目结构",
        "代码仓",
        "报告",
        "本地文件",
        "路径",
        "改写文档",
        "写入文档",
        "分析目录",
    ),
    "research": (
        "latest",
        "recent",
        "today",
        "news",
        "compare",
        "comparison",
        "recommend",
        "review",
        "what does this page say",
        "website",
        "web",
        "url",
        "source",
        "price",
        "policy",
        "regulation",
        "current",
        "official source",
        "最新",
        "最近",
        "今天",
        "新闻",
        "对比",
        "比较",
        "推荐",
        "评测",
        "网页",
        "链接",
        "网址",
        "一手信息",
        "资讯",
        "价格",
        "政策",
        "法规",
    ),
    "office": (
        "meeting",
        "agenda",
        "minutes",
        "schedule",
        "calendar",
        "invite",
        "attendee",
        "follow-up",
        "email",
        "message",
        "draft",
        "notion",
        "feishu",
        "sync notes",
        "todo",
        "task",
        "会议",
        "议程",
        "纪要",
        "日程",
        "日历",
        "排期",
        "邀请",
        "参会人",
        "邮件",
        "消息",
        "草稿",
        "同步笔记",
        "待办",
        "任务",
    ),
    "study": (
        "study",
        "learn",
        "learning",
        "course",
        "exam",
        "quiz",
        "flashcard",
        "mastery",
        "review",
        "practice",
        "syllabus",
        "lesson",
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
        "教案",
    ),
}

_NORMAL_WEB_HINTS = (
    "latest",
    "recent",
    "today",
    "news",
    "compare",
    "comparison",
    "recommend",
    "review",
    "what does this page say",
    "website",
    "web",
    "url",
    "link",
    "source",
    "current",
    "look up",
    "search online",
    "web search",
    "最新",
    "最近",
    "今天",
    "新闻",
    "比较",
    "推荐",
    "评测",
    "链接",
    "网址",
    "查一下",
    "搜一下",
    "上网查",
)

_DEEP_RESEARCH_HINTS = (
    "watchlist",
    "track updates",
    "source updates",
    "source update",
    "monitor",
    "monitoring",
    "research report",
    "with citations",
    "citation",
    "citations",
    "evidence",
    "evidence table",
    "source verification",
    "verify with sources",
    "strictly sourced",
    "official sources",
    "持续监测",
    "更新跟踪",
    "来源更新",
    "研究报告",
    "引用",
    "引文",
    "证据",
    "证据表",
    "来源核验",
    "核验来源",
    "严格引用",
)

_RESEARCH_PROFILE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "academic": (
        "paper",
        "research paper",
        "journal",
        "doi",
        "arxiv",
        "pubmed",
        "citation",
        "论文",
        "文献",
        "期刊",
        "doi",
        "研究",
    ),
    "policy": (
        "policy",
        "regulation",
        "law",
        "government",
        "sec",
        "fda",
        "who",
        "gov",
        "政策",
        "法规",
        "监管",
        "政府",
        "央行",
        "证监会",
        "药监",
    ),
    "finance": (
        "finance",
        "stock",
        "earnings",
        "investor relations",
        "ir",
        "10-k",
        "10-q",
        "price target",
        "财报",
        "股票",
        "金融",
        "投资者关系",
        "业绩",
        "股价",
    ),
}

_PRIMARY_SOURCE_DOMAINS = {
    "gov.cn",
    "stats.gov.cn",
    "www.gov.cn",
    "who.int",
    "fda.gov",
    "sec.gov",
    "edgar.sec.gov",
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "crossref.org",
    "doi.org",
    "w3.org",
    "whatwg.org",
    "ietf.org",
    "github.com",
    "gitee.com",
}

_DEFAULT_SOURCE_PROFILES = {
    "workspace_local": {
        "label": "Workspace / Local Knowledge",
        "description": "Prefer local files, project notes, memory, and trusted private sources.",
        "primary_domains": [],
        "source_order": ["local", "memory", "notion"],
        "freshness": "workspace",
    },
    "study_materials": {
        "label": "Study Materials",
        "description": "Prefer local learning materials, notes, and explicit references from the user.",
        "primary_domains": [],
        "source_order": ["local", "memory", "notion", "academic"],
        "freshness": "coursework",
    },
    "tech_global": {
        "label": "Tech Global",
        "description": "Official docs, GitHub releases, standards, and vendor changelogs first.",
        "primary_domains": [
            "github.com",
            "docs.python.org",
            "developer.mozilla.org",
            "w3.org",
            "whatwg.org",
            "ietf.org",
        ],
        "source_order": ["official_docs", "standard", "repo_release", "vendor", "media"],
        "freshness": "high",
    },
    "tech_cn": {
        "label": "Tech China",
        "description": "Chinese-language official docs, cloud vendor docs, and official repositories first.",
        "primary_domains": [
            "help.aliyun.com",
            "cloud.tencent.com",
            "support.huaweicloud.com",
            "gitee.com",
            "github.com",
        ],
        "source_order": ["official_docs", "vendor", "repo_release", "media"],
        "freshness": "high",
    },
    "academic": {
        "label": "Academic",
        "description": "Papers, DOI records, PubMed, and preprint indexes first.",
        "primary_domains": [
            "arxiv.org",
            "pubmed.ncbi.nlm.nih.gov",
            "doi.org",
            "crossref.org",
        ],
        "source_order": ["paper", "index", "official", "media"],
        "freshness": "medium",
    },
    "policy": {
        "label": "Policy / Regulation",
        "description": "Government and regulator sources first.",
        "primary_domains": [
            "gov.cn",
            "stats.gov.cn",
            "who.int",
            "fda.gov",
            "sec.gov",
            "edgar.sec.gov",
        ],
        "source_order": ["government", "regulator", "official", "media"],
        "freshness": "high",
    },
    "finance": {
        "label": "Finance",
        "description": "Exchange filings, official IR, and regulator disclosures first.",
        "primary_domains": [
            "sec.gov",
            "edgar.sec.gov",
            "nasdaq.com",
            "nyse.com",
        ],
        "source_order": ["exchange", "regulator", "ir", "official", "media"],
        "freshness": "high",
    },
    "campus_forum": {
        "label": "Campus Forum",
        "description": "Campus forum threads, replies, subscriptions, and private workspace context first.",
        "primary_domains": [
            "forum.fduhole.com",
            "auth.fduhole.com",
            "webvpn.fudan.edu.cn",
        ],
        "source_order": ["forum_api", "memory", "local"],
        "freshness": "high",
    },
}

_DEFAULT_MODE_TOOL_BUNDLES = {
    "normal": {
        "tools": [
            "get_sys_vitals",
            "research_topic",
            "inspect_page",
        ],
        "mcp_servers": [],
    },
    "documents": {
        "tools": [
            "exec_sys_cmd",
            "get_sys_vitals",
            "analyze_workspace",
            "read_local_documents",
            "write_local_document",
            "rewrite_local_document",
            "compile_report",
        ],
        "mcp_servers": ["filesystem_tools"],
    },
    "research": {
        "tools": [
            "research_topic",
            "inspect_page",
            "track_source_updates",
            "compile_report",
        ],
        "mcp_servers": [],
    },
    "office": {
        "tools": [
            "read_local_documents",
            "write_local_document",
            "compile_report",
            "manage_schedule",
            "draft_message",
            "meeting_brief",
            "sync_notes",
        ],
        "mcp_servers": ["filesystem_tools"],
    },
    "study": {
        "tools": [
            "read_local_documents",
            "compile_report",
            "build_study_plan",
            "extract_learning_points",
            "quiz_me",
            "generate_flashcards",
            "track_mastery",
        ],
        "mcp_servers": ["filesystem_tools"],
    },
    "danxi": {
        "tools": [
            "danxi_login",
            "danxi_logout",
            "danxi_get_session_status",
            "danxi_list_divisions",
            "danxi_list_tags",
            "danxi_list_posts",
            "danxi_get_post",
            "danxi_list_floors",
            "danxi_search_posts",
            "danxi_create_post",
            "danxi_reply_post",
            "danxi_edit_reply",
            "danxi_delete_reply",
            "danxi_delete_post",
            "danxi_manage_favorite",
            "danxi_manage_subscription",
            "danxi_list_messages",
            "danxi_mark_message_read",
        ],
        "mcp_servers": [],
    },
}

_DEFAULT_BASIC_MODE_TOOLS = [
    "ask_human",
    "get_current_system_time",
    "list_skills",
    "load_skill",
    "create_skill",
    "manage_procedures",
    "list_workspaces",
    "switch_workspace",
    "list_active_agents",
    "list_active_clients",
    "send_endpoint_message",
    "emit_short_reply",
    "restart_core",
    "search_knowledge",
    "search_memory",
    "search_web",
    "read_web_page",
    "remember_knowledge",
    "manage_memories",
    "summarize_text",
    "organize_notes",
    "extract_action_items",
]

_TASK_RECOGNITION_HINTS = (
    "todo",
    "to-do",
    "task",
    "tasks",
    "reminder",
    "remind me",
    "deadline",
    "due",
    "follow up",
    "follow-up",
    "blocker",
    "blocked",
    "complete",
    "completed",
    "finish this",
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
)

_DEFAULT_ROUTER_CONFIG = {
    "default_mode": ASSISTANT_MODE_NORMAL,
    "sticky_current_mode": True,
    "allow_preferred_override": True,
    "allow_in_turn_switch": True,
    "max_switches_per_round": 0,
    "max_switches_per_turn": 0,
    "max_tool_calls_per_round": 0,
    "fallback_to_heuristic": True,
    "semantic_routing_enabled": True,
}

_DEFAULT_DOCUMENT_PARSERS = {
    "max_file_bytes": 2_000_000,
    "max_total_chars": 24_000,
    "max_chunks_per_document": 12,
    "enable_ocr": True,
}

_DEFAULT_OFFICE_INTEGRATIONS = {
    "local": {"enabled": True, "draft_only": False},
    "notion": {"enabled": True, "draft_only": True},
    "feishu": {"enabled": True, "draft_only": True},
    "google": {"enabled": False, "draft_only": True},
    "outlook": {"enabled": False, "draft_only": True},
    "slack": {"enabled": False, "draft_only": True},
}

_MODE_PROMPT_FALLBACKS = {
    "auto-router": (
        "[Auto Router]\n"
        "Choose the working mode that best matches the user's next immediate step.\n"
        "Modes:\n"
        "- normal: ordinary conversation, daily assistant work, private knowledge lookup, and lightweight web work with the shared basic tools first\n"
        "- documents: local files, folders, workspace analysis, document writing, report generation, then document-specific tools when the shared basic tools are not enough\n"
        "- research: deep research, source tracking, evidence-heavy analysis, research-style reports, and the research_grounding skill layered on top of the shared basic tools\n"
        "- office: schedules, meeting briefs, drafts, notes sync, and coordination, with task_recognition available when task signals appear and the shared basic tools used for grounding\n"
        "- study: study plans, learning points, quizzes, flashcards, mastery tracking, and the study_coaching skill combined with the shared basic tools\n"
        "- danxi: FDU campus-forum browsing, thread search, favorites or subscriptions, messages, and normal-user post or reply actions through the Danxi tool suite\n"
        "Shared basic tools across modes include search_knowledge, search_memory, search_web, read_web_page, remember_knowledge, manage_memories, list_workspaces, switch_workspace, ask_human, and get_current_system_time.\n"
        "Task-style reminders can also activate the task_recognition skill to expose manage_tasks for user TODOs and manage_scheduled_tasks for assistant-owned scheduled work.\n"
        "If signals are mixed, prefer the smallest mode that directly matches the user's next job."
    ),
    "normal": (
        "[Normal Mode]\n"
        "You are operating as a general daily assistant.\n"
        "Handle ordinary conversation, lightweight planning, private knowledge lookup, and basic web search or direct page reading without escalating too early.\n"
        "Start with the shared basic tools in this mode: search_knowledge, search_memory, search_web, read_web_page, remember_knowledge, manage_memories, list_workspaces, switch_workspace, ask_human, and get_current_system_time.\n"
        "When the user's message clearly contains user TODO or scheduled-task work, the task_recognition skill can activate manage_tasks or manage_scheduled_tasks.\n"
        "Stay in normal mode unless the next immediate step clearly requires file tools, deep research constraints, office coordination tools, or study-specific tools."
    ),
    "documents": (
        "[Documents Mode]\n"
        "You are operating as a document and workspace specialist.\n"
        "Prefer local files, directory analysis, structured document reading, and safe draft-first writing.\n"
        "Start with the shared basic tools for knowledge lookup, memory lookup, and web/page reading when they help ground the document task, then move to document-specific tools for repository or file operations.\n"
        "If the user also mixes in user TODO or scheduled-task work, task_recognition can activate the matching task tool without leaving this mode.\n"
        "When editing documents, inspect first, summarize the current structure, and keep writes inside trusted roots unless the user explicitly confirms a broader target."
    ),
    "research": (
        "[Research Mode]\n"
        "You are operating as a research specialist.\n"
        "Prioritize first-party and official sources, reason explicitly about freshness, and ground claims in evidence objects and citations.\n"
        "Start with the shared basic tools such as search_web, read_web_page, search_memory, and search_knowledge for focused evidence collection, then use the research_grounding skill and heavier research flows when the task needs broader synthesis or source tracking.\n"
        "Use this mode for source-heavy analysis, update tracking, and report-style research work where rigorous sourcing matters."
    ),
    "office": (
        "[Office Mode]\n"
        "You are operating as an office and coordination specialist.\n"
        "Favor schedules, drafts, task state, meeting notes, and note synchronization.\n"
        "Start with the shared basic tools for knowledge lookup, memory lookup, and lightweight page reading before assuming an external system already acted, then use office-specific tools when coordination artifacts must be produced.\n"
        "Task-style requests can also activate the task_recognition skill so user TODO and scheduled-task tools stay available inside office workflows.\n"
        "External side effects stay draft-first. Do not pretend that a message or calendar entry has been sent unless the tool confirms it."
    ),
    "study": (
        "[Study Mode]\n"
        "You are operating as a study coach.\n"
        "Favor plans, extracted learning points, quizzes, flashcards, and mastery tracking.\n"
        "Start with the shared basic tools when you need memory lookup, private knowledge lookup, or lightweight page reading, then use the study_coaching skill to turn the retrieved material into guided learning work.\n"
        "If the user adds user TODOs or scheduled follow-ups, task_recognition can also activate the matching task tool."
    ),
    "danxi": (
        "[Danxi Mode]\n"
        "You are operating as a Danxi campus-forum specialist.\n"
        "Use Danxi tools only in this mode to browse forum content, search threads or floors, manage subscriptions or favorites, and perform normal-user post or reply operations.\n"
        "Prefer safe, low-frequency actions that match ordinary user behavior. Ask for confirmation before destructive actions such as deleting a post or reply.\n"
        "Keep all forum-side claims grounded in the returned Danxi API data, and use summarize_text, organize_notes, or extract_action_items to turn fetched thread data into concise deliverables."
    ),
}

_SKILL_PROMPT_FALLBACKS = {
    "task-recognition": (
        "[Task Recognition Skill]\n"
        "Detect when the user is creating, listing, updating, blocking, rescheduling, or completing actionable tasks.\n"
        "Use manage_tasks for user TODOs and manage_scheduled_tasks for assistant-owned scheduled tasks when task work is actually requested, instead of keeping task tracking only in free-form chat."
    ),
    "research-grounding": (
        "[Research Grounding Skill]\n"
        "Prioritize first-party and official sources, reason explicitly about freshness, and ground claims in evidence objects and citations.\n"
        "Start with focused basic-tool evidence gathering, then lead with the answer and cite sourced claims inline like [1], [2]. Distinguish between direct evidence and inference."
    ),
    "study-coaching": (
        "[Study Coaching Skill]\n"
        "Optimize for retention, practice, and source-grounded explanations.\n"
        "Start from the user's retrieved materials when available, preserve source references, and turn outputs into concrete study steps."
    ),
    "knowledge-synthesis": (
        "[Knowledge Synthesis Skill]\n"
        "Condense source material into a clear outline, concise summary, and actionable takeaways.\n"
        "Prefer lightweight native tools before escalating to heavier research or document workflows."
    ),
    "office-coordination": (
        "[Office Coordination Skill]\n"
        "Turn meeting notes, coordination context, and fragmented updates into structured briefs and action items.\n"
        "Keep outputs draft-first and make owners, follow-ups, and open questions explicit."
    ),
    "hotspot-tracking": (
        "[Hotspot Tracking Skill]\n"
        "Track evolving public topics, compare multiple sources, and produce a structured digest with clear freshness boundaries.\n"
        "Prefer available web and browser MCP capabilities, and fall back to native research tools when those integrations are unavailable."
    ),
    "model-capability-refresh": (
        "[Model Capability Refresh Skill]\n"
        "Refresh and verify model context/output limits with authoritative sources.\n"
        "Prefer provider APIs first, then official docs/versioned registry fallback, and never trust model self-reported limits.\n"
        "Unknown models must include diagnostics and low-confidence fallback status."
    ),
    "mode-danxi": (
        "[Danxi Mode Skill]\n"
        "Operate as a campus-forum workflow specialist.\n"
        "Browse divisions, threads, floors, subscriptions, favorites, and messages with Danxi tools; keep all forum writes low-risk and confirmation-first.\n"
        "Do not attempt admin-only APIs, bulk operations, concurrency tests, or other high-risk forum actions."
    ),
}

_DEFAULT_PROMPT_REGISTRY = {
    "auto-router": {"path": "prompt/modes/auto-router", "kind": "mode", "fallback": _MODE_PROMPT_FALLBACKS["auto-router"]},
    "mode:normal": {"path": "prompt/modes/normal", "kind": "mode", "fallback": _MODE_PROMPT_FALLBACKS["normal"]},
    "mode:documents": {"path": "prompt/modes/documents", "kind": "mode", "fallback": _MODE_PROMPT_FALLBACKS["documents"]},
    "mode:research": {"path": "prompt/modes/research", "kind": "mode", "fallback": _MODE_PROMPT_FALLBACKS["research"]},
    "mode:office": {"path": "prompt/modes/office", "kind": "mode", "fallback": _MODE_PROMPT_FALLBACKS["office"]},
    "mode:study": {"path": "prompt/modes/study", "kind": "mode", "fallback": _MODE_PROMPT_FALLBACKS["study"]},
    "mode:danxi": {"path": "prompt/modes/danxi", "kind": "mode", "fallback": _MODE_PROMPT_FALLBACKS["danxi"]},
    "skill:task-recognition": {
        "path": "prompt/SKILL/task-recognition",
        "kind": "skill",
        "fallback": _SKILL_PROMPT_FALLBACKS["task-recognition"],
    },
    "skill:research-grounding": {
        "path": "prompt/SKILL/research-grounding",
        "kind": "skill",
        "fallback": _SKILL_PROMPT_FALLBACKS["research-grounding"],
    },
    "skill:study-coaching": {
        "path": "prompt/SKILL/study-coaching",
        "kind": "skill",
        "fallback": _SKILL_PROMPT_FALLBACKS["study-coaching"],
    },
    "skill:knowledge-synthesis": {
        "path": "prompt/SKILL/knowledge-synthesis",
        "kind": "skill",
        "fallback": _SKILL_PROMPT_FALLBACKS["knowledge-synthesis"],
    },
    "skill:office-coordination": {
        "path": "prompt/SKILL/office-coordination",
        "kind": "skill",
        "fallback": _SKILL_PROMPT_FALLBACKS["office-coordination"],
    },
    "skill:model-capability-refresh": {
        "path": "prompt/SKILL/model-capability-refresh",
        "kind": "skill",
        "fallback": _SKILL_PROMPT_FALLBACKS["model-capability-refresh"],
    },
    "skill:hotspot-tracking": {
        "path": "prompt/SKILL/hotspot-tracking",
        "kind": "skill",
        "fallback": _SKILL_PROMPT_FALLBACKS["hotspot-tracking"],
    },
    "skill:mode-danxi": {
        "path": "prompt/SKILL/mode-danxi",
        "kind": "skill",
        "fallback": _SKILL_PROMPT_FALLBACKS["mode-danxi"],
    },
}

_DEFAULT_SKILL_REGISTRY = {
    "task_recognition": {
        "prompts": ["skill:task-recognition"],
        "tools": ["manage_tasks", "manage_scheduled_tasks"],
        "mcp_servers": [],
        "activation_keywords": list(_TASK_RECOGNITION_HINTS),
    },
    "research_grounding": {
        "prompts": ["skill:research-grounding"],
        "tools": [],
        "mcp_servers": [],
        "authorization": {"read_only": True},
    },
    "study_coaching": {
        "prompts": ["skill:study-coaching"],
        "tools": [],
        "mcp_servers": [],
    },
    "knowledge_synthesis": {
        "prompts": ["skill:knowledge-synthesis"],
        "tools": ["summarize_text", "organize_notes", "extract_action_items"],
        "mcp_servers": [],
        "scenes": ["knowledge_synthesis"],
        "activation_keywords": [
            "summary",
            "summarize",
            "outline",
            "organize",
            "takeaways",
            "整理",
            "提炼",
            "归纳",
            "摘要",
            "结构化",
        ],
    },
    "office_coordination": {
        "prompts": ["skill:office-coordination"],
        "tools": ["organize_notes", "extract_action_items"],
        "mcp_servers": ["notion_knowledge"],
        "scenes": ["office_coordination"],
        "activation_keywords": ["meeting", "minutes", "action items", "纪要", "同步", "后续"],
    },
    "model_capability_refresh": {
        "prompts": ["skill:model-capability-refresh"],
        "tools": [],
        "mcp_servers": [],
        "activation_keywords": [
            "model context",
            "context window",
            "output limit",
            "token limit",
            "模型上下文",
            "模型更新",
            "deepseek 新版本",
            "gpt-5.4",
        ],
        "authorization": {"read_only": True},
    },
    "hotspot_tracking": {
        "prompts": ["skill:hotspot-tracking"],
        "tools": ["summarize_text"],
        "mcp_servers": ["tavily_web", "browser_automation"],
        "scenes": ["hotspot_tracking"],
        "fallback_tools": ["research_topic", "inspect_page", "track_source_updates", "summarize_text"],
        "activation_keywords": ["hotspot", "trending", "breaking", "热点", "时政热点", "热搜", "舆情"],
        "authorization": {"read_only": True},
    },
    "danxi_digest": {
        "prompts": [],
        "tools": ["summarize_text", "organize_notes", "extract_action_items"],
        "mcp_servers": [],
        "scenes": ["danxi_forum_ops"],
        "activation_keywords": ["danxi", "旦夕", "fduhole", "forum", "帖子", "楼层", "校内论坛"],
    },
}

_DEFAULT_SCENE_DEFINITIONS = {
    "knowledge_synthesis": {
        "title": "Knowledge Synthesis",
        "summary": "轻量总结、重组笔记与提炼行动项。",
        "applicable_modes": ["normal", "documents", "research", "office", "study"],
        "skills": ["knowledge_synthesis"],
        "tools": ["summarize_text", "organize_notes", "extract_action_items"],
        "mcp_servers": [],
        "fallback_tools": ["summarize_text", "organize_notes"],
        "activation_keywords": ["summary", "outline", "整理", "提炼", "摘要", "结构化"],
    },
    "workspace_delivery": {
        "title": "Workspace Delivery",
        "summary": "处理工作区读取、报告整理与结构化交付。",
        "applicable_modes": ["documents", "office"],
        "skills": ["knowledge_synthesis"],
        "tools": ["analyze_workspace", "read_local_documents", "compile_report", "organize_notes"],
        "mcp_servers": ["filesystem_tools"],
        "fallback_tools": ["analyze_workspace", "read_local_documents", "compile_report"],
        "activation_keywords": ["workspace", "repo", "目录", "工作区", "项目结构"],
    },
    "research_synthesis": {
        "title": "Research Synthesis",
        "summary": "科研、资料核验与来源追踪。",
        "applicable_modes": ["research", "normal"],
        "skills": ["research_grounding", "knowledge_synthesis"],
        "tools": ["research_topic", "inspect_page", "track_source_updates", "summarize_text"],
        "mcp_servers": ["tavily_web", "browser_automation"],
        "fallback_tools": ["research_topic", "inspect_page", "track_source_updates", "summarize_text"],
        "activation_keywords": ["citation", "evidence", "policy", "research", "引用", "证据", "核验"],
        "authorization": {"read_only": True},
    },
    "office_coordination": {
        "title": "Office Coordination",
        "summary": "办公整理、会议纪要、跟进事项与沟通草稿。",
        "applicable_modes": ["office", "documents"],
        "skills": ["office_coordination", "task_recognition"],
        "tools": ["meeting_brief", "draft_message", "sync_notes", "organize_notes", "extract_action_items"],
        "mcp_servers": ["filesystem_tools", "notion_knowledge"],
        "fallback_tools": ["meeting_brief", "draft_message", "organize_notes", "extract_action_items"],
        "activation_keywords": ["meeting", "agenda", "minutes", "纪要", "同步", "消息"],
    },
    "study_guidance": {
        "title": "Study Guidance",
        "summary": "学习计划、知识提炼与复盘练习。",
        "applicable_modes": ["study"],
        "skills": ["study_coaching", "knowledge_synthesis"],
        "tools": ["build_study_plan", "extract_learning_points", "quiz_me", "generate_flashcards", "summarize_text"],
        "mcp_servers": ["filesystem_tools"],
        "fallback_tools": ["build_study_plan", "extract_learning_points", "summarize_text"],
        "activation_keywords": ["study", "quiz", "flashcard", "学习", "复习", "知识点"],
    },
    "hotspot_tracking": {
        "title": "Hotspot Tracking",
        "summary": "热点事件追踪、多源比对与摘要输出。",
        "applicable_modes": ["normal", "research"],
        "skills": ["hotspot_tracking", "research_grounding"],
        "tools": ["research_topic", "inspect_page", "track_source_updates", "summarize_text"],
        "mcp_servers": ["tavily_web", "browser_automation"],
        "fallback_tools": ["research_topic", "inspect_page", "track_source_updates", "summarize_text"],
        "activation_keywords": ["hotspot", "trending", "breaking", "热点", "时政热点", "热搜", "舆情"],
        "authorization": {"read_only": True},
    },
    "danxi_forum_ops": {
        "title": "Danxi Forum Ops",
        "summary": "校内论坛浏览、信息整理与低风险普通用户操作。",
        "applicable_modes": ["danxi"],
        "skills": ["danxi_digest", "knowledge_synthesis"],
        "tools": [
            "danxi_list_posts",
            "danxi_get_post",
            "danxi_list_floors",
            "danxi_search_posts",
            "danxi_list_messages",
            "summarize_text",
            "organize_notes",
            "extract_action_items",
        ],
        "mcp_servers": [],
        "fallback_tools": ["danxi_list_posts", "danxi_get_post", "danxi_list_floors", "summarize_text"],
        "activation_keywords": ["danxi", "旦夕", "forum", "帖子", "楼层", "收藏", "订阅"],
    },
}

_DEFAULT_MCP_CATALOG = {
    "filesystem_tools": {
        "title": "Filesystem Tools",
        "summary": "访问本地文件、目录与工作区元数据。",
        "scenarios": ["documents", "workspace", "office sync", "study materials"],
        "risk_level": "read",
        "auth_env": [],
        "fallback_tools": ["analyze_workspace", "read_local_documents"],
        "enabled_by_default": True,
        "boundary": "agent_mcp",
        "managed_by": "desktop_or_edge_agent",
        "classification_reason": "本地文件、工作区与终端邻接能力仍由 Desktop Agent / Edge Agent 托管，不收口到 Core MCP。",
    },
    "tavily_web": {
        "title": "Tavily Web Search",
        "summary": "为外部网页搜索与抽取提供更强的在线检索能力。",
        "scenarios": ["research", "news", "hotspot tracking"],
        "risk_level": "read",
        "auth_env": ["TAVILY_API_KEY"],
        "fallback_tools": ["search_web", "read_web_page", "research_topic"],
        "enabled_by_default": False,
        "boundary": "core_mcp",
        "managed_by": "core",
        "classification_reason": "服务端可安全托管的外部检索能力，应优先通过 Core MCP 暴露。",
    },
    "browser_automation": {
        "title": "Browser Automation",
        "summary": "浏览器导航与页面快照能力，用于复杂网页观察。",
        "scenarios": ["research", "inspection", "hotspot tracking"],
        "risk_level": "read",
        "auth_env": [],
        "fallback_tools": ["inspect_page", "read_web_page"],
        "enabled_by_default": False,
        "boundary": "core_mcp",
        "managed_by": "core",
        "classification_reason": "非端侧网页观察能力可在服务端沙箱内运行，属于 Core MCP 收口范围。",
    },
    "notion_knowledge": {
        "title": "Notion Knowledge",
        "summary": "私有 Notion 知识库读取与检索。",
        "scenarios": ["office", "knowledge base", "workspace memory"],
        "risk_level": "read",
        "auth_env": ["NOTION_TOKEN"],
        "fallback_tools": ["search_knowledge", "search_memory", "organize_notes"],
        "enabled_by_default": False,
        "boundary": "core_mcp",
        "managed_by": "core",
        "classification_reason": "远程知识库读取属于服务端集成能力，应通过 Core MCP 统一治理与诊断。",
    },
}

_DEFAULT_CORE_MCP_CLASSIFICATION_STANDARD = {
    "core_mcp": {
        "criteria": [
            "能力不依赖本地文件、Shell 或端侧本地 MCP 生命周期。",
            "能力可在服务端通过显式配置、鉴权与审计安全托管。",
            "能力面向外部搜索、浏览、知识库等非端侧集成面。",
        ],
        "decision": "正式收口到 Core MCP。",
    },
    "agent_mcp": {
        "criteria": [
            "能力直接触达本地文件系统、终端或工作区运行时。",
            "能力需要随端侧会话、权限与本地 MCP 生命周期一起托管。",
        ],
        "decision": "继续留在 Desktop Agent / Edge Agent，不纳入 Core MCP。",
    },
    "runtime_native_exception": {
        "criteria": [
            "能力是纯进程内轻量逻辑，不依赖外部集成或 MCP server。",
            "能力主要做文本整理、状态读取或 Core 自身内存/任务编排。",
        ],
        "decision": "保留为 runtime-native tool，不一刀切迁为 MCP。",
    },
}

_DEFAULT_RUNTIME_NATIVE_TOOL_EXCEPTIONS = [
    {
        "tool_name": "summarize_text",
        "category": "lightweight_transform",
        "reason": "纯进程内摘要整理，不依赖外部集成。",
    },
    {
        "tool_name": "organize_notes",
        "category": "lightweight_transform",
        "reason": "纯进程内笔记结构化，不依赖外部集成。",
    },
    {
        "tool_name": "extract_action_items",
        "category": "lightweight_transform",
        "reason": "纯进程内行动项提炼，不依赖外部集成。",
    },
    {
        "tool_name": "manage_tasks",
        "category": "core_state",
        "reason": "直接管理 Core 自身任务状态，不是外部集成。",
    },
    {
        "tool_name": "manage_scheduled_tasks",
        "category": "core_state",
        "reason": "直接管理 Core 自身调度状态，不是外部集成。",
    },
    {
        "tool_name": "manage_procedures",
        "category": "core_state",
        "reason": "直接管理 Core procedure 目录与审批，不是外部集成。",
    },
]

_DEFAULT_MODE_DEFINITIONS = {
    "normal": {
        "prompts": ["mode:normal"],
        "mode_skills": ["mode:normal"],
        "tools": _DEFAULT_MODE_TOOL_BUNDLES["normal"]["tools"],
        "mcp_servers": _DEFAULT_MODE_TOOL_BUNDLES["normal"]["mcp_servers"],
        "skills": [],
        "auto_skills": ["task_recognition"],
        "scenes": ["knowledge_synthesis"],
    },
    "documents": {
        "prompts": ["mode:documents"],
        "mode_skills": ["mode:documents"],
        "tools": _DEFAULT_MODE_TOOL_BUNDLES["documents"]["tools"],
        "mcp_servers": _DEFAULT_MODE_TOOL_BUNDLES["documents"]["mcp_servers"],
        "skills": [],
        "auto_skills": ["task_recognition"],
        "scenes": ["workspace_delivery", "knowledge_synthesis"],
    },
    "research": {
        "prompts": ["mode:research"],
        "mode_skills": ["mode:research"],
        "tools": _DEFAULT_MODE_TOOL_BUNDLES["research"]["tools"],
        "mcp_servers": _DEFAULT_MODE_TOOL_BUNDLES["research"]["mcp_servers"],
        "skills": ["research_grounding"],
        "auto_skills": ["task_recognition", "hotspot_tracking", "knowledge_synthesis"],
        "scenes": ["research_synthesis", "hotspot_tracking"],
        "authorization": {"read_only": True},
    },
    "office": {
        "prompts": ["mode:office"],
        "mode_skills": ["mode:office"],
        "tools": _DEFAULT_MODE_TOOL_BUNDLES["office"]["tools"],
        "mcp_servers": _DEFAULT_MODE_TOOL_BUNDLES["office"]["mcp_servers"],
        "skills": [],
        "auto_skills": ["task_recognition", "office_coordination", "knowledge_synthesis"],
        "scenes": ["office_coordination", "knowledge_synthesis"],
    },
    "study": {
        "prompts": ["mode:study"],
        "mode_skills": ["mode:study"],
        "tools": _DEFAULT_MODE_TOOL_BUNDLES["study"]["tools"],
        "mcp_servers": _DEFAULT_MODE_TOOL_BUNDLES["study"]["mcp_servers"],
        "skills": ["study_coaching"],
        "auto_skills": ["task_recognition", "knowledge_synthesis"],
        "scenes": ["study_guidance", "knowledge_synthesis"],
    },
    "danxi": {
        "prompts": ["mode:danxi"],
        "mode_skills": ["mode:danxi"],
        "tools": _DEFAULT_MODE_TOOL_BUNDLES["danxi"]["tools"],
        "mcp_servers": _DEFAULT_MODE_TOOL_BUNDLES["danxi"]["mcp_servers"],
        "skills": [],
        "auto_skills": ["danxi_digest", "knowledge_synthesis"],
        "scenes": ["danxi_forum_ops", "knowledge_synthesis"],
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_json_config(raw_value: Any) -> Any:
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            return {}
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return {}
    return raw_value or {}


def _unique_strings(values: list[Any] | tuple[Any, ...] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _normalize_mode(value: Any, *, fallback: str = ASSISTANT_MODE_NORMAL) -> str:
    normalized = to_internal_assistant_mode(value, fallback=fallback)
    if normalized in VALID_ASSISTANT_MODES:
        return normalized
    return fallback


def _normalize_path(path_value: str) -> str:
    return str(Path(path_value).expanduser().resolve())


def _domain_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    return parsed.netloc.lower().strip()


def _looks_like_chinese(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


RouteDecision = RouteRuntime


class AssistantModeManager:
    def __init__(self, config_manager, *, semantic_router: SemanticRouterAgent | None = None):
        self._config = config_manager
        self._source_catalog = SourceCatalogManager(config_manager)
        self._semantic_router = semantic_router or SemanticRouterAgent()
        assistant_modes_config = _parse_json_config(self._config.get("assistant_modes"))
        self._skill_registry = SkillRegistryManager(
            skill_dir=str(assistant_modes_config.get("skill_prompt_dir") or "prompt/SKILL")
        )
        self._capability_registry = CapabilityRegistry(self._mode_registry(), self._skill_registry)
        self._prompt_assembler = PromptAssembler(self._capability_registry)

    def _mode_registry(self) -> dict[str, Any]:
        return _deep_merge(
            {
                "enabled_modes": list(ASSISTANT_MODES),
                "prompt_dir": "prompt/modes",
                "skill_prompt_dir": "prompt/SKILL",
                "basic_tools": list(_DEFAULT_BASIC_MODE_TOOLS),
                "prompt_registry": _DEFAULT_PROMPT_REGISTRY,
                "skills": _DEFAULT_SKILL_REGISTRY,
                "mode_definitions": _DEFAULT_MODE_DEFINITIONS,
                "scene_definitions": _DEFAULT_SCENE_DEFINITIONS,
                "mcp_catalog": _DEFAULT_MCP_CATALOG,
                "tool_bundles": _DEFAULT_MODE_TOOL_BUNDLES,
            },
            _parse_json_config(self._config.get("assistant_modes")),
        )

    def get_mode_router_config(self) -> dict[str, Any]:
        return _deep_merge(_DEFAULT_ROUTER_CONFIG, _parse_json_config(self._config.get("mode_router")))

    def get_document_parser_config(self) -> dict[str, Any]:
        return _deep_merge(_DEFAULT_DOCUMENT_PARSERS, _parse_json_config(self._config.get("document_parsers")))

    def get_office_integrations(self) -> dict[str, Any]:
        return _deep_merge(_DEFAULT_OFFICE_INTEGRATIONS, _parse_json_config(self._config.get("office_integrations")))

    def set_source_catalog_backend(self, backend, *, migrate_current: bool = False) -> None:
        self._source_catalog.set_store_backend(backend, migrate_current=migrate_current)

    def get_source_catalog_path(self) -> str:
        return self._source_catalog.get_catalog_path()

    def get_source_catalog_status(self) -> dict[str, Any]:
        return self._source_catalog.get_catalog_status()

    def get_source_profiles(self) -> dict[str, Any]:
        return self._source_catalog.get_source_profiles()

    def get_source_profile(self, profile_name: str) -> dict[str, Any]:
        profiles = self.get_source_profiles()
        normalized = str(profile_name or "").strip() or "workspace_local"
        payload = profiles.get(normalized)
        if payload is None:
            payload = profiles.get("tech_updates") or profiles.get("workspace_local", {})
            normalized = "tech_updates" if "tech_updates" in profiles else "workspace_local"
        return {"name": normalized, **payload}

    def get_sources_for_profile(
        self,
        profile_name: str,
        *,
        official_only: bool | None = None,
    ) -> list[dict[str, Any]]:
        return self._source_catalog.get_sources(profile_name, official_only=official_only)

    def get_source_by_id(self, source_id: str) -> dict[str, Any] | None:
        return self._source_catalog.get_source_by_id(source_id)

    def resolve_source_auth_entries(self, source_config: dict[str, Any]) -> list[dict[str, Any]]:
        return self._source_catalog.resolve_auth_entries(source_config)

    def _get_mode_definition(self, mode: str) -> dict[str, Any]:
        return self._capability_registry.get_mode_capability(mode).to_dict()

    def _get_skill_definition(self, skill_name: str) -> dict[str, Any]:
        capability = self._capability_registry.get_skill_capability(skill_name)
        return capability.to_dict(include_content=True) if capability is not None else {}

    def _evaluate_skill_activation(self, skill_name: str, *, content: str, mode: str = "") -> dict[str, Any]:
        if hasattr(self._semantic_router, "evaluate_skill_activation"):
            decision = self._semantic_router.evaluate_skill_activation(skill_name, content, mode=mode)
            return {
                "skill_id": skill_name,
                "active": bool(getattr(decision, "value", False)),
                "reason": str(getattr(decision, "reason", "") or "").strip(),
                "signals": _unique_strings(getattr(decision, "signals", [])),
                "confidence": str(getattr(decision, "confidence", "") or "").strip(),
                "adapter_name": str(getattr(decision, "adapter_name", "") or "").strip(),
                "source": "router",
            }
        return {
            "skill_id": skill_name,
            "active": bool(self._semantic_router.should_activate_skill(skill_name, content, mode=mode)),
            "reason": "",
            "signals": [],
            "confidence": "",
            "adapter_name": "",
            "source": "router",
        }

    def _resolve_active_skills(self, mode: str, *, content: str = "") -> list[str]:
        return self._capability_registry.resolve_active_skills(
            mode,
            content=content,
            activator=lambda skill_name, skill_content: self._evaluate_skill_activation(
                skill_name,
                content=skill_content,
                mode=mode,
            ),
        )

    def _resolve_prompt_text(self, prompt_name: str) -> str:
        return self._capability_registry.get_prompt_text(prompt_name)

    def assemble_prompt_for_mode(
        self,
        mode: str,
        *,
        content: str = "",
        active_skills: list[str] | None = None,
        loaded_skills: list[str] | None = None,
    ) -> str:
        normalized_mode = _normalize_mode(mode, fallback=mode)
        return self._prompt_assembler.assemble_for_mode(
            normalized_mode,
            content=content,
            active_skills=active_skills,
            loaded_skills=loaded_skills,
        )

    def get_tool_bundle(
        self,
        mode: str,
        *,
        content: str = "",
        active_skills: list[str] | None = None,
        loaded_skills: list[str] | None = None,
    ) -> dict[str, Any]:
        capability_set = self._capability_registry.build_capability_set(
            _normalize_mode(mode),
            content=content,
            active_skills=active_skills,
            loaded_skills=loaded_skills,
            activator=lambda skill_name, skill_content: self._evaluate_skill_activation(
                skill_name,
                content=skill_content,
                mode=_normalize_mode(mode),
            ),
        )
        return {
            "tools": list(capability_set.tools),
            "mcp_servers": list(capability_set.mcp_servers),
            "active_skills": list(capability_set.active_skills),
            "scene_ids": list(capability_set.scene_ids),
            "authorization": dict(capability_set.authorization),
            "mcp_diagnostics": [dict(item) for item in capability_set.mcp_diagnostics],
            "degradation_notes": [dict(item) for item in capability_set.degradation_notes],
        }

    def build_route_for_mode(
        self,
        mode: str,
        *,
        requested_mode: str = ASSISTANT_MODE_AUTO,
        reason: str = "",
        content: str = "",
        active_skills: list[str] | None = None,
        source_profile: str = "",
        loaded_skills: list[str] | None = None,
        confidence: str = "",
        should_preload_context: bool = False,
        prefer_live_web: bool = False,
        signals: list[str] | None = None,
        adapter_name: str = "",
        used_keyword_fallback: bool = False,
    ) -> RouteDecision:
        normalized_mode = _normalize_mode(mode)
        capability_set = self._capability_registry.build_capability_set(
            normalized_mode,
            content=content,
            active_skills=active_skills,
            loaded_skills=loaded_skills,
            activator=lambda skill_name, skill_content: self._evaluate_skill_activation(
                skill_name,
                content=skill_content,
                mode=normalized_mode,
            ),
        )
        route_reason = str(reason or "").strip() or f"Selected mode: {normalized_mode}"
        if capability_set.skill_activations:
            skill_reasons = [
                f"{item['skill_id']}:{item['reason']}"
                for item in capability_set.skill_activations
                if str(item.get("skill_id") or "").strip() and str(item.get("reason") or "").strip()
            ]
            if skill_reasons:
                route_reason = f"{route_reason} Skills -> {'; '.join(skill_reasons)}"
        if capability_set.degradation_notes:
            degradation_labels = [
                f"{item['capability_id']}:{item['status']}"
                for item in capability_set.degradation_notes
                if str(item.get("capability_id") or "").strip()
            ]
            if degradation_labels:
                route_reason = f"{route_reason} Fallbacks -> {', '.join(degradation_labels)}"
        active_skill_ids = list(capability_set.active_skills)
        loaded_skill_ids = list(capability_set.loaded_skills)
        prompt_bundle_parts = [normalized_mode, *active_skill_ids, *loaded_skill_ids]
        return RouteDecision(
            requested_mode=_normalize_mode(requested_mode, fallback=ASSISTANT_MODE_AUTO),
            current_mode=normalized_mode,
            route_reason=route_reason,
            source_profile=source_profile or self._default_source_profile_for_mode(normalized_mode, content),
            tool_bundle=list(capability_set.tools),
            mcp_servers=list(capability_set.mcp_servers),
            prompt_bundle="+".join(prompt_bundle_parts) if prompt_bundle_parts else normalized_mode,
            active_skills=active_skill_ids,
            loaded_skills=loaded_skill_ids,
            confidence=str(confidence or "").strip(),
            should_preload_context=bool(should_preload_context),
            prefer_live_web=bool(prefer_live_web),
            signals=_unique_strings(signals),
            adapter_name=str(adapter_name or "").strip(),
            used_keyword_fallback=bool(used_keyword_fallback),
            authorization_policy=dict(capability_set.authorization),
            capability_set=capability_set.to_dict(),
            skill_activations=[dict(item) for item in capability_set.skill_activations],
            capability_sources=dict(capability_set.capability_sources),
            degradation_notes=[dict(item) for item in capability_set.degradation_notes],
        )

    def get_prompt_for_mode(
        self,
        mode: str,
        *,
        content: str = "",
        active_skills: list[str] | None = None,
        loaded_skills: list[str] | None = None,
    ) -> str:
        if mode == "auto-router":
            return self._resolve_prompt_text("auto-router")
        return self.assemble_prompt_for_mode(
            mode,
            content=content,
            active_skills=active_skills,
            loaded_skills=loaded_skills,
        )

    def assemble_prompt_for_route(self, route_context: dict[str, Any] | None) -> str:
        return self._prompt_assembler.assemble_for_route(route_context)

    def get_auto_router_prompt(self) -> str:
        return self.get_prompt_for_mode("auto-router")

    def list_skills(self, *, skill_type: str = "all", query: str = "") -> list[dict[str, Any]]:
        return self._skill_registry.list_skills(skill_type=skill_type, query=query)

    def load_skill(self, skill_id: str) -> dict[str, Any] | None:
        return self._skill_registry.load_skill(skill_id)

    def get_skill_capability(self, skill_id: str) -> dict[str, Any] | None:
        capability = self._capability_registry.get_skill_capability(skill_id)
        return capability.to_dict(include_content=True) if capability is not None else None

    def get_capability_registry(self) -> CapabilityRegistry:
        return self._capability_registry

    def get_prompt_assembler(self) -> PromptAssembler:
        return self._prompt_assembler

    def validate_capability_registry(
        self,
        *,
        tool_names: list[str] | None = None,
        mcp_servers: list[str] | None = None,
    ) -> list[str]:
        available_tool_names = set(_unique_strings(tool_names))
        available_mcp_servers = set(_unique_strings(mcp_servers))
        return self._capability_registry.validate(
            tool_checker=(lambda tool_name: tool_name in available_tool_names) if available_tool_names else None,
            mcp_checker=(lambda server_name: server_name in available_mcp_servers) if available_mcp_servers else None,
        )

    def get_capability_diagnostics(
        self,
        *,
        tool_names: list[str] | None = None,
        available_mcp_servers: list[str] | None = None,
        configured_mcp_servers: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._capability_registry.get_diagnostics(
            tool_names=tool_names,
            available_mcp_servers=available_mcp_servers,
            configured_mcp_servers=configured_mcp_servers,
        )

    def get_core_mcp_boundary_diagnostics(
        self,
        *,
        available_mcp_servers: list[str] | None = None,
        configured_mcp_servers: list[str] | None = None,
    ) -> dict[str, Any]:
        diagnostics = self.get_capability_diagnostics(
            available_mcp_servers=available_mcp_servers,
            configured_mcp_servers=configured_mcp_servers,
        )
        configured_set = set(_unique_strings(configured_mcp_servers))
        core_mcp_servers: list[dict[str, Any]] = []
        agent_managed_mcp_servers: list[dict[str, Any]] = []
        for item in diagnostics.get("mcp_servers", []):
            payload = dict(item or {})
            if str(payload.get("boundary") or "core_mcp").strip() == "agent_mcp":
                agent_managed_mcp_servers.append(payload)
            else:
                core_mcp_servers.append(payload)

        configured_core_servers = [
            item for item in core_mcp_servers
            if str(item.get("server_name") or "").strip() in configured_set
        ]
        enabled_core_servers = [
            item for item in configured_core_servers
            if str(item.get("status") or "").strip() == "enabled"
        ]
        partial_failure_servers = [
            item for item in configured_core_servers
            if str(item.get("status") or "").strip() in {"requires_auth", "unavailable"}
        ]
        return {
            "classification_standard": json.loads(json.dumps(_DEFAULT_CORE_MCP_CLASSIFICATION_STANDARD, ensure_ascii=False)),
            "core_mcp_servers": core_mcp_servers,
            "agent_managed_mcp_servers": agent_managed_mcp_servers,
            "runtime_native_tools": json.loads(json.dumps(_DEFAULT_RUNTIME_NATIVE_TOOL_EXCEPTIONS, ensure_ascii=False)),
            "summary": {
                "configured_server_count": len(configured_core_servers),
                "enabled_count": len(enabled_core_servers),
                "partial_failure_count": len(partial_failure_servers),
                "partial_failure_servers": [
                    str(item.get("server_name") or "").strip()
                    for item in partial_failure_servers
                    if str(item.get("server_name") or "").strip()
                ],
                "agent_managed_server_count": len(agent_managed_mcp_servers),
                "runtime_native_exception_count": len(_DEFAULT_RUNTIME_NATIVE_TOOL_EXCEPTIONS),
            },
        }

    def create_skill(
        self,
        *,
        skill_id: str,
        title: str,
        summary: str,
        content: str,
        recommended_tools: list[str] | None = None,
        applicable_modes: list[str] | None = None,
        scenarios: list[str] | None = None,
        source: str = "agent",
    ) -> dict[str, Any]:
        return self._skill_registry.create_skill(
            skill_id=skill_id,
            title=title,
            summary=summary,
            content=content,
            recommended_tools=recommended_tools,
            applicable_modes=applicable_modes,
            scenarios=scenarios,
            source=source,
        )

    def should_preload_context(self, query: str, goal: str = "") -> bool:
        return self._semantic_router.should_preload_context(query, goal)

    def is_live_web_query(self, query: str) -> bool:
        return self._semantic_router.is_live_web_query(query)

    def get_trusted_write_roots(self) -> list[str]:
        configured = _parse_json_config(self._config.get("trusted_write_roots"))
        if isinstance(configured, str):
            configured = [configured]
        roots = [str(item).strip() for item in (configured or []) if str(item).strip()]
        if not roots:
            cwd = Path.cwd()
            roots = [
                str(cwd),
                str(cwd / "user"),
                str(cwd / "docs"),
            ]
        normalized: list[str] = []
        for root in roots:
            try:
                normalized.append(_normalize_path(root))
            except Exception:
                continue
        return list(dict.fromkeys(normalized))

    def is_trusted_write_path(self, path_value: str) -> bool:
        if not path_value:
            return False
        try:
            candidate = Path(path_value).expanduser().resolve()
        except Exception:
            return False
        candidate_str = str(candidate)
        for root in self.get_trusted_write_roots():
            if candidate_str == root or candidate_str.startswith(f"{root}{os.sep}"):
                return True
        return False

    def classify_research_source_profile(self, text: str) -> str:
        classified = self._semantic_router.classify_source_profile(text)
        if classified:
            return classified
        classified = self._source_catalog.classify_research_profile(text)
        if classified:
            return classified
        if _looks_like_chinese(text):
            return "policy_cn"
        return "tech_updates"

    def is_primary_source(self, url: str, profile_name: str = "") -> bool:
        return self._source_catalog.is_primary_source(url, profile_name)

    async def resolve_context_limit(
        self,
        *,
        provider_name: str,
        api_url: str,
        model_name: str,
        adapter,
    ) -> dict[str, Any]:
        return (
            await self._source_catalog.resolve_context_limit(
                provider_name=provider_name,
                api_url=api_url,
                model_name=model_name,
                adapter=adapter,
            )
        ).to_dict()

    def _restore_loaded_skills(self, session_metadata: dict[str, Any] | None) -> list[str]:
        session_metadata = session_metadata or {}
        current_route = session_metadata.get("current_route")
        if isinstance(current_route, dict):
            restored = _unique_strings(current_route.get("loaded_skills"))
            if restored:
                return restored
        return _unique_strings(session_metadata.get("loaded_skills"))

    def _fallback_route_by_keywords(self, content: str, *, current_mode: str, sticky_current_mode: bool) -> tuple[str, str]:
        scores = {mode: 0 for mode in ASSISTANT_MODES}
        triggers = {mode: [] for mode in ASSISTANT_MODES}
        lowered = content.lower()

        for mode, keywords in _MODE_KEYWORDS.items():
            if mode == "research":
                continue
            for keyword in keywords:
                if keyword in lowered:
                    scores[mode] += 2
                    if len(triggers[mode]) < 4:
                        triggers[mode].append(keyword)

        for keyword in _NORMAL_WEB_HINTS:
            if keyword in lowered:
                scores[ASSISTANT_MODE_NORMAL] += 2
                if len(triggers[ASSISTANT_MODE_NORMAL]) < 4:
                    triggers[ASSISTANT_MODE_NORMAL].append(keyword)

        for keyword in _DEEP_RESEARCH_HINTS:
            if keyword in lowered:
                scores["research"] += 3
                if len(triggers["research"]) < 4:
                    triggers["research"].append(keyword)

        if _URL_RE.search(content):
            scores[ASSISTANT_MODE_NORMAL] += 4
            if len(triggers[ASSISTANT_MODE_NORMAL]) < 4:
                triggers[ASSISTANT_MODE_NORMAL].append("direct_url")

        if _PATH_RE.search(content):
            scores["documents"] += 4
            if len(triggers["documents"]) < 4:
                triggers["documents"].append("local_path")

        if sticky_current_mode and current_mode in ASSISTANT_MODES:
            scores[current_mode] += 1
            if len(triggers[current_mode]) < 4:
                triggers[current_mode].append("sticky_current_mode")

        best_mode = max(scores.items(), key=lambda item: (item[1], item[0]))[0]
        if scores[best_mode] <= 0:
            best_mode = current_mode if current_mode in ASSISTANT_MODES else ASSISTANT_MODE_NORMAL
            reason = (
                f"No strong routing signal found; reusing current mode {best_mode}."
                if current_mode in ASSISTANT_MODES
                else "No strong routing signal found; defaulting to normal for ordinary conversation."
            )
            return best_mode, reason

        matched = ", ".join(dict.fromkeys(triggers[best_mode])) or "keyword_match"
        return best_mode, f"Keyword fallback selected {best_mode}: {matched}"

    def route(
        self,
        input_info: dict[str, Any],
        *,
        session_metadata: dict[str, Any] | None = None,
        source=None,
    ) -> RouteDecision:
        session_metadata = session_metadata or {}
        router_config = self.get_mode_router_config()
        preferred_mode = _normalize_mode(
            (input_info.get("metadata") or {}).get("preferred_mode")
            or input_info.get("preferred_mode"),
            fallback="",
        )
        has_explicit_preference = bool(preferred_mode)
        requested_mode = _normalize_mode(
            preferred_mode
            or router_config.get("default_mode")
            or ASSISTANT_MODE_NORMAL,
            fallback=ASSISTANT_MODE_NORMAL,
        )

        content = str(input_info.get("content") or "").strip()
        current_mode = _normalize_mode(session_metadata.get("current_mode") or "", fallback="")
        loaded_skills = self._restore_loaded_skills(session_metadata)
        if (
            has_explicit_preference
            and requested_mode in ASSISTANT_SPECIALIZED_MODES
            and router_config.get("allow_preferred_override", True)
        ):
            return self.build_route_for_mode(
                requested_mode,
                requested_mode=requested_mode,
                reason=f"Preferred mode override requested: {requested_mode}",
                content=content,
                loaded_skills=loaded_skills,
            )
        if has_explicit_preference and requested_mode == ASSISTANT_MODE_NORMAL:
            return self.build_route_for_mode(
                ASSISTANT_MODE_NORMAL,
                requested_mode=ASSISTANT_MODE_NORMAL,
                reason="Preferred mode selected: normal",
                content=content,
                loaded_skills=loaded_skills,
            )

        semantic_routing_enabled = bool(router_config.get("semantic_routing_enabled", True))
        semantic_decision = self._semantic_router.analyze(
            content,
            current_mode=current_mode,
            source_kind=getattr(source, "kind", "") or "",
            sticky_current_mode=bool(router_config.get("sticky_current_mode", True)),
            enable_keyword_fallback=semantic_routing_enabled and bool(router_config.get("fallback_to_heuristic", True)),
        )
        best_mode = semantic_decision.mode
        reason = semantic_decision.reason
        active_skills = semantic_decision.active_skills
        source_profile = semantic_decision.source_profile

        return self.build_route_for_mode(
            best_mode,
            requested_mode=requested_mode,
            reason=reason,
            content=content,
            active_skills=active_skills,
            source_profile=source_profile,
            loaded_skills=loaded_skills,
            confidence=semantic_decision.confidence,
            should_preload_context=semantic_decision.should_preload_context,
            prefer_live_web=semantic_decision.prefer_live_web,
            signals=semantic_decision.signals,
            adapter_name=semantic_decision.adapter_name,
            used_keyword_fallback=semantic_decision.used_keyword_fallback,
        )

    def _default_source_profile_for_mode(self, mode: str, content: str) -> str:
        if mode == "research":
            return self.classify_research_source_profile(content)
        if mode == "study":
            return "study_materials"
        if mode == ASSISTANT_MODE_DANXI:
            return "campus_forum"
        return "workspace_local"
