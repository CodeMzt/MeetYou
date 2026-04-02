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
    title: '模型与推理',
    description: '模型提供商、主模型和默认推理强度。',
  },
  {
    key: 'secrets',
    title: '密钥与令牌',
    description: '敏感字段只显示是否已配置，输入后覆盖保存。',
  },
  {
    key: 'memory',
    title: 'Embedding / Memory',
    description: '向量化、记忆文件和上下文相关配置。',
  },
  {
    key: 'heartbeat',
    title: 'Heartbeat',
    description: '后台心跳模型与节奏控制。',
  },
  {
    key: 'advanced',
    title: '集成与高级',
    description: '网关、飞书、MCP 和其他较少调整的设置。',
  },
]

const KNOWN_FIELDS: Record<string, Omit<ConfigFieldSchema, 'key'>> = {
  api_provider: {
    title: '主模型提供商',
    description: '主对话使用的 provider。',
    group: 'model',
    input: 'select',
    options: PROVIDER_OPTIONS,
  },
  api_url: {
    title: '主模型 API URL',
    description: '主对话请求地址。',
    group: 'model',
    input: 'text',
    placeholder: 'https://api.openai.com/v1/responses',
  },
  model: {
    title: '主模型',
    description: '主对话模型名称。',
    group: 'model',
    input: 'text',
    placeholder: 'gpt-5.4-nano',
  },
  thinking_enabled: {
    title: '默认启用推理',
    description: '未覆盖时的全局 thinking 开关。',
    group: 'model',
    input: 'boolean',
  },
  thinking_effort: {
    title: '默认推理强度',
    description: '未覆盖时的全局 thinking effort。',
    group: 'model',
    input: 'select',
    options: THINKING_OPTIONS,
  },
  thinking_budget_tokens: {
    title: '推理预算',
    description: 'provider 支持时透传的预算 token。',
    group: 'model',
    input: 'number',
  },
  api_key: {
    title: '主模型 API Key',
    description: '主对话使用的密钥。',
    group: 'secrets',
    input: 'password',
  },
  heartbeat_api_key: {
    title: 'Heartbeat API Key',
    description: '后台心跳模型密钥。',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  embedding_api_key: {
    title: 'Embedding API Key',
    description: 'Embedding 请求使用的密钥。',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  feishu_app_id: {
    title: '飞书 App ID',
    description: '飞书集成使用的应用 ID。',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  feishu_app_secret: {
    title: '飞书 App Secret',
    description: '飞书集成使用的应用密钥。',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  notion_token: {
    title: 'Notion Token',
    description: 'Notion MCP 或集成访问令牌。',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  tavily_api_key: {
    title: 'Tavily API Key',
    description: '网页搜索能力依赖的令牌。',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  embedding_api_url: {
    title: 'Embedding API URL',
    description: 'Embedding 服务地址。',
    group: 'memory',
    input: 'text',
  },
  embedding_model: {
    title: 'Embedding 模型',
    description: '向量化使用的模型。',
    group: 'memory',
    input: 'text',
  },
  memory_file_path: {
    title: '记忆文件路径',
    description: '记忆图谱持久化位置。',
    group: 'memory',
    input: 'text',
    advanced: true,
  },
  heartbeat_api_provider: {
    title: 'Heartbeat 提供商',
    description: '后台心跳使用的 provider。',
    group: 'heartbeat',
    input: 'select',
    options: PROVIDER_OPTIONS,
    advanced: true,
  },
  heartbeat_api_url: {
    title: 'Heartbeat API URL',
    description: '后台心跳请求地址。',
    group: 'heartbeat',
    input: 'text',
    advanced: true,
  },
  heart_model: {
    title: 'Heartbeat 模型',
    description: '后台心跳使用的模型。',
    group: 'heartbeat',
    input: 'text',
  },
  heartbeat_interval: {
    title: 'Heartbeat 间隔',
    description: '后台心跳执行间隔，单位秒。',
    group: 'heartbeat',
    input: 'number',
  },
  heartbeat_path: {
    title: 'Heartbeat Prompt 路径',
    description: '后台心跳提示词路径。',
    group: 'heartbeat',
    input: 'text',
    advanced: true,
  },
  enable_feishu_bot: {
    title: '启用飞书机器人',
    description: '开启后会启用飞书长连接接入。',
    group: 'advanced',
    input: 'boolean',
    advanced: true,
  },
  enable_gateway: {
    title: '启用网关',
    description: '当前运行模式下通常保持开启。',
    group: 'advanced',
    input: 'boolean',
    advanced: true,
  },
  gateway_host: {
    title: '网关 Host',
    description: 'HTTP / WebSocket 服务监听地址。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  gateway_port: {
    title: '网关端口',
    description: 'HTTP / WebSocket 服务监听端口。',
    group: 'advanced',
    input: 'number',
    advanced: true,
  },
  feishu_broadcast_chat_ids: {
    title: '飞书广播 Chat ID',
    description: '一行一个 Chat ID。',
    group: 'advanced',
    input: 'list',
    advanced: true,
  },
  feishu_default_chat_id: {
    title: '默认飞书 Chat ID',
    description: '默认推送目标。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  feishu_chat_registry_path: {
    title: '飞书 Chat 注册表路径',
    description: '自动记录 chat_id 的文件位置。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  cmd_policy_path: {
    title: '命令策略路径',
    description: '系统命令审批策略文件路径。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  tools_schema_path: {
    title: '工具 Schema 路径',
    description: '工具描述文件路径。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  soul_path: {
    title: 'Soul Prompt 路径',
    description: '主系统提示词路径。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  start_path: {
    title: 'Start Prompt 路径',
    description: '启动提示词路径。',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  mcp_registry_url: {
    title: 'MCP Registry URL',
    description: 'MCP 服务注册中心地址。',
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
  if (
    key.startsWith('embedding_') ||
    key.startsWith('memory_')
  ) {
    return 'memory'
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
    description: '未在前端预设中的受管配置项。',
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
  }).filter((group) => group.commonFields.length > 0 || group.advancedFields.length > 0)
}
