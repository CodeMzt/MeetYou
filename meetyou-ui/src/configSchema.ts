import type {
  ConfigEntry,
  ConfigFieldGroup,
  ConfigFieldSchema,
  ConfigGroupDefinition,
  ConfigGroupKey,
  ResolvedConfigField,
} from './types'

const PROVIDER_OPTIONS = [
  { label: 'OpenAI', value: 'openai' },
  { label: 'Anthropic', value: 'anthropic' },
  { label: 'Gemini', value: 'gemini' },
  { label: 'Ollama', value: 'ollama' },
]

const THINKING_OPTIONS = [
  { label: '低', value: 'low' },
  { label: '中', value: 'medium' },
  { label: '高', value: 'high' },
]

export const CONFIG_GROUPS: ConfigGroupDefinition[] = [
  {
    key: 'model',
    title: '模型',
    description: '主模型提供商、模型名称与默认推理设置。',
  },
  {
    key: 'secrets',
    title: '密钥',
    description: 'API Key 与其他敏感集成凭证。',
  },
  {
    key: 'memory',
    title: '记忆',
    description: 'Embedding、记忆持久化与相关配置。',
  },
  {
    key: 'heartbeat',
    title: '心跳',
    description: '后台心跳模型与运行频率控制。',
  },
  {
    key: 'modes',
    title: '模式',
    description: '助手模式路由、可信写入目录与 JSON 配置包。',
  },
  {
    key: 'advanced',
    title: '高级',
    description: 'Gateway、飞书、MCP 等集成配置。',
  },
]

