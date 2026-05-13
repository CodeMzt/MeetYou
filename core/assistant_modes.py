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
from core.source_catalog import SourceCatalogManager, normalize_source_profile_name

ASSISTANT_MODE_NORMAL = "general"
ASSISTANT_MODE_GENERAL = ASSISTANT_MODE_NORMAL
ASSISTANT_MODE_AUTO = "auto"
ASSISTANT_MODE_AUTOMATION = "automation"
ASSISTANT_MODE_RESEARCH = "research"
ASSISTANT_MODE_DANXI = "danxi"
ASSISTANT_SPECIALIZED_MODES = (ASSISTANT_MODE_AUTOMATION, ASSISTANT_MODE_RESEARCH, ASSISTANT_MODE_DANXI)
ASSISTANT_MODES = (ASSISTANT_MODE_NORMAL, *ASSISTANT_SPECIALIZED_MODES)
VALID_ASSISTANT_MODES = (ASSISTANT_MODE_AUTO, *ASSISTANT_MODES)

ACTION_RISKS = ("read", "local_write", "external_write", "destructive")
ACTION_RISK_RANK = {name: index for index, name in enumerate(ACTION_RISKS)}

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_PATH_RE = re.compile(
    r"(?i)(?:[a-z]:[\\/][^\s]+|(?:\.{1,2}[\\/]|[\\/])?[^\s]+\.(?:md|txt|pdf|docx|xlsx|pptx|csv|json|py|ts|tsx|js|jsx|html))"
)

_MODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    ASSISTANT_MODE_GENERAL: (
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
        "study",
        "learn",
        "learning",
        "course",
        "exam",
        "quiz",
        "flashcard",
        "mastery",
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
    ASSISTANT_MODE_AUTOMATION: (
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
        "command",
        "shell",
        "terminal",
        "powershell",
        "run command",
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
        "命令",
        "终端",
        "运行命令",
    ),
    ASSISTANT_MODE_RESEARCH: (
        "deep research",
        "research report",
        "literature review",
        "systematic review",
        "papers",
        "citations",
        "evidence ledger",
        "source verification",
        "academic",
        "arxiv",
        "doi",
        "深度研究",
        "研究报告",
        "文献综述",
        "论文",
        "引用",
        "证据",
        "学术",
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
    "academic_biomed": (
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
    "policy_global": (
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
    "finance_macro": (
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
        "label": "工作区与本地知识",
        "description": "优先使用本地文件、项目笔记、记忆和可信私有来源。",
        "primary_domains": [],
        "source_order": ["local", "memory", "notion"],
        "freshness": "workspace",
    },
    "study_materials": {
        "label": "学习资料",
        "description": "优先使用本地学习资料、笔记和用户明确给出的引用。",
        "primary_domains": [],
        "source_order": ["local", "memory", "notion", "academic"],
        "freshness": "coursework",
    },
    "tech_updates": {
        "label": "国际技术",
        "description": "优先使用官方文档、GitHub 发布、标准和供应商变更日志。",
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
    "policy_cn": {
        "label": "国内技术",
        "description": "优先使用中文官方文档、云厂商文档和官方仓库。",
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
    "academic_biomed": {
        "label": "学术资料",
        "description": "优先使用论文、DOI 记录、PubMed 和预印本索引。",
        "primary_domains": [
            "arxiv.org",
            "pubmed.ncbi.nlm.nih.gov",
            "doi.org",
            "crossref.org",
        ],
        "source_order": ["paper", "index", "official", "media"],
        "freshness": "medium",
    },
    "policy_global": {
        "label": "政策与监管",
        "description": "优先使用政府和监管机构资料。",
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
    "finance_macro": {
        "label": "金融资料",
        "description": "优先使用交易所申报、官方投资者关系和监管披露资料。",
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
        "label": "校园论坛",
        "description": "优先使用校园论坛帖子、回复、订阅和私有工作区上下文。",
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
    ASSISTANT_MODE_GENERAL: {
        "tools": [
            "get_sys_vitals",
            "analyze_workspace",
            "read_local_documents",
            "write_local_document",
            "rewrite_local_document",
            "research_topic",
            "create_research_task",
            "manage_research_tasks",
            "manage_projects",
            "manage_project_sources",
            "inspect_page",
            "track_source_updates",
            "compile_report",
            "build_study_plan",
            "extract_learning_points",
            "quiz_me",
            "generate_flashcards",
            "track_mastery",
        ],
        "mcp_servers": ["filesystem_tools"],
    },
    ASSISTANT_MODE_AUTOMATION: {
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
    ASSISTANT_MODE_RESEARCH: {
        "tools": [
            "emit_progress_notice",
            "search_web",
            "read_web_page",
            "research_topic",
            "create_research_task",
            "manage_research_tasks",
            "manage_projects",
            "manage_project_sources",
            "search_academic_sources",
            "inspect_page",
            "compile_report",
            "list_skills",
            "load_skill",
        ],
        "mcp_servers": ["filesystem_tools"],
    },
    ASSISTANT_MODE_DANXI: {
        "tools": [
            "danxi_login",
            "danxi_logout",
            "danxi_get_session_status",
            "danxi_set_webvpn_cookie",
            "danxi_clear_webvpn_cookie",
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
    "exec_core_cmd",
    "get_current_system_time",
    "list_skills",
    "load_skill",
    "create_skill",
    "manage_skill",
    "list_workspaces",
    "switch_workspace",
    "manage_projects",
    "manage_project_sources",
    "list_active_endpoints",
    "list_endpoint_tool_targets",
    "list_delivery_targets",
    "set_delivery_preference",
    "send_delivery_message",
    "create_scheduled_workflow",
    "manage_scheduled_workflows",
    "create_scheduled_delivery",
    "manage_scheduled_deliveries",
    "send_endpoint_message",
    "emit_progress_notice",
    "restart_core",
    "search_knowledge",
    "search_memory",
    "search_web",
    "read_web_page",
    "search_academic_sources",
    "create_research_task",
    "manage_research_tasks",
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
    "default_mode": ASSISTANT_MODE_GENERAL,
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
        "Choose the smallest public mode that matches the user's next immediate step.\n"
        "Modes:\n"
        "- general: ordinary conversation, local/workspace work, lightweight web/page reading, study help, and private knowledge lookup\n"
        "- automation: schedules, meeting briefs, drafts, notes sync, endpoint messaging, action items, and coordination artifacts\n"
        "- research: deep research reports, literature reviews, citation-heavy investigation, artifact-producing research, and evidence ledgers\n"
        "- danxi: FDU campus-forum browsing, thread search, favorites or subscriptions, messages, and normal-user post or reply actions through the Danxi tool suite\n"
        "Shared basic tools across modes include search_knowledge, search_memory, search_web, read_web_page, remember_knowledge, manage_memories, list_workspaces, switch_workspace, ask_human, emit_progress_notice, and get_current_system_time.\n"
        "Before any potentially time-consuming tool work such as web/page reading, research, local file or workspace operations, endpoint tool calls, or endpoint messaging, call emit_progress_notice first with a short status update.\n"
        "Task-style reminders can also activate the task_recognition skill to expose manage_tasks for user TODOs, create_scheduled_workflow/manage_scheduled_workflows for ordinary recurring work, create_scheduled_delivery/manage_scheduled_deliveries only when the output must be delivered to an endpoint address, and manage_scheduled_jobs only for advanced Scheduler maintenance.\n"
        "Legacy documents/study requests remain in general and should use skills/tools; explicit research requests should use research mode."
    ),
    "general": (
        "[General Mode]\n"
        "You are operating as a general daily assistant.\n"
        "Handle ordinary conversation, lightweight planning, private knowledge lookup, and basic web search or direct page reading without escalating too early.\n"
        "Start with the shared basic tools in this mode: search_knowledge, search_memory, search_web, read_web_page, remember_knowledge, manage_memories, list_workspaces, switch_workspace, ask_human, emit_progress_notice, and get_current_system_time.\n"
        "Before any potentially time-consuming tool work such as web/page reading, research, local file or workspace operations, endpoint tool calls, or endpoint messaging, call emit_progress_notice first with a short status update.\n"
        "When the user's message clearly contains user TODO, reminder, or recurring-work intent, the task_recognition skill can activate manage_tasks, create_scheduled_workflow, or manage_scheduled_workflows; use scheduled-delivery tools only when endpoint delivery is part of the request, and reserve manage_scheduled_jobs for advanced Scheduler maintenance.\n"
        "Stay in general mode unless the next immediate step clearly requires automation coordination or Danxi forum tools."
    ),
    "automation": (
        "[Automation Mode]\n"
        "You are operating as an automation and coordination specialist.\n"
        "Favor schedules, drafts, task state, meeting notes, and note synchronization.\n"
        "Start with the shared basic tools for knowledge lookup, memory lookup, and lightweight page reading before assuming an external system already acted. Call emit_progress_notice before page reads, endpoint messaging, endpoint tool calls, or other slow I/O, then use automation-specific tools when coordination artifacts must be produced.\n"
        "Task-style requests can also activate the task_recognition skill so user TODO, scheduled workflow, and scheduled delivery tools stay available inside automation workflows.\n"
        "External side effects stay draft-first. Do not pretend that a message or calendar entry has been sent unless the tool confirms it."
    ),
    "danxi": (
        "[Danxi Mode]\n"
        "You are operating as a Danxi campus-forum specialist.\n"
        "Use Danxi tools only in this mode to browse forum content, search threads or floors, manage subscriptions or favorites, and perform normal-user post or reply operations.\n"
        "Prefer safe, low-frequency actions that match ordinary user behavior. Ask for confirmation before destructive actions such as deleting a post or reply.\n"
        "Keep all forum-side claims grounded in the returned Danxi API data, and use summarize_text, organize_notes, or extract_action_items to turn fetched thread data into concise deliverables."
    ),
    "research": (
        "[Research Mode]\n"
        "You are operating as a deep research assistant. Treat the first research-mode user message in the current thread as the topic, create or refine an editable Chinese plan in chat, and ask the user to confirm or modify it before long-running execution.\n"
        "Use create_research_task/manage_research_tasks for thread-bound task state, progress, and artifacts. Let the external research adapter handle ordinary web/academic discovery; use targeted search/read tools only for explicit checks.\n"
        "Every substantive claim in the final report must map to an evidence source. Do not fabricate progress steps; surface real Core/adapter status, events, source counts, errors, and artifact links."
    ),
}

_SKILL_PROMPT_FALLBACKS = {
    "task-recognition": (
        "[Task Recognition Skill]\n"
        "Detect when the user is creating, listing, updating, blocking, rescheduling, or completing actionable tasks.\n"
        "Use manage_tasks for user TODOs. Use create_scheduled_workflow for ordinary reminders or recurring assistant work, manage_scheduled_workflows for follow-up maintenance, create_scheduled_delivery only when the scheduled output must be delivered to an EndpointAddress, and manage_scheduled_jobs only for advanced Scheduler/system.heartbeat inspection."
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
    "mode-research": (
        "[Research Mode Skill]\n"
        "Operate as a deep-research workflow specialist.\n"
        "Plan first, gather only read-only evidence from web, academic, and project sources, then produce cited artifact-backed reports.\n"
        "Keep long reports in artifacts and keep final chat replies short."
    ),
}

_DEFAULT_PROMPT_REGISTRY = {
    "auto-router": {"path": "prompt/modes/auto-router", "kind": "mode", "fallback": _MODE_PROMPT_FALLBACKS["auto-router"]},
    "mode:general": {"path": "prompt/modes/general", "kind": "mode", "fallback": _MODE_PROMPT_FALLBACKS["general"]},
    "mode:automation": {"path": "prompt/modes/automation", "kind": "mode", "fallback": _MODE_PROMPT_FALLBACKS["automation"]},
    "mode:research": {"path": "prompt/modes/research", "kind": "mode", "fallback": _MODE_PROMPT_FALLBACKS["research"]},
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
    "skill:mode-research": {
        "path": "prompt/SKILL/mode-research",
        "kind": "skill",
        "fallback": _SKILL_PROMPT_FALLBACKS["mode-research"],
    },
}

_DEFAULT_SKILL_REGISTRY = {
    "task_recognition": {
        "prompts": ["skill:task-recognition"],
        "tools": ["manage_tasks", "create_scheduled_workflow", "manage_scheduled_workflows", "create_scheduled_delivery", "manage_scheduled_deliveries", "manage_scheduled_jobs"],
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
    "mode:research": {
        "prompts": ["skill:mode-research"],
        "tools": [],
        "mcp_servers": [],
    },
}

_DEFAULT_SCENE_DEFINITIONS = {
    "knowledge_synthesis": {
        "title": "知识综合",
        "summary": "轻量总结、重组笔记与提炼行动项。",
        "applicable_modes": [ASSISTANT_MODE_GENERAL, ASSISTANT_MODE_AUTOMATION, ASSISTANT_MODE_DANXI],
        "skills": ["knowledge_synthesis"],
        "tools": ["summarize_text", "organize_notes", "extract_action_items"],
        "mcp_servers": [],
        "fallback_tools": ["summarize_text", "organize_notes"],
        "activation_keywords": ["summary", "outline", "整理", "提炼", "摘要", "结构化"],
    },
    "workspace_delivery": {
        "title": "工作区交付",
        "summary": "处理工作区读取、报告整理与结构化交付。",
        "applicable_modes": [ASSISTANT_MODE_GENERAL, ASSISTANT_MODE_AUTOMATION],
        "skills": ["knowledge_synthesis"],
        "tools": ["analyze_workspace", "read_local_documents", "compile_report", "organize_notes"],
        "mcp_servers": ["filesystem_tools"],
        "fallback_tools": ["analyze_workspace", "read_local_documents", "compile_report"],
        "activation_keywords": ["workspace", "repo", "目录", "工作区", "项目结构"],
    },
    "research_synthesis": {
        "title": "研究综合",
        "summary": "科研、资料核验与来源追踪。",
        "applicable_modes": [ASSISTANT_MODE_GENERAL, ASSISTANT_MODE_RESEARCH],
        "skills": ["research_grounding", "knowledge_synthesis"],
        "tools": ["research_topic", "inspect_page", "track_source_updates", "summarize_text"],
        "mcp_servers": ["tavily_web", "browser_automation"],
        "fallback_tools": ["research_topic", "inspect_page", "track_source_updates", "summarize_text"],
        "activation_keywords": ["citation", "evidence", "policy", "research", "引用", "证据", "核验"],
        "authorization": {"read_only": True},
    },
    "office_coordination": {
        "title": "办公协作",
        "summary": "办公整理、会议纪要、跟进事项与沟通草稿。",
        "applicable_modes": [ASSISTANT_MODE_AUTOMATION],
        "skills": ["office_coordination", "task_recognition"],
        "tools": ["meeting_brief", "draft_message", "sync_notes", "organize_notes", "extract_action_items"],
        "mcp_servers": ["filesystem_tools", "notion_knowledge"],
        "fallback_tools": ["meeting_brief", "draft_message", "organize_notes", "extract_action_items"],
        "activation_keywords": ["meeting", "agenda", "minutes", "纪要", "同步", "消息"],
    },
    "study_guidance": {
        "title": "学习指导",
        "summary": "学习计划、知识提炼与复盘练习。",
        "applicable_modes": [ASSISTANT_MODE_GENERAL],
        "skills": ["study_coaching", "knowledge_synthesis"],
        "tools": ["build_study_plan", "extract_learning_points", "quiz_me", "generate_flashcards", "summarize_text"],
        "mcp_servers": ["filesystem_tools"],
        "fallback_tools": ["build_study_plan", "extract_learning_points", "summarize_text"],
        "activation_keywords": ["study", "quiz", "flashcard", "学习", "复习", "知识点"],
    },
    "hotspot_tracking": {
        "title": "热点追踪",
        "summary": "热点事件追踪、多源比对与摘要输出。",
        "applicable_modes": [ASSISTANT_MODE_GENERAL, ASSISTANT_MODE_RESEARCH],
        "skills": ["hotspot_tracking", "research_grounding"],
        "tools": ["research_topic", "inspect_page", "track_source_updates", "summarize_text"],
        "mcp_servers": ["tavily_web", "browser_automation"],
        "fallback_tools": ["research_topic", "inspect_page", "track_source_updates", "summarize_text"],
        "activation_keywords": ["hotspot", "trending", "breaking", "热点", "时政热点", "热搜", "舆情"],
        "authorization": {"read_only": True},
    },
    "danxi_forum_ops": {
        "title": "旦夕论坛操作",
        "summary": "校内论坛浏览、信息整理与低风险普通用户操作。",
        "applicable_modes": [ASSISTANT_MODE_DANXI],
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
        "title": "文件系统工具",
        "summary": "访问本地文件、目录与工作区元数据。",
        "scenarios": ["文档", "工作区", "办公同步", "学习资料"],
        "risk_level": "read",
        "auth_env": [],
        "fallback_tools": ["analyze_workspace", "read_local_documents"],
        "enabled_by_default": True,
        "boundary": "endpoint_local_mcp",
        "managed_by": "desktop_or_edge_endpoint_provider",
        "classification_reason": "本地文件、工作区与终端邻接能力由 Desktop / Edge Endpoint Provider 作为 tool 托管，不收口到 Core MCP。",
    },
    "tavily_web": {
        "title": "Tavily 网页搜索",
        "summary": "为外部网页搜索与抽取提供更强的在线检索能力。",
        "scenarios": ["研究", "新闻", "热点追踪"],
        "risk_level": "read",
        "auth_env": ["TAVILY_API_KEY"],
        "fallback_tools": ["search_web", "read_web_page", "research_topic"],
        "enabled_by_default": False,
        "boundary": "core_mcp",
        "managed_by": "core",
        "classification_reason": "服务端可安全托管的外部检索能力，应优先通过 Core MCP 暴露。",
    },
    "browser_automation": {
        "title": "浏览器自动化",
        "summary": "浏览器导航与页面快照能力，用于复杂网页观察。",
        "scenarios": ["研究", "检查", "热点追踪"],
        "risk_level": "read",
        "auth_env": [],
        "fallback_tools": ["inspect_page", "read_web_page"],
        "enabled_by_default": False,
        "boundary": "core_mcp",
        "managed_by": "core",
        "classification_reason": "非端侧网页观察能力可在服务端沙箱内运行，属于 Core MCP 收口范围。",
    },
    "notion_knowledge": {
        "title": "Notion 知识库",
        "summary": "私有 Notion 知识库读取与检索。",
        "scenarios": ["办公", "知识库", "工作区记忆"],
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
    "endpoint_local_mcp": {
        "criteria": [
            "能力直接触达本地文件系统、终端或工作区运行时。",
            "能力需要随端侧会话、权限与本地 MCP 生命周期一起托管。",
        ],
        "decision": "继续留在 Desktop / Edge Endpoint Provider，不纳入 Core MCP。",
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
        "tool_name": "manage_scheduled_jobs",
        "category": "core_state",
        "reason": "高级维护 V4 SchedulerService / scheduled_jobs，不是普通提醒首选。",
    },
    {
        "tool_name": "create_scheduled_workflow",
        "category": "core_state",
        "reason": "创建可扩展 V4 Scheduled Workflow，消息投递只是可选输出。",
    },
    {
        "tool_name": "manage_scheduled_workflows",
        "category": "core_state",
        "reason": "管理 V4 scheduled_workflow 任务。",
    },
    {
        "tool_name": "create_scheduled_delivery",
        "category": "core_state",
        "reason": "创建输出为 EndpointAddress 投递的 Scheduled Workflow 便捷任务。",
    },
    {
        "tool_name": "manage_scheduled_deliveries",
        "category": "core_state",
        "reason": "管理带投递输出的 V4 scheduled_workflow 任务。",
    },
]

_DEFAULT_MODE_DEFINITIONS = {
    ASSISTANT_MODE_GENERAL: {
        "prompts": ["mode:general"],
        "mode_skills": ["mode:general"],
        "tools": _DEFAULT_MODE_TOOL_BUNDLES[ASSISTANT_MODE_GENERAL]["tools"],
        "mcp_servers": _DEFAULT_MODE_TOOL_BUNDLES[ASSISTANT_MODE_GENERAL]["mcp_servers"],
        "skills": [],
        "auto_skills": ["task_recognition"],
        "scenes": ["knowledge_synthesis"],
    },
    ASSISTANT_MODE_AUTOMATION: {
        "prompts": ["mode:automation"],
        "mode_skills": ["mode:automation"],
        "tools": _DEFAULT_MODE_TOOL_BUNDLES[ASSISTANT_MODE_AUTOMATION]["tools"],
        "mcp_servers": _DEFAULT_MODE_TOOL_BUNDLES[ASSISTANT_MODE_AUTOMATION]["mcp_servers"],
        "skills": [],
        "auto_skills": ["task_recognition", "office_coordination", "knowledge_synthesis"],
        "scenes": ["office_coordination", "knowledge_synthesis"],
    },
    ASSISTANT_MODE_RESEARCH: {
        "prompts": ["mode:research"],
        "mode_skills": ["mode:research"],
        "tools": _DEFAULT_MODE_TOOL_BUNDLES[ASSISTANT_MODE_RESEARCH]["tools"],
        "mcp_servers": _DEFAULT_MODE_TOOL_BUNDLES[ASSISTANT_MODE_RESEARCH]["mcp_servers"],
        "skills": ["research_grounding"],
        "auto_skills": ["knowledge_synthesis", "hotspot_tracking"],
        "scenes": ["research_synthesis"],
        "authorization": {"read_only": True},
    },
    ASSISTANT_MODE_DANXI: {
        "prompts": ["mode:danxi"],
        "mode_skills": ["mode:danxi"],
        "tools": _DEFAULT_MODE_TOOL_BUNDLES[ASSISTANT_MODE_DANXI]["tools"],
        "mcp_servers": _DEFAULT_MODE_TOOL_BUNDLES[ASSISTANT_MODE_DANXI]["mcp_servers"],
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


def get_default_assistant_capability_tools(*, include_basic: bool = True) -> list[str]:
    tools: list[Any] = []
    if include_basic:
        tools.extend(_DEFAULT_BASIC_MODE_TOOLS)
    for mode in ASSISTANT_MODES:
        bundle = _DEFAULT_MODE_TOOL_BUNDLES.get(mode, {})
        tools.extend(bundle.get("tools", []))
    for skill in _DEFAULT_SKILL_REGISTRY.values():
        if isinstance(skill, dict):
            tools.extend(skill.get("tools", []))
            tools.extend(skill.get("fallback_tools", []))
    for scene in _DEFAULT_SCENE_DEFINITIONS.values():
        if isinstance(scene, dict):
            tools.extend(scene.get("tools", []))
            tools.extend(scene.get("fallback_tools", []))
    return _unique_strings(tools)


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
            skill_dir=str(assistant_modes_config.get("skill_prompt_dir") or "prompt/SKILL"),
            created_skill_dir=str(assistant_modes_config.get("created_skill_dir") or "user/skills"),
        )
        self._capability_registry = CapabilityRegistry(self._mode_registry(), self._skill_registry)
        self._prompt_assembler = PromptAssembler(self._capability_registry)

    def _mode_registry(self) -> dict[str, Any]:
        return _deep_merge(
            {
                "enabled_modes": list(ASSISTANT_MODES),
                "prompt_dir": "prompt/modes",
                "skill_prompt_dir": "prompt/SKILL",
                "created_skill_dir": "user/skills",
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
        return self._source_catalog.get_source_profile(profile_name)

    def get_sources_for_profile(
        self,
        profile_name: str,
        *,
        official_only: bool | None = None,
    ) -> list[dict[str, Any]]:
        return self._source_catalog.get_sources(
            normalize_source_profile_name(profile_name, fallback="tech_updates"),
            official_only=official_only,
        )

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
        normalized_context = dict(route_context or {})
        normalized_context["current_mode"] = _normalize_mode(
            normalized_context.get("current_mode") or ASSISTANT_MODE_NORMAL,
            fallback=ASSISTANT_MODE_NORMAL,
        )
        return self._prompt_assembler.assemble_for_route(normalized_context)

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
        client_managed_mcp_servers: list[dict[str, Any]] = []
        for item in diagnostics.get("mcp_servers", []):
            payload = dict(item or {})
            if str(payload.get("boundary") or "core_mcp").strip() in {"endpoint_local_mcp"}:
                client_managed_mcp_servers.append(payload)
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
            "client_managed_mcp_servers": client_managed_mcp_servers,
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
                "client_managed_server_count": len(client_managed_mcp_servers),
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
        overwrite: bool = False,
        source: str = "client",
    ) -> dict[str, Any]:
        return self._skill_registry.create_skill(
            skill_id=skill_id,
            title=title,
            summary=summary,
            content=content,
            recommended_tools=recommended_tools,
            applicable_modes=applicable_modes,
            scenarios=scenarios,
            overwrite=overwrite,
            source=source,
        )

    def manage_skill(
        self,
        *,
        action: str,
        skill_id: str = "",
        new_skill_id: str = "",
        title: str | None = None,
        summary: str | None = None,
        content: str | None = None,
        recommended_tools: list[str] | None = None,
        applicable_modes: list[str] | None = None,
        scenarios: list[str] | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        return self._skill_registry.manage_skill(
            action=action,
            skill_id=skill_id,
            new_skill_id=new_skill_id,
            title=title,
            summary=summary,
            content=content,
            recommended_tools=recommended_tools,
            applicable_modes=applicable_modes,
            scenarios=scenarios,
            overwrite=overwrite,
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
        classified = normalize_source_profile_name(self._semantic_router.classify_source_profile(text), fallback="")
        if classified:
            return classified
        classified = normalize_source_profile_name(self._source_catalog.classify_research_profile(text), fallback="")
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

        for keyword_mode, keywords in _MODE_KEYWORDS.items():
            mode = _normalize_mode(keyword_mode, fallback=ASSISTANT_MODE_NORMAL)
            if mode not in scores:
                mode = ASSISTANT_MODE_NORMAL
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
                scores[ASSISTANT_MODE_RESEARCH] += 3
                if len(triggers[ASSISTANT_MODE_RESEARCH]) < 4:
                    triggers[ASSISTANT_MODE_RESEARCH].append(keyword)

        if _URL_RE.search(content):
            scores[ASSISTANT_MODE_NORMAL] += 4
            if len(triggers[ASSISTANT_MODE_NORMAL]) < 4:
                triggers[ASSISTANT_MODE_NORMAL].append("direct_url")

        if _PATH_RE.search(content):
            scores[ASSISTANT_MODE_NORMAL] += 4
            if len(triggers[ASSISTANT_MODE_NORMAL]) < 4:
                triggers[ASSISTANT_MODE_NORMAL].append("local_path")

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
                else "No strong routing signal found; defaulting to general for ordinary conversation."
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
                reason="Preferred mode selected: general",
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
        if mode == ASSISTANT_MODE_DANXI:
            return "campus_forum"
        if mode == ASSISTANT_MODE_RESEARCH:
            return self.classify_research_source_profile(content)
        return "workspace_local"

