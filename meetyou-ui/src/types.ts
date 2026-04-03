export type MessageRole = 'user' | 'assistant' | 'system'

export type ConnectionState = 'connecting' | 'connected' | 'disconnected'

export type AssistantMode = 'normal' | 'auto' | 'documents' | 'research' | 'office' | 'study'

export type RuntimeStatus =
  | 'initializing'
  | 'idle'
  | 'thinking'
  | 'tool_calling'
  | 'answering'
  | 'waiting_confirm'
  | 'waiting_human_input'
  | 'heartbeat'
  | 'error'
  | 'shutting_down'

export type ThinkingOverride = 'default' | 'off' | 'low' | 'medium' | 'high'

export interface InputRequestPayload {
  content: string
  session_id?: string
  source_id: string
  client_message_id?: string
  role: MessageRole
  preferred_mode?: AssistantMode
  metadata?: Record<string, unknown>
  options?: {
    thinking?: {
      enabled?: boolean
      effort?: Exclude<ThinkingOverride, 'default' | 'off'>
      budget_tokens?: number
    }
  }
}

export interface RuntimeStateSnapshot {
  session_id: string
  status: RuntimeStatus
  detail: string
  active_tools: string[]
  current_mode: string
  route_reason: string
  action_risk: string
  source_profile: string
  stream_id: string
  turn_id: string
  updated_at: string
}

export interface UsageCounters {
  prompt_tokens: number
  completion_tokens: number
  reasoning_tokens: number
  total_tokens: number
}

export interface SessionUsageTotals extends UsageCounters {
  turn_count: number
}

export interface ContextBreakdown {
  system: number
  history: number
  tool_history: number
  memory_context: number
  policy: number
  current_input: number
  proprioception: number
  total: number
}

export interface RuntimeUsageSnapshot {
  session_id: string
  usage_ready: boolean
  context_limit_tokens: number
  context_limit_source: string
  context_limit_model: string
  context_limit_confidence: string
  current_context_tokens_estimated: number
  context_breakdown: ContextBreakdown
  last_turn_usage: UsageCounters
  session_totals: SessionUsageTotals
  usage_source: string
  updated_at: string
}

export interface TurnActivity {
  id: string
  turnId: string
  streamId: string
  phase: string
  content: string
  activityKind: string
  toolNames: string[]
  metadata: Record<string, unknown>
  createdAt: number
}

export interface ChatTurn {
  id: string
  streamId: string
  turnId: string
  role: MessageRole
  content: string
  reasoning: string
  activities: TurnActivity[]
  isStreaming: boolean
  createdAt: number
  error?: string
}

export interface ConfirmRequestPayload {
  requestId: string
  content: string
  timeout?: number
}

export interface HumanInputRequestPayload {
  requestId: string
  question: string
  options: string[]
  placeholder?: string
  timeout?: number
}

export interface ConfigEntry {
  key: string
  value: unknown
  is_secret: boolean
  has_value: boolean
  source: string
  env_key: string | null
}

export type ConfigGroupKey = 'model' | 'secrets' | 'memory' | 'heartbeat' | 'modes' | 'advanced'

export type ConfigFieldInput = 'text' | 'password' | 'number' | 'boolean' | 'select' | 'list' | 'json'

export interface ConfigFieldOption {
  label: string
  value: string
}

export interface ConfigFieldSchema {
  key: string
  title: string
  description: string
  group: ConfigGroupKey
  input: ConfigFieldInput
  options?: ConfigFieldOption[]
  placeholder?: string
  advanced?: boolean
}

export interface ConfigGroupDefinition {
  key: ConfigGroupKey
  title: string
  description: string
}

export type ConfigFormValue = boolean | string

export interface ResolvedConfigField {
  key: string
  schema: ConfigFieldSchema
  entry: ConfigEntry | null
  value: ConfigFormValue
  dirty: boolean
  error: string | null
}

export interface ConfigFieldGroup {
  key: ConfigGroupKey
  title: string
  description: string
  commonFields: ResolvedConfigField[]
  advancedFields: ResolvedConfigField[]
}

export interface ConfigPatchResult {
  applied_keys: string[]
  reloaded_components: string[]
  restart_required_keys: string[]
  warnings: string[]
}
