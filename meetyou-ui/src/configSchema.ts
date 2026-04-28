import type {
  ConfigEntry,
  ConfigFieldGroup,
  ConfigFieldSchema,
  ConfigGroupDefinition,
  ConfigGroupKey,
  ResolvedConfigField,
  UiProtocolSchema,
} from './types'

const DEFAULT_CONFIG_GROUPS: ConfigGroupDefinition[] = [
  {
    key: 'model',
    title: '模型',
    description: '主模型提供商、模型名称与默认推理设置。',
  },
  {
    key: 'secrets',
    title: '密钥',
    description: '接口密钥与其他敏感集成凭证。',
  },
  {
    key: 'memory',
    title: '记忆',
    description: '向量嵌入、记忆持久化与相关配置。',
  },
  {
    key: 'heartbeat',
    title: '心跳',
    description: '后台心跳模型与运行频率控制。',
  },
  {
    key: 'modes',
    title: '模式',
    description: '助手模式路由、可信写入目录与结构化配置包。',
  },
  {
    key: 'advanced',
    title: '高级',
    description: '网关、飞书、MCP 等集成配置。',
  },
]

function getSchemaLookup(uiSchema?: UiProtocolSchema | null): Record<string, ConfigFieldSchema> {
  if (!uiSchema?.config_fields.length) {
    return {}
  }
  return Object.fromEntries(
    uiSchema.config_fields.map((field) => [
      field.key,
      {
        ...field,
        options: field.options ? [...field.options] : [],
      },
    ]),
  )
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

export function getConfigFieldSchema(
  key: string,
  entry: ConfigEntry | null,
  uiSchema?: UiProtocolSchema | null,
): ConfigFieldSchema {
  const known = getSchemaLookup(uiSchema)[key]
  if (known) {
    return { ...known, key }
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

export function buildConfigGroups(
  fields: ResolvedConfigField[],
  uiSchema?: UiProtocolSchema | null,
): ConfigFieldGroup[] {
  const groups = uiSchema?.config_groups?.length ? uiSchema.config_groups : DEFAULT_CONFIG_GROUPS
  return groups.map((group) => {
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
