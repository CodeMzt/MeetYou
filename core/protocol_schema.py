from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.status import RuntimeStatus

HTTP_SCHEMA_NAME = "meetyou.http.v1"
WS_SCHEMA_NAME = "meetyou.ws.v1"

WS_FRAME_KINDS = (
    "connection",
    "event",
    "runtime",
    "ack",
    "error",
    "health",
    "pong",
)

WS_EVENT_TYPES = (
    "message",
    "reasoning",
    "status",
    "control",
    "confirm_request",
    "human_input_request",
    "runtime_status",
    "usage",
    "error",
)

WS_RUNTIME_RESOURCES = ("state", "usage", "debug")

SUPPORTED_PROVIDER_OPTIONS = (
    {"label": "OpenAI", "value": "openai"},
    {"label": "Anthropic", "value": "anthropic"},
    {"label": "Gemini", "value": "gemini"},
    {"label": "Ollama", "value": "ollama"},
)

SUPPORTED_PROVIDER_VALUES = tuple(option["value"] for option in SUPPORTED_PROVIDER_OPTIONS)

OBJECT_STORE_BACKEND_OPTIONS = (
    {"label": "Local Filesystem", "value": "local"},
    {"label": "Filesystem", "value": "filesystem"},
    {"label": "S3 Compatible", "value": "s3_compatible"},
)

THINKING_EFFORT_OPTIONS = (
    {"label": "低", "value": "low"},
    {"label": "中", "value": "medium"},
    {"label": "高", "value": "high"},
)

THINKING_EFFORT_VALUES = tuple(option["value"] for option in THINKING_EFFORT_OPTIONS)

CONFIG_GROUPS = (
    {
        "key": "model",
        "title": "模型",
        "description": "主模型提供商、模型名称与默认推理设置。",
    },
    {
        "key": "secrets",
        "title": "密钥",
        "description": "API Key 与其他敏感集成凭证。",
    },
    {
        "key": "memory",
        "title": "记忆",
        "description": "Embedding、记忆持久化与相关配置。",
    },
    {
        "key": "heartbeat",
        "title": "心跳",
        "description": "后台心跳模型与运行频率控制。",
    },
    {
        "key": "modes",
        "title": "模式",
        "description": "助手模式路由、可信写入目录与 JSON 配置包。",
    },
    {
        "key": "advanced",
        "title": "高级",
        "description": "Gateway、飞书、MCP 等集成配置。",
    },
)

