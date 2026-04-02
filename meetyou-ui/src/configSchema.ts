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
  { label: 'Low', value: 'low' },
  { label: 'Medium', value: 'medium' },
  { label: 'High', value: 'high' },
]

export const CONFIG_GROUPS: ConfigGroupDefinition[] = [
  {
    key: 'model',
    title: 'Model',
    description: 'Main provider, model, and default reasoning settings.',
  },
  {
    key: 'secrets',
    title: 'Secrets',
    description: 'API keys and sensitive integration tokens.',
  },
  {
    key: 'memory',
    title: 'Memory',
    description: 'Embedding, memory persistence, and related settings.',
  },
  {
    key: 'heartbeat',
    title: 'Heartbeat',
    description: 'Background heartbeat model and cadence controls.',
  },
  {
    key: 'modes',
    title: 'Modes',
    description: 'Assistant mode routing, trusted write roots, and JSON bundles.',
  },
  {
    key: 'advanced',
    title: 'Advanced',
    description: 'Gateway, Feishu, MCP, and other integration settings.',
  },
]

const KNOWN_FIELDS: Record<string, Omit<ConfigFieldSchema, 'key'>> = {
  api_provider: {
    title: 'Main Provider',
    description: 'Provider used for the main conversation model.',
    group: 'model',
    input: 'select',
    options: PROVIDER_OPTIONS,
  },
  api_url: {
    title: 'Main API URL',
    description: 'Base URL for the main model API.',
    group: 'model',
    input: 'text',
    placeholder: 'https://api.openai.com/v1/responses',
  },
  model: {
    title: 'Main Model',
    description: 'Model name used for the main conversation loop.',
    group: 'model',
    input: 'text',
    placeholder: 'gpt-5.4',
  },
  thinking_enabled: {
    title: 'Default Reasoning',
    description: 'Whether reasoning is enabled by default.',
    group: 'model',
    input: 'boolean',
  },
  thinking_effort: {
    title: 'Reasoning Effort',
    description: 'Default reasoning effort when supported.',
    group: 'model',
    input: 'select',
    options: THINKING_OPTIONS,
  },
  thinking_budget_tokens: {
    title: 'Reasoning Budget',
    description: 'Optional token budget for reasoning.',
    group: 'model',
    input: 'number',
  },
  api_key: {
    title: 'Main API Key',
    description: 'Secret for the main model provider.',
    group: 'secrets',
    input: 'password',
  },
  heartbeat_api_key: {
    title: 'Heartbeat API Key',
    description: 'Secret for the heartbeat model provider.',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  embedding_api_key: {
    title: 'Embedding API Key',
    description: 'Secret for the embedding service.',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  feishu_app_id: {
    title: 'Feishu App ID',
    description: 'Feishu application id.',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  feishu_app_secret: {
    title: 'Feishu App Secret',
    description: 'Feishu application secret.',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  notion_token: {
    title: 'Notion Token',
    description: 'Token used by Notion integration or MCP.',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  tavily_api_key: {
    title: 'Tavily API Key',
    description: 'Token used for web research.',
    group: 'secrets',
    input: 'password',
    advanced: true,
  },
  embedding_api_url: {
    title: 'Embedding API URL',
    description: 'Embedding service URL.',
    group: 'memory',
    input: 'text',
  },
  embedding_model: {
    title: 'Embedding Model',
    description: 'Embedding model name.',
    group: 'memory',
    input: 'text',
  },
  memory_file_path: {
    title: 'Memory File Path',
    description: 'Persistence path for the memory graph.',
    group: 'memory',
    input: 'text',
    advanced: true,
  },
  heartbeat_api_provider: {
    title: 'Heartbeat Provider',
    description: 'Provider used by the heartbeat model.',
    group: 'heartbeat',
    input: 'select',
    options: PROVIDER_OPTIONS,
    advanced: true,
  },
  heartbeat_api_url: {
    title: 'Heartbeat API URL',
    description: 'Base URL for the heartbeat model API.',
    group: 'heartbeat',
    input: 'text',
    advanced: true,
  },
  heart_model: {
    title: 'Heartbeat Model',
    description: 'Model name used by heartbeat.',
    group: 'heartbeat',
    input: 'text',
  },
  heartbeat_interval: {
    title: 'Heartbeat Interval',
    description: 'Heartbeat cadence in seconds.',
    group: 'heartbeat',
    input: 'number',
  },
  heartbeat_path: {
    title: 'Heartbeat Prompt Path',
    description: 'Prompt file used by the heartbeat loop.',
    group: 'heartbeat',
    input: 'text',
    advanced: true,
  },
  assistant_modes: {
    title: 'Assistant Modes',
    description: 'JSON bundle describing enabled modes, prompt directory, and tool bundles.',
    group: 'modes',
    input: 'json',
  },
  mode_router: {
    title: 'Mode Router',
    description: 'JSON config for automatic mode routing.',
    group: 'modes',
    input: 'json',
  },
  trusted_write_roots: {
    title: 'Trusted Write Roots',
    description: 'Directories where local document writes are allowed without expanding trust.',
    group: 'modes',
    input: 'list',
  },
  source_profiles: {
    title: 'Source Profiles',
    description: 'JSON registry for research source-priority profiles.',
    group: 'modes',
    input: 'json',
  },
  document_parsers: {
    title: 'Document Parsers',
    description: 'JSON config for local document parsing limits and OCR.',
    group: 'modes',
    input: 'json',
  },
  office_integrations: {
    title: 'Office Integrations',
    description: 'JSON config for office integrations and draft-only behavior.',
    group: 'modes',
    input: 'json',
  },
  enable_feishu_bot: {
    title: 'Enable Feishu Bot',
    description: 'Enable the Feishu long-connection input/output adapter.',
    group: 'advanced',
    input: 'boolean',
    advanced: true,
  },
  enable_gateway: {
    title: 'Enable Gateway',
    description: 'Enable the HTTP and WebSocket gateway.',
    group: 'advanced',
    input: 'boolean',
    advanced: true,
  },
  gateway_host: {
    title: 'Gateway Host',
    description: 'Host address for the gateway.',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  gateway_port: {
    title: 'Gateway Port',
    description: 'Port for the gateway.',
    group: 'advanced',
    input: 'number',
    advanced: true,
  },
  feishu_broadcast_chat_ids: {
    title: 'Feishu Broadcast Chat IDs',
    description: 'One chat id per line.',
    group: 'advanced',
    input: 'list',
    advanced: true,
  },
  feishu_default_chat_id: {
    title: 'Default Feishu Chat ID',
    description: 'Default Feishu chat target.',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  feishu_chat_registry_path: {
    title: 'Feishu Chat Registry Path',
    description: 'File path used to store discovered chat ids.',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  cmd_policy_path: {
    title: 'Command Policy Path',
    description: 'Command safety policy file path.',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  tools_schema_path: {
    title: 'Tools Schema Path',
    description: 'Tool schema file path.',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  soul_path: {
    title: 'Soul Prompt Path',
    description: 'Main system prompt path.',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  start_path: {
    title: 'Start Prompt Path',
    description: 'Boot prompt path.',
    group: 'advanced',
    input: 'text',
    advanced: true,
  },
  mcp_registry_url: {
    title: 'MCP Registry URL',
    description: 'MCP registry URL.',
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
    description: 'Config field not yet given a custom UI schema.',
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