const KNOWN_FIELDS: Record<string, Omit<ConfigFieldSchema, 'key'>> = {
  api_provider: {
    title: '主模型提供商',
    description: '主对话模型使用的服务提供商。',
    group: 'model',
    input: 'select',
    options: PROVIDER_OPTIONS,
  },
  api_url: {
    title: '主模型 API 地址',
    description: '主模型接口使用的基础 URL。',
    group: 'model',
    input: 'text',
    placeholder: 'https://api.openai.com/v1/responses',
  },
  model: {
    title: '主模型名称',
    description: '主对话流程使用的模型名称。',
    group: 'model',
    input: 'text',
    placeholder: 'gpt-5.4',
  },
  thinking_enabled: {
    title: '默认启用推理',
    description: '是否默认开启推理能力。',
    group: 'model',
    input: 'boolean',
  },
  thinking_effort: {
    title: '推理强度',
    description: '模型支持时使用的默认推理强度。',
    group: 'model',
    input: 'select',
    options: THINKING_OPTIONS,
  },
  thinking_budget_tokens: {
    title: '推理预算',
    description: '可选的推理 Token 预算。',
    group: 'model',
    input: 'number',
  },
  api_key: {
    title: '主模型 API Key',
    description: '主模型提供商使用的密钥。',
    group: 'secrets',
    input: 'password',
  },
  heartbeat_api_key: {
    title: '心跳模型 API Key',
    description: '心跳模型提供商使用的密钥。',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  embedding_api_key: {
    title: 'Embedding API Key',
    description: 'Embedding 服务使用的密钥。',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  feishu_app_id: {
    title: '飞书应用 ID',
    description: '飞书应用的 App ID。',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  feishu_app_secret: {
    title: '飞书应用 Secret',
    description: '飞书应用的密钥。',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  notion_token: {
    title: 'Notion Token',
    description: 'Notion 集成或 MCP 使用的令牌。',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  tavily_api_key: {
    title: 'Tavily API Key',
    description: '网页研究能力使用的令牌。',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  embedding_api_url: {
    title: 'Embedding API 地址',
    description: 'Embedding 服务的接口地址。',
    group: 'memory',
    input: 'text',
  },
  embedding_model: {
    title: 'Embedding 模型',
    description: 'Embedding 使用的模型名称。',
    group: 'memory',
    input: 'text',
  },
  memory_file_path: {
    title: '记忆文件路径',
    description: '记忆图持久化文件的保存路径。',
    group: 'memory',
    input: 'text',
    advanced: true,
  },
  heartbeat_api_provider: {
    title: '心跳模型提供商',
    description: '心跳模型使用的服务提供商。',
    group: 'heartbeat',
    input: 'select',
    options: PROVIDER_OPTIONS,
    advanced: true,
  },
  heartbeat_api_url: {
    title: '心跳模型 API 地址',
    description: '心跳模型接口使用的基础 URL。',
    group: 'heartbeat',
    input: 'text',
    advanced: true,
  },
  heart_model: {
    title: '心跳模型名称',
    description: '心跳流程使用的模型名称。',
    group: 'heartbeat',
    input: 'text',
  },
  heartbeat_interval: {
    title: '心跳间隔',
    description: '心跳循环的执行间隔，单位为秒。',
    group: 'heartbeat',
    input: 'number',
  },
  housekeeping_interval: {
    title: '清理间隔',
    description: '记忆清理循环的执行间隔，单位为秒。',
    group: 'heartbeat',
    input: 'number',
    advanced: true,
  },
  scheduler_interval: {
    title: '调度轮询间隔',
    description: '定时任务轮询间隔，单位为秒。',
    group: 'heartbeat',
    input: 'number',
    advanced: true,
  },
  heartbeat_path: {
    title: '心跳提示词路径',
    description: '心跳循环使用的提示词文件路径。',
    group: 'heartbeat',
    input: 'text',
    advanced: true,
  },
  assistant_modes: {
    title: '助手模式配置',
    description: '定义模式、共享基础工具、提示词注册、技能注册与工具包的 JSON 配置。',
    group: 'modes',
    input: 'json',
  },
  mode_router: {
    title: '模式路由配置',
    description: '用于 Brain 决策、会话内切换与启发式回退策略的 JSON 配置。',
    group: 'modes',
    input: 'json',
  },
  trusted_write_roots: {
    title: '可信写入目录',
    description: '无需额外放宽信任边界即可写入本地文档的目录列表。',
    group: 'modes',
    input: 'list',
  },
  source_profiles: {
    title: '信息源配置档',
    description: '研究信息源优先级配置的 JSON 注册表。',
    group: 'modes',
    input: 'json',
  },
  source_catalog_path: {
    title: '信息源目录路径',
    description: '配置驱动的信息源目录 JSON 文件路径。',
    group: 'modes',
    input: 'text',
    placeholder: 'user/source_catalog.json',
  },
  document_parsers: {
    title: '文档解析配置',
    description: '本地文档解析限制与 OCR 能力的 JSON 配置。',
    group: 'modes',
    input: 'json',
  },
  office_integrations: {
    title: 'Office 集成配置',
    description: 'Office 集成能力与仅草稿行为的 JSON 配置。',
    group: 'modes',
    input: 'json',
  },
  research_contact_email: {
    title: '研究联系邮箱',
    description: '部分官方 API 要求提供时使用的联系邮箱或 User-Agent 提示。',
    group: 'advanced',
    input: 'text',
    advanced: true,
    placeholder: 'research@example.com',
  },
  enable_feishu_bot: {
    title: '启用飞书机器人',
    description: '启用飞书长连接输入输出适配器。',
    group: 'advanced',
    input: 'boolean',
    advanced: true,
  },
  enable_gateway: {
    title: '启用 Gateway',
    description: '启用 HTTP 与 WebSocket 网关。',
    group: 'advanced',
    input: 'boolean',
    advanced: true,
  },
  gateway_host: {
    title: 'Gateway 主机地址',
    description: 'Gateway 使用的主机地址。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  gateway_port: {
    title: 'Gateway 端口',
    description: 'Gateway 使用的端口号。',
    group: 'advanced',
    input: 'number',
    advanced: true,
  },
  feishu_broadcast_chat_ids: {
    title: '飞书广播会话 ID',
    description: '每行填写一个会话 ID。',
    group: 'advanced',
    input: 'list',
    advanced: true,
  },
  feishu_default_chat_id: {
    title: '默认飞书会话 ID',
    description: '默认发送消息的飞书会话目标。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  feishu_chat_registry_path: {
    title: '飞书会话注册表路径',
    description: '用于保存已发现会话 ID 的文件路径。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  cmd_policy_path: {
    title: '命令策略路径',
    description: '命令安全策略文件路径。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  tools_schema_path: {
    title: '工具 Schema 路径',
    description: '工具 Schema 文件路径。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  soul_path: {
    title: 'Soul 提示词路径',
    description: '主系统提示词文件路径。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  start_path: {
    title: 'Start 提示词路径',
    description: '启动提示词文件路径。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  mcp_registry_url: {
    title: 'MCP 注册表地址',
    description: 'MCP 注册表的访问地址。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
}

function titleFromKey(key: string): string {
  return key
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function inferGroup(key: string): ConfigGroupKey {
  if (
    key.includes('api_key') ||
    key.includes('token') ||
    key.includes('secret') ||
    key.includes('app_id')
  ) {
    return 'secrets'
  }
  if (key.startsWith('embedding_') || key.startsWith('memory_')) {
    return 'memory'
  }
  if (
    key === 'assistant_modes' ||
    key === 'mode_router' ||
    key === 'trusted_write_roots' ||
    key === 'source_profiles' ||
    key === 'document_parsers' ||
    key === 'office_integrations'
  ) {
    return 'modes'
  }
  if (key.startsWith('heartbeat_') || key.startsWith('heart_')) {
    return 'heartbeat'
  }
  if (
    key.startsWith('gateway_') ||
    key.startsWith('feishu_') ||
    key.startsWith('mcp_') ||
    key.endsWith('_path') ||
    key.startsWith('enable_') ||
    key.includes('policy')
  ) {
    return 'advanced'
  }
  return 'model'
}

function inferInput(key: string, entry: ConfigEntry | null): ConfigFieldSchema['input'] {
  if (entry?.is_secret) {
    return 'password'
  }
  if (Array.isArray(entry?.value)) {
    return 'list'
  }
  if (entry?.value && typeof entry.value === 'object') {
    return 'json'
  }
  if (typeof entry?.value === 'boolean') {
    return 'boolean'
  }
  if (typeof entry?.value === 'number') {
    return 'number'
  }
  if (key === 'thinking_effort') {
    return 'select'
  }
  return 'text'
}

export function getConfigFieldSchema(key: string, entry: ConfigEntry | null): ConfigFieldSchema {
  const known = KNOWN_FIELDS[key]
  if (known) {
    return { key, ...known }
  }

  return {
    key,
    title: titleFromKey(key),
    description: '该配置项暂未提供专用界面描述。',
    group: inferGroup(key),
    input: inferInput(key, entry),
    advanced: true,
  }
}

export function buildConfigGroups(fields: ResolvedConfigField[]): ConfigFieldGroup[] {
  return CONFIG_GROUPS.map((group) => {
    const groupFields = fields.filter((field) => field.schema.group === group.key)
    return {
      key: group.key,
      title: group.title,
      description: group.description,
      commonFields: groupFields.filter((field) => !field.schema.advanced),
      advancedFields: groupFields.filter((field) => field.schema.advanced),
    }
  })
}