CONFIG_FIELD_SCHEMAS: dict[str, dict[str, Any]] = {
    "api_provider": {
        "title": "主模型提供商",
        "description": "主对话模型使用的服务提供商。",
        "group": "model",
        "input": "select",
        "options": list(SUPPORTED_PROVIDER_OPTIONS),
    },
    "api_url": {
        "title": "主模型 API 地址",
        "description": "主模型接口使用的基础 URL。",
        "group": "model",
        "input": "text",
        "placeholder": "https://api.openai.com/v1/responses",
    },
    "model": {
        "title": "主模型名称",
        "description": "主对话流程使用的模型名称。",
        "group": "model",
        "input": "text",
        "placeholder": "gpt-5.4",
    },
    "thinking_enabled": {
        "title": "默认启用推理",
        "description": "是否默认开启推理能力。",
        "group": "model",
        "input": "boolean",
    },
    "thinking_effort": {
        "title": "推理强度",
        "description": "模型支持时使用的默认推理强度。",
        "group": "model",
        "input": "select",
        "options": list(THINKING_EFFORT_OPTIONS),
    },
    "thinking_budget_tokens": {
        "title": "推理预算",
        "description": "可选的推理 Token 预算。",
        "group": "model",
        "input": "number",
    },
    "api_key": {
        "title": "主模型 API Key",
        "description": "主模型提供商使用的密钥。",
        "group": "secrets",
        "input": "password",
    },
    "heartbeat_api_key": {
        "title": "心跳模型 API Key",
        "description": "心跳模型提供商使用的密钥。",
        "group": "secrets",
        "input": "password",
        "advanced": True,
    },
    "embedding_api_key": {
        "title": "Embedding API Key",
        "description": "Embedding 服务使用的密钥。",
        "group": "secrets",
        "input": "password",
        "advanced": True,
    },
    "agent_access_token": {
        "title": "Agent 访问令牌",
        "description": "Desktop Agent 与 Edge Agent 连接 Core 时使用的令牌。",
        "group": "secrets",
        "input": "password",
        "advanced": True,
    },
    "database_url": {
        "title": "数据库连接串",
        "description": "Core Service 使用的 PostgreSQL 连接串。",
        "group": "secrets",
        "input": "password",
        "advanced": True,
    },
    "gateway_access_token": {
        "title": "Gateway 访问令牌",
        "description": "HTTP 与 WebSocket 访问统一使用的受保护令牌。",
        "group": "secrets",
        "input": "password",
        "advanced": True,
    },
    "object_store_backend": {
        "title": "对象存储后端",
        "description": "附件内容存储使用的后端实现。当前支持 local/filesystem。",
        "group": "advanced",
        "input": "select",
        "options": list(OBJECT_STORE_BACKEND_OPTIONS),
        "advanced": True,
    },
    "attachment_storage_root": {
        "title": "附件本地存储目录",
        "description": "local/filesystem 后端保存附件内容的根目录。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
        "placeholder": "user/attachments",
    },
    "object_store_endpoint": {
        "title": "对象存储 Endpoint",
        "description": "为后续 MinIO/S3 接入预留的 endpoint 配置。当前仅做占位。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
        "placeholder": "https://minio.example.com",
    },
    "object_store_bucket": {
        "title": "对象存储 Bucket",
        "description": "为后续 MinIO/S3 接入预留的 bucket 配置。当前仅做占位。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
        "placeholder": "meetyou-attachments",
    },
    "object_store_region": {
        "title": "对象存储 Region",
        "description": "S3 / MinIO 后端使用的 region。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
        "placeholder": "us-east-1",
    },
    "object_store_access_key": {
        "title": "对象存储 Access Key",
        "description": "S3 / MinIO 后端使用的 access key。",
        "group": "secrets",
        "input": "password",
        "advanced": True,
    },
    "object_store_secret_key": {
        "title": "对象存储 Secret Key",
        "description": "S3 / MinIO 后端使用的 secret key。",
        "group": "secrets",
        "input": "password",
        "advanced": True,
    },
    "feishu_app_id": {
        "title": "飞书应用 ID",
        "description": "飞书应用的 App ID。",
        "group": "secrets",
        "input": "password",
        "advanced": True,
    },
    "feishu_app_secret": {
        "title": "飞书应用 Secret",
        "description": "飞书应用的密钥。",
        "group": "secrets",
        "input": "password",
        "advanced": True,
    },
    "notion_token": {
        "title": "Notion Token",
        "description": "Notion 集成或 MCP 使用的令牌。",
        "group": "secrets",
        "input": "password",
        "advanced": True,
    },
    "tavily_api_key": {
        "title": "Tavily API Key",
        "description": "网页研究能力使用的令牌。",
        "group": "secrets",
        "input": "password",
        "advanced": True,
    },
    "embedding_api_url": {
        "title": "Embedding API 地址",
        "description": "Embedding 服务的接口地址。",
        "group": "memory",
        "input": "text",
    },
    "embedding_model": {
        "title": "Embedding 模型",
        "description": "Embedding 使用的模型名称。",
        "group": "memory",
        "input": "text",
    },
    "memory_file_path": {
        "title": "记忆文件路径",
        "description": "记忆图持久化文件的保存路径。",
        "group": "memory",
        "input": "text",
        "advanced": True,
    },
    "task_file_path": {
        "title": "任务文件路径",
        "description": "任务与调度状态持久化文件的保存路径。",
        "group": "memory",
        "input": "text",
        "advanced": True,
        "placeholder": "user/memory_tasks.json",
    },
    "heartbeat_api_provider": {
        "title": "心跳模型提供商",
        "description": "心跳模型使用的服务提供商。",
        "group": "heartbeat",
        "input": "select",
        "options": list(SUPPORTED_PROVIDER_OPTIONS),
        "advanced": True,
    },
    "heartbeat_api_url": {
        "title": "心跳模型 API 地址",
        "description": "心跳模型接口使用的基础 URL。",
        "group": "heartbeat",
        "input": "text",
        "advanced": True,
    },
    "heart_model": {
        "title": "心跳模型名称",
        "description": "心跳流程使用的模型名称。",
        "group": "heartbeat",
        "input": "text",
    },
    "heartbeat_interval": {
        "title": "心跳间隔",
        "description": "心跳循环的执行间隔，单位为秒。",
        "group": "heartbeat",
        "input": "number",
    },
    "housekeeping_interval": {
        "title": "清理间隔",
        "description": "记忆清理循环的执行间隔，单位为秒。",
        "group": "heartbeat",
        "input": "number",
        "advanced": True,
    },
    "scheduler_interval": {
        "title": "调度轮询间隔",
        "description": "定时任务轮询间隔，单位为秒。",
        "group": "heartbeat",
        "input": "number",
        "advanced": True,
    },
    "heartbeat_path": {
        "title": "心跳提示词路径",
        "description": "心跳循环使用的提示词文件路径。",
        "group": "heartbeat",
        "input": "text",
        "advanced": True,
    },
    "assistant_modes": {
        "title": "助手模式配置",
        "description": "定义模式、共享基础工具、提示词注册、技能注册与工具包的 JSON 配置。",
        "group": "modes",
        "input": "json",
    },
    "mode_router": {
        "title": "模式路由配置",
        "description": "用于 Brain 决策、会话内切换与启发式回退策略的 JSON 配置。",
        "group": "modes",
        "input": "json",
    },
    "trusted_write_roots": {
        "title": "可信写入目录",
        "description": "无需额外放宽信任边界即可写入本地文档的目录列表。",
        "group": "modes",
        "input": "list",
    },
    "source_catalog_path": {
        "title": "信息源目录路径",
        "description": "配置驱动的信息源目录 JSON 文件路径。",
        "group": "modes",
        "input": "text",
        "placeholder": "user/source_catalog.json",
    },
    "document_parsers": {
        "title": "文档解析配置",
        "description": "本地文档解析限制与 OCR 能力的 JSON 配置。",
        "group": "modes",
        "input": "json",
    },
    "office_integrations": {
        "title": "Office 集成配置",
        "description": "Office 集成能力与仅草稿行为的 JSON 配置。",
        "group": "modes",
        "input": "json",
    },
    "research_contact_email": {
        "title": "研究联系邮箱",
        "description": "部分官方 API 要求提供时使用的联系邮箱或 User-Agent 提示。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
        "placeholder": "research@example.com",
    },
    "enable_feishu_bot": {
        "title": "启用飞书机器人",
        "description": "启用飞书长连接输入输出适配器。",
        "group": "advanced",
        "input": "boolean",
        "advanced": True,
    },
    "gateway_host": {
        "title": "Gateway 主机地址",
        "description": "Gateway 使用的主机地址。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
    },
    "gateway_port": {
        "title": "Gateway 端口",
        "description": "Gateway 使用的端口号。",
        "group": "advanced",
        "input": "number",
        "advanced": True,
    },
    "gateway_cors_origins": {
        "title": "Gateway 允许来源",
        "description": "允许访问 Gateway 的额外浏览器来源列表。",
        "group": "advanced",
        "input": "list",
        "advanced": True,
    },
    "feishu_broadcast_chat_ids": {
        "title": "飞书广播会话 ID",
        "description": "每行填写一个会话 ID。",
        "group": "advanced",
        "input": "list",
        "advanced": True,
    },
    "feishu_default_chat_id": {
        "title": "默认飞书会话 ID",
        "description": "默认发送消息的飞书会话目标。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
    },
    "feishu_chat_registry_path": {
        "title": "飞书会话注册表路径",
        "description": "用于保存已发现会话 ID 的文件路径。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
    },
    "cmd_policy_path": {
        "title": "命令策略路径",
        "description": "命令安全策略文件路径。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
    },
    "tools_schema_path": {
        "title": "工具 Schema 路径",
        "description": "工具 Schema 文件路径。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
    },
    "soul_path": {
        "title": "Soul 提示词路径",
        "description": "主系统提示词文件路径。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
    },
    "start_path": {
        "title": "Start 提示词路径",
        "description": "启动提示词文件路径。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
    },
    "mcp_registry_url": {
        "title": "MCP 注册表地址",
        "description": "MCP 注册表的访问地址。",
        "group": "advanced",
        "input": "text",
        "advanced": True,
    },
}

CONFIG_FIELD_KEYS = tuple(CONFIG_FIELD_SCHEMAS.keys())
RUNTIME_STATUS_VALUES = tuple(status.value for status in RuntimeStatus)


def build_ui_protocol_schema() -> dict[str, Any]:
    return {
        "http_schema": HTTP_SCHEMA_NAME,
        "ws_schema": WS_SCHEMA_NAME,
        "ws_frame_kinds": list(WS_FRAME_KINDS),
        "ws_event_types": list(WS_EVENT_TYPES),
        "ws_runtime_resources": list(WS_RUNTIME_RESOURCES),
        "runtime_statuses": list(RUNTIME_STATUS_VALUES),
        "providers": deepcopy(list(SUPPORTED_PROVIDER_OPTIONS)),
        "thinking_efforts": deepcopy(list(THINKING_EFFORT_OPTIONS)),
        "config_groups": deepcopy(list(CONFIG_GROUPS)),
        "config_fields": [
            {"key": key, **deepcopy(value)}
            for key, value in CONFIG_FIELD_SCHEMAS.items()
        ],
    }
