export type MessageRole = 'user' | 'assistant' | 'system' | 'tool'

export type ConnectionState = 'connecting' | 'connected' | 'disconnected'

export type AssistantMode = 'general' | 'automation' | 'research' | 'danxi'

export type RuntimeStatus = string

export type ThinkingOverride = 'default' | 'off' | 'low' | 'medium' | 'high'

export interface InputRequestPayload {
  content: string
  session_id?: string
  source_id: string
  endpoint_message_id?: string
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

export interface RuntimeWorkspace {
  workspace_id: string
  title: string
  status: string
  base_mode: AssistantMode
  description: string
  prompt_overlay: string
  default_execution_target: string
  tool_policy: string
  allowed_tool_ids: string[]
  preferred_target_endpoint_ids: string[]
  preferred_endpoint_provider_types: string[]
  preferred_source_profiles: string[]
  tool_target_routing_policy: string
  memory_ranking_policy: string
  tool_routing_overrides: Record<string, unknown>
}

export interface WorkspaceTopologyMembership {
  workspace_id: string
  primary: boolean
  role: string
  enabled: boolean
  source: string
}

export interface WorkspaceTopologyWorkspace {
  workspace_id: string
  title: string
  status: string
  base_mode: AssistantMode | string
  description: string
  endpoint_count: number
  online_endpoint_count: number
}

export interface WorkspaceTopologyEndpoint {
  endpoint_id: string
  display_name: string
  endpoint_type: string
  provider_type: string
  transport_type: string
  status: string
  connected: boolean
  connection_count: number
  workspace_ids: string[]
  primary_workspace_id: string
  provider_declared_workspace_ids: string[]
  capability_count: number
  executable_tools: string[]
  labels: string[]
  last_seen_at: string
  core_owned: boolean
  memberships: WorkspaceTopologyMembership[]
}

export interface WorkspaceTopologyAddress {
  address_id: string
  endpoint_id: string
  display_name: string
  provider_type: string
  address_type: string
  status: string
  workspace_ids: string[]
  primary_workspace_id: string
  capabilities: string[]
  memberships: WorkspaceTopologyMembership[]
}

export interface WorkspaceTopology {
  workspaces: WorkspaceTopologyWorkspace[]
  endpoints: WorkspaceTopologyEndpoint[]
  addresses: WorkspaceTopologyAddress[]
}

export interface WorkspaceMembershipMutationResult {
  ok: boolean
  target_type: 'endpoint' | 'address' | string
  target_id: string
  workspace_ids: string[]
  primary_workspace_id: string
}

export interface RuntimeThread {
  thread_id: string
  home_workspace_id: string
  workspace_id: string
  project_id: string
  title: string
  status: string
  summary: string
}

export interface RuntimeProject {
  project_id: string
  workspace_id: string
  title: string
  description: string
  instructions: string
  status: string
  memory_scope: Record<string, unknown>
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface RuntimeProjectSource {
  source_id: string
  project_id: string
  source_type: string
  title: string
  content: string
  content_type: string
  checksum: string
  status: string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface RuntimeThreadBranch {
  branch_id: string
  thread_id: string
  parent_branch_id: string
  title: string
  status: string
  current_leaf_message_id: string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface RuntimeMessageEditRetryResult {
  branch: RuntimeThreadBranch
  message: RuntimeMessage
  replay_status: string
}

export interface RuntimeConversationCheckpoint {
  checkpoint_id: string
  thread_id: string
  branch_id: string
  message_id: string
  checkpoint_type: string
  title: string
  state: Record<string, unknown>
  status: string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface RuntimeArtifact {
  artifact_id: string
  project_id: string
  thread_id: string
  artifact_type: string
  filename: string
  content_type: string
  byte_size: number
  checksum: string
  status: string
  download_url: string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface RuntimeResearchTask {
  research_task_id: string
  project_id: string
  thread_id: string
  artifact_id: string
  topic: string
  status: string
  plan: Record<string, unknown>
  source_policy: Record<string, unknown>
  evidence_ledger: Array<Record<string, unknown>>
  output_format: string
  summary: string
  artifact: RuntimeArtifact | null
  derived_artifacts?: RuntimeArtifact[]
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface RuntimeThreadDeleteResult {
  ok: boolean
  thread_id: string
  deleted: boolean
  status: string
  reason: string
  default_thread: boolean
}

export interface RuntimeSession {
  session_id: string
  thread_id: string
  active_workspace_id: string
  workspace_id: string
  endpoint_id: string
  status: string
}

export interface RuntimeOperation {
  operation_id: string
  thread_id: string
  workspace_id: string
  title: string
  operation_type: string
  execution_target: string
  target_endpoint_id: string
  tool_key: string
  tool_id: string
  status: string
  approval_id?: string
  approval_status?: string
  approval_required?: boolean
  routing_reason?: string
}

export type OperationStatusTone = 'pending' | 'running' | 'success' | 'failed'

export interface OperationView extends RuntimeOperation {
  call_id: string
  phase: string
  detail: string
  result: Record<string, unknown>
  error: Record<string, unknown>
  tone: OperationStatusTone
  summary: string
  isBlocking: boolean
}

export interface AvailableEndpoint {
  endpoint_id: string
  endpoint_type: string
  provider_type: string
  display_name: string
  transport_profile: string
  status: string
  workspace_ids: string[]
  available_tools: string[]
  executable_tools: string[]
  membership_role: string
  enabled: boolean
}

export interface OperatorSourceProfile {
  profile_name: string
  label: string
  description: string
  official_only: boolean
  default_freshness: string
}

export interface DanxiSessionStatus {
  session_key: string
  email: string
  transport: string
  webvpn_enabled: boolean
  has_webvpn_cookie: boolean
  webvpn_required: boolean
  direct_connect_available: boolean
  logged_in: boolean
  connection_error?: string | null
  user_profile: Record<string, unknown> | null
}

export interface DanxiListResponse<T = Record<string, unknown>> {
  count: number
  items: T[]
  scope?: string
  hole_id?: number
  offset?: number | string
  size?: number
  start_time?: string
  next_offset?: number | string
  next_start_time?: string
  has_more?: boolean
  include_all?: boolean
  order?: string
  cursor_field?: string
}

export interface DanxiPostResponse {
  hole: Record<string, unknown>
}

export interface DanxiSearchResponse {
  query: string
  floor_hits: number
  hole_ids: number[]
  hits_by_hole: Record<string, Record<string, unknown>[]>
  items: Record<string, unknown>[]
}

export interface DanxiUserProfileResponse {
  session_key: string
  logged_in: boolean
  transport: string
  webvpn_enabled: boolean
  has_webvpn_cookie: boolean
  webvpn_required: boolean
  direct_connect_available: boolean
  profile: Record<string, unknown> | null
}

export interface DanxiActionResponse {
  ok: boolean
  status_code: number
  message: string
  hole_id?: number | null
  floor_id?: number | null
}

export interface DanxiSummaryResponse {
  hole_id: number
  title: string
  summary: string
  key_points: string[]
  reply_highlights: string[]
  floor_count: number
  participant_count: number
  generated_at: string
}

export interface DanxiMessageTargetResponse {
  floor_id: number
  hole_id: number
}

export interface RuntimeMessage {
  message_id: string
  thread_id: string
  session_id: string
  active_workspace_id: string
  workspace_id: string
  endpoint_id: string
  role: MessageRole
  content: string
  status: string
  channel: string
  created_at: string
  temporary?: boolean
}

export interface RuntimeMessageCreatePayload {
  thread_id: string
  active_workspace_id?: string
  workspace_id?: string
  endpoint_id: string
  content: string
  session_id?: string
  endpoint_type?: string
  display_name?: string
  role?: MessageRole
  endpoint_message_id?: string
  preferred_mode?: AssistantMode
  options?: InputRequestPayload['options']
  metadata?: Record<string, unknown>
}

export type EndpointWsConnectionState = 'connected'

export type EndpointWsEvent =
  | { kind: 'ignore' }
  | { kind: 'connection'; threadId: string; status: EndpointWsConnectionState }
  | { kind: 'pong' }
  | { kind: 'ack'; ack: AckPayload }
  | { kind: 'error'; error: RuntimeErrorPayload }
  | { kind: 'runtime_state'; snapshot: RuntimeStateSnapshot }
  | { kind: 'runtime_usage'; snapshot: RuntimeUsageSnapshot }
  | { kind: 'activity'; activity: TurnActivity }
  | { kind: 'confirm_requested'; sessionId: string; payload: ConfirmRequestPayload }
  | { kind: 'confirm_resolved'; sessionId: string; requestId: string; accepted: boolean }
  | { kind: 'human_input_requested'; sessionId: string; payload: HumanInputRequestPayload }
  | { kind: 'human_input_resolved'; sessionId: string; requestId: string; answerText: string; selectedOption?: string }
  | { kind: 'workspace_changed'; threadId: string; sessionId: string; activeWorkspaceId: string; workspaceId: string }
  | { kind: 'thread_switched'; threadId: string; sessionId: string; targetThreadId: string; workspaceId: string }
  | { kind: 'thread_deleted'; threadId: string; sessionId: string; deletedThreadId: string; fallbackThreadId: string; workspaceId: string }
  | {
      kind: 'operation_updated'
      threadId: string
      operationId: string
      workspaceId: string
      title: string
      operationType: string
      executionTarget: string
      targetEndpointId: string
      toolKey: string
      toolId: string
      callId: string
      status: string
      phase: string
      detail: string
      result: Record<string, unknown>
      error: Record<string, unknown>
      approvalId: string
      approvalStatus: string
      approvalRequired: boolean
    }
  | { kind: 'message_created'; threadId: string; sessionId: string; message: RuntimeMessage }
  | {
      kind: 'message_delta'
      threadId: string
      sessionId: string
      streamId: string
      turnId: string
      delta: string
      channel: 'answer' | 'reasoning'
      phase: string
    }
  | {
      kind: 'message_completed'
      threadId: string
      sessionId: string
      streamId: string
      turnId: string
      message: RuntimeMessage
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
  finish_reason?: string
  reply_control?: Record<string, unknown>
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
  context_pool: number
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
    context_pool: boolean
    memory_recall: boolean
    session_preload: boolean
    prefer_live_web: boolean
    history_message_count: number
  }
}

export interface ContextPoolQueryItem {
  context_id: string
  item_type: string
  role: string
  content: string
  score: number
  same_session: boolean
  same_thread: boolean
  same_workspace: boolean
  workspace_tags: string[]
  metadata: Record<string, unknown>
  created_at: string
}

export interface ContextPoolQueryResponse {
  query: string
  count: number
  items: ContextPoolQueryItem[]
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
  reply_control?: Record<string, unknown>
  checkpoints?: Record<string, unknown>[]
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

export interface StatusFeedback {
  id: string
  text: string
  tone: 'neutral' | 'success' | 'error'
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
  clientRequestId?: string
  trimmedActivityCount?: number
  error?: string
  temporary?: boolean
  confirmRequest?: ConfirmRequestPayload | null
  confirmResponse?: { accepted: boolean } | null
  humanInputRequest?: HumanInputRequestPayload | null
  humanInputResponse?: { answerText: string; selectedOption?: string } | null
}

export interface ConfirmRequestPayload {
  requestId: string
  content: string
  timeout?: number
  defaultDecision?: boolean
  approvalId?: string
  approvalStatus?: string
  approvalType?: string
  riskLevel?: string
  operationId?: string
}

export interface HumanInputRequestPayload {
  requestId: string
  question: string
  options: string[]
  placeholder?: string
  timeout?: number
}

export interface ApprovalDisplayModel {
  requestId: string
  title: string
  content: string
  timeoutSeconds?: number
  defaultDecision?: boolean
  isBlocking: boolean
}

export interface AckPayload {
  action: string
  accepted?: boolean
  session_id: string
  event_id?: string
  request_id?: string
  [key: string]: unknown
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
export type ConfigFieldControl = 'directory' | 'directory_list'

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
  control?: ConfigFieldControl | string
  help_text?: string
  examples?: string[]
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

export interface SkillListItem {
  id: string
  skill_type: 'mode' | 'reusable' | string
  title: string
  summary: string
  storage_path?: string
  storage_ref?: string
  editable?: boolean
  source?: string
  applicable_modes: string[]
  scenarios: string[]
  recommended_tools: string[]
}

export interface SkillDetail extends SkillListItem {
  content: string
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
