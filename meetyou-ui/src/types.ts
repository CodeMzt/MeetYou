export type MessageRole = 'user' | 'assistant' | 'system'

export type ConnectionState = 'connecting' | 'connected' | 'disconnected'

export type AssistantMode = 'normal' | 'auto' | 'documents' | 'research' | 'office' | 'study'

export type RuntimeStatus = string

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

export interface RuntimeRequestLengthPolicy {
  provider_family: string
  target_input_tokens: number
  reserved_response_tokens: number
  reserve_ratio: number
}

export interface RuntimeRequestBudget {
  context_limit_tokens: number
  target_input_tokens: number
  reserved_response_tokens: number
  breakdown_total: number
}

export interface RuntimeRequestSnapshot {
  provider_name: string
  model: string
  api_target: {
    host: string
    path: string
  }
  transport_mode: string
  message_count: number
  tool_count: number
  request_tokens_estimated: number
  context_limit_tokens: number
  pressure_ratio: number
  near_limit: boolean
  length_policy: RuntimeRequestLengthPolicy
  budget: RuntimeRequestBudget
  layers: {
    conversation_summary: boolean
    memory_recall: boolean
    session_preload: boolean
    prefer_live_web: boolean
    history_message_count: number
  }
}

export interface RuntimeCompressionSnapshot {
  triggered: boolean
  level: string
  trimmed_messages: number
  before_tokens: number
  after_tokens: number
  usable_tokens: number
  summary_tokens: number
}

export interface RuntimeDebugSnapshot {
  session_id: string
  route: Record<string, unknown>
  route_history: Record<string, unknown>[]
  context_plan: Record<string, unknown>
  memory_scope: Record<string, unknown>
  authorization: Record<string, unknown>
  object_operations: Record<string, unknown>[]
  task_state: Record<string, unknown>
  runtime_state: Record<string, unknown>
  usage: Record<string, unknown>
  request: RuntimeRequestSnapshot | null
  compression: RuntimeCompressionSnapshot | null
  last_failure: RuntimeErrorPayload | null
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
  trimmedActivityCount?: number
  error?: string
}

export interface ConfirmRequestPayload {
  requestId: string
  content: string
  timeout?: number
  defaultDecision?: boolean
}

export interface HumanInputRequestPayload {
  requestId: string
  question: string
  options: string[]
  placeholder?: string
  timeout?: number
}

export interface AckPayload {
  action: string
  accepted: boolean
  session_id: string
  event_id: string
  request_id: string
}

export interface RuntimeErrorPayload {
  code: string
  category: string
  message: string
  retryable: boolean
  details: Record<string, unknown>
  occurred_at: string
}

export interface RuntimeHealthComponent {
  name: string
  status: string
  detail: string
  last_event: string
  updated_at: string
}

export interface RuntimeHealthSnapshot {
  service: string
  version: string
  status: string
  live: boolean
  ready: boolean
  degraded: boolean
  components: RuntimeHealthComponent[]
  errors: RuntimeErrorPayload[]
  updated_at: string
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

export interface UiProtocolSchema {
  http_schema: string
  ws_schema: string
  ws_frame_kinds: string[]
  ws_event_types: string[]
  ws_runtime_resources: string[]
  runtime_statuses: string[]
  providers: ConfigFieldOption[]
  thinking_efforts: ConfigFieldOption[]
  config_groups: ConfigGroupDefinition[]
  config_fields: ConfigFieldSchema[]
}

export interface UiProtocolSchemaEnvelope {
  schema: string
  kind: 'schema'
  ui_schema: UiProtocolSchema
}

export interface RuntimeStateEnvelope {
  schema: string
  kind: 'runtime'
  runtime: {
    resource: 'state'
    session_id: string
    state: {
      global_state: RuntimeStateSnapshot
      heartbeat_state: RuntimeStateSnapshot
      session_state: RuntimeStateSnapshot | null
    }
    metadata?: Record<string, unknown>
    event_id?: string
  }
}

export interface RuntimeUsageEnvelope {
  schema: string
  kind: 'runtime'
  runtime: {
    resource: 'usage'
    session_id: string
    usage: RuntimeUsageSnapshot
    metadata?: Record<string, unknown>
    event_id?: string
  }
}

export interface RuntimeDebugEnvelope {
  schema: string
  kind: 'runtime'
  runtime: {
    resource: 'debug'
    session_id: string
    debug: RuntimeDebugSnapshot
    metadata?: Record<string, unknown>
    event_id?: string
  }
}

export interface HealthEnvelope {
  schema: string
  kind: 'health'
  health: RuntimeHealthSnapshot
}

export interface AckEnvelope {
  schema: string
  kind: 'ack'
  ack: AckPayload
}

export interface ErrorEnvelope {
  schema: string
  kind: 'error'
  error: RuntimeErrorPayload
}
