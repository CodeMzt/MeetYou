import type {
  AckPayload,
  ClientMessage,
  ClientWsEvent,
  ConfirmRequestPayload,
  HumanInputRequestPayload,
  RuntimeCompressionSnapshot,
  RuntimeDebugSnapshot,
  RuntimeErrorPayload,
  RuntimeHealthSnapshot,
  RuntimeRequestSnapshot,
  RuntimeStateSnapshot,
  RuntimeUsageSnapshot,
  TurnActivity,
  UiProtocolSchema,
} from './types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function toRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {}
}

function toString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function toBoolean(value: unknown): boolean {
  return typeof value === 'boolean' ? value : false
}

function toStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function toNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : Number(value ?? 0)
}

function normalizeContent(value: unknown): string {
  if (typeof value === 'string') {
    return value
  }
  if (value == null) {
    return ''
  }
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function toClientMessage(value: unknown): ClientMessage | null {
  const record = toRecord(value)
  if (!record.message_id || !record.thread_id || !record.role) {
    return null
  }
    return {
      message_id: toString(record.message_id),
      thread_id: toString(record.thread_id),
      session_id: toString(record.session_id),
      active_workspace_id: toString(record.active_workspace_id || record.workspace_id),
      workspace_id: toString(record.workspace_id || record.active_workspace_id),
    client_id: toString(record.client_id),
    role: (toString(record.role) || 'assistant') as ClientMessage['role'],
    content: normalizeContent(record.content),
    status: toString(record.status) || 'completed',
    channel: toString(record.channel) || 'message',
    created_at: toString(record.created_at),
    temporary: toBoolean(record.temporary),
  }
}

function resolveEventThreadId(event: Record<string, unknown>): string {
  return toString(event.thread_id) || toString(toRecord(event.message).thread_id)
}

function resolveEventSessionId(event: Record<string, unknown>): string {
  return toString(event.session_id) || toString(toRecord(event.message).session_id)
}

function toOperationUpdatedEvent(event: Record<string, unknown>): ClientWsEvent {
  return {
    kind: 'operation_updated',
    threadId: resolveEventThreadId(event),
    operationId: toString(event.operation_id),
    workspaceId: toString(event.workspace_id),
    title: toString(event.title),
    operationType: toString(event.operation_type),
    executionTarget: toString(event.execution_target),
    targetEndpointId: toString(event.target_endpoint_id),
    toolKey: toString(event.tool_key),
    toolId: toString(event.tool_id),
    callId: toString(event.call_id),
    status: toString(event.status),
    phase: toString(event.phase),
    detail: toString(event.detail),
    result: toRecord(event.result),
    error: toRecord(event.error),
    approvalId: toString(event.approval_id),
    approvalStatus: toString(event.approval_status),
    approvalRequired: toBoolean(event.approval_required),
  }
}

function toAckPayload(value: unknown): AckPayload | null {
  const record = toRecord(value)
  if (!record.action) {
    return null
  }
  return {
    action: toString(record.action),
    accepted: record.accepted !== false,
    session_id: toString(record.session_id),
    event_id: toString(record.event_id),
    request_id: toString(record.request_id),
  }
}

function toRuntimeErrorPayload(value: unknown): RuntimeErrorPayload | null {
  const record = toRecord(value)
  if (!record.code || !record.message) {
    return null
  }
  return {
    code: toString(record.code),
    category: toString(record.category) || 'runtime',
    message: toString(record.message),
    retryable: toBoolean(record.retryable),
    details: toRecord(record.details),
    occurred_at: toString(record.occurred_at),
  }
}

function toRuntimeHealthSnapshot(value: unknown): RuntimeHealthSnapshot | null {
  const record = toRecord(value)
  if (!record.service || !record.status) {
    return null
  }
  return {
    service: toString(record.service),
    version: toString(record.version),
    status: toString(record.status),
    live: toBoolean(record.live),
    ready: toBoolean(record.ready),
    degraded: toBoolean(record.degraded),
    components: Array.isArray(record.components)
      ? record.components.map((item) => {
          const component = toRecord(item)
          return {
            name: toString(component.name),
            status: toString(component.status),
            detail: toString(component.detail),
            last_event: toString(component.last_event),
            updated_at: toString(component.updated_at),
          }
        })
      : [],
    errors: Array.isArray(record.errors)
      ? record.errors
          .map((item) => toRuntimeErrorPayload(item))
          .filter((item): item is RuntimeErrorPayload => item !== null)
      : [],
    updated_at: toString(record.updated_at),
  }
}

function toRuntimeStateSnapshot(value: unknown): RuntimeStateSnapshot | null {
  const record = toRecord(value)
  if (!record.session_id && !record.status && !record.turn_id && !record.stream_id) {
    return null
  }
  return {
    session_id: toString(record.session_id),
    status: toString(record.status) || 'idle',
    detail: toString(record.detail),
    active_tools: toStringArray(record.active_tools),
    current_mode: toString(record.current_mode),
    route_reason: toString(record.route_reason),
    action_risk: toString(record.action_risk),
    source_profile: toString(record.source_profile),
    stream_id: toString(record.stream_id),
    turn_id: toString(record.turn_id),
    updated_at: toString(record.updated_at),
    finish_reason: toString(record.finish_reason),
    reply_control: toRecord(record.reply_control),
  }
}

function toRuntimeUsageSnapshot(value: unknown): RuntimeUsageSnapshot | null {
  const record = toRecord(value)
  if (!record.session_id) {
    return null
  }
  const contextBreakdown = toRecord(record.context_breakdown)
  const lastTurnUsage = toRecord(record.last_turn_usage)
  const sessionTotals = toRecord(record.session_totals)
  return {
    session_id: toString(record.session_id),
    usage_ready: toBoolean(record.usage_ready),
    context_limit_tokens: toNumber(record.context_limit_tokens),
    context_limit_source: toString(record.context_limit_source),
    context_limit_model: toString(record.context_limit_model),
    context_limit_confidence: toString(record.context_limit_confidence),
    current_context_tokens_estimated: toNumber(record.current_context_tokens_estimated),
    context_breakdown: {
      system: toNumber(contextBreakdown.system),
      history: toNumber(contextBreakdown.history),
      tool_history: toNumber(contextBreakdown.tool_history),
      context_pool: toNumber(contextBreakdown.context_pool),
      memory_context: toNumber(contextBreakdown.memory_context),
      policy: toNumber(contextBreakdown.policy),
      current_input: toNumber(contextBreakdown.current_input),
      proprioception: toNumber(contextBreakdown.proprioception),
      total: toNumber(contextBreakdown.total),
    },
    last_turn_usage: {
      prompt_tokens: toNumber(lastTurnUsage.prompt_tokens),
      completion_tokens: toNumber(lastTurnUsage.completion_tokens),
      reasoning_tokens: toNumber(lastTurnUsage.reasoning_tokens),
      total_tokens: toNumber(lastTurnUsage.total_tokens),
    },
    session_totals: {
      prompt_tokens: toNumber(sessionTotals.prompt_tokens),
      completion_tokens: toNumber(sessionTotals.completion_tokens),
      reasoning_tokens: toNumber(sessionTotals.reasoning_tokens),
      total_tokens: toNumber(sessionTotals.total_tokens),
      turn_count: toNumber(sessionTotals.turn_count),
    },
    usage_source: toString(record.usage_source),
    updated_at: toString(record.updated_at),
  }
}

function toRuntimeRequestSnapshot(value: unknown): RuntimeRequestSnapshot | null {
  const record = toRecord(value)
  if (!record.provider_name && !record.model && !record.transport_mode) {
    return null
  }
  const apiTarget = toRecord(record.api_target)
  const lengthPolicy = toRecord(record.length_policy)
  const budget = toRecord(record.budget)
  const layers = toRecord(record.layers)
  return {
    provider_name: toString(record.provider_name),
    model: toString(record.model),
    api_target: {
      host: toString(apiTarget.host),
      path: toString(apiTarget.path),
    },
    transport_mode: toString(record.transport_mode),
    message_count: toNumber(record.message_count),
    tool_count: toNumber(record.tool_count),
    request_tokens_estimated: toNumber(record.request_tokens_estimated),
    context_limit_tokens: toNumber(record.context_limit_tokens),
    pressure_ratio: toNumber(record.pressure_ratio),
    near_limit: toBoolean(record.near_limit),
    length_policy: {
      provider_family: toString(lengthPolicy.provider_family),
      target_input_tokens: toNumber(lengthPolicy.target_input_tokens),
      reserved_response_tokens: toNumber(lengthPolicy.reserved_response_tokens),
      reserve_ratio: toNumber(lengthPolicy.reserve_ratio),
    },
    budget: {
      context_limit_tokens: toNumber(budget.context_limit_tokens),
      target_input_tokens: toNumber(budget.target_input_tokens),
      reserved_response_tokens: toNumber(budget.reserved_response_tokens),
      breakdown_total: toNumber(budget.breakdown_total),
    },
    layers: {
      conversation_summary: toBoolean(layers.conversation_summary),
      context_pool: toBoolean(layers.context_pool),
      memory_recall: toBoolean(layers.memory_recall),
      session_preload: toBoolean(layers.session_preload),
      prefer_live_web: toBoolean(layers.prefer_live_web),
      history_message_count: toNumber(layers.history_message_count),
    },
  }
}

function toRuntimeCompressionSnapshot(value: unknown): RuntimeCompressionSnapshot | null {
  const record = toRecord(value)
  if (!record.level && !record.triggered && !record.before_tokens && !record.after_tokens) {
    return null
  }
  return {
    triggered: toBoolean(record.triggered),
    level: toString(record.level),
    trimmed_messages: toNumber(record.trimmed_messages),
    before_tokens: toNumber(record.before_tokens),
    after_tokens: toNumber(record.after_tokens),
    usable_tokens: toNumber(record.usable_tokens),
    summary_tokens: toNumber(record.summary_tokens),
  }
}

function toRuntimeDebugSnapshot(value: unknown): RuntimeDebugSnapshot | null {
  const record = toRecord(value)
  const sessionId = toString(record.session_id)
  if (!sessionId) {
    return null
  }
  return {
    session_id: sessionId,
    route: toRecord(record.route),
    route_history: Array.isArray(record.route_history) ? record.route_history.map((item) => toRecord(item)) : [],
    context_plan: toRecord(record.context_plan),
    memory_scope: toRecord(record.memory_scope),
    authorization: toRecord(record.authorization),
    object_operations: Array.isArray(record.object_operations)
      ? record.object_operations.map((item) => toRecord(item))
      : [],
    task_state: toRecord(record.task_state),
    runtime_state: toRecord(record.runtime_state),
    usage: toRecord(record.usage),
    request: toRuntimeRequestSnapshot(record.request),
    compression: toRuntimeCompressionSnapshot(record.compression),
    last_failure: toRuntimeErrorPayload(record.last_failure),
    updated_at: toString(record.updated_at),
    reply_control: toRecord(record.reply_control),
    checkpoints: Array.isArray(record.checkpoints)
      ? record.checkpoints.map((item) => toRecord(item))
      : [],
  }
}

function getToolNames(metadata: Record<string, unknown>): string[] {
  return toStringArray(metadata.tool_names)
}

export type ProtocolUpdate =
  | { kind: 'ignore' }
  | { kind: 'connection'; sessionId: string; sourceId: string; status: string }
  | { kind: 'ack'; ack: AckPayload }
  | { kind: 'error'; error: RuntimeErrorPayload }
  | { kind: 'health'; health: RuntimeHealthSnapshot }
  | { kind: 'runtime_state'; snapshot: RuntimeStateSnapshot; eventId: string }
  | { kind: 'runtime_usage'; snapshot: RuntimeUsageSnapshot; eventId: string }
  | { kind: 'confirm_request'; payload: ConfirmRequestPayload; eventId: string }
  | { kind: 'human_input_request'; payload: HumanInputRequestPayload; eventId: string }
  | { kind: 'status'; activity: TurnActivity; eventId: string }
  | {
      kind: 'message'
      eventId: string
      role: string
      content: string
      streamId: string
      turnId: string
      channel: string
      phase: string
    }

export function parseUiProtocolSchemaEnvelope(payload: unknown): UiProtocolSchema | null {
  const record = toRecord(payload)
  if (toString(record.kind) !== 'schema') {
    return null
  }
  const schema = toRecord(record.ui_schema)
  if (!schema.http_schema || !schema.ws_schema) {
    return null
  }
  return {
    http_schema: toString(schema.http_schema),
    ws_schema: toString(schema.ws_schema),
    ws_frame_kinds: toStringArray(schema.ws_frame_kinds),
    ws_event_types: toStringArray(schema.ws_event_types),
    ws_runtime_resources: toStringArray(schema.ws_runtime_resources),
    runtime_statuses: toStringArray(schema.runtime_statuses),
    providers: Array.isArray(schema.providers)
      ? schema.providers
          .map((item) => {
            const option = toRecord(item)
            return {
              label: toString(option.label),
              value: toString(option.value),
            }
          })
          .filter((item) => item.value)
      : [],
    thinking_efforts: Array.isArray(schema.thinking_efforts)
      ? schema.thinking_efforts
          .map((item) => {
            const option = toRecord(item)
            return {
              label: toString(option.label),
              value: toString(option.value),
            }
          })
          .filter((item) => item.value)
      : [],
    config_groups: Array.isArray(schema.config_groups)
      ? schema.config_groups
          .map((item) => {
            const group = toRecord(item)
            return {
              key: toString(group.key) as UiProtocolSchema['config_groups'][number]['key'],
              title: toString(group.title),
              description: toString(group.description),
            }
          })
          .filter((item) => item.key)
      : [],
    config_fields: Array.isArray(schema.config_fields)
      ? schema.config_fields
          .map((item) => {
            const field = toRecord(item)
            return {
              key: toString(field.key),
              title: toString(field.title),
              description: toString(field.description),
              group: toString(field.group) as UiProtocolSchema['config_fields'][number]['group'],
              input: toString(field.input) as UiProtocolSchema['config_fields'][number]['input'],
              options: Array.isArray(field.options)
                ? field.options
                    .map((option) => {
                      const normalized = toRecord(option)
                      return {
                        label: toString(normalized.label),
                        value: toString(normalized.value),
                      }
                    })
                    .filter((option) => option.value)
                : [],
              placeholder: toString(field.placeholder),
              advanced: toBoolean(field.advanced),
            }
          })
          .filter((item) => item.key)
      : [],
  }
}

export function parseRuntimeStateEnvelope(payload: unknown): RuntimeStateSnapshot | null {
  const record = toRecord(payload)
  if (toString(record.kind) !== 'runtime') {
    return null
  }
  const runtime = toRecord(record.runtime)
  if (toString(runtime.resource) !== 'state') {
    return null
  }
  return toRuntimeStateSnapshot(toRecord(runtime.state).session_state)
}

export function parseRuntimeUsageEnvelope(payload: unknown): RuntimeUsageSnapshot | null {
  const record = toRecord(payload)
  if (toString(record.kind) !== 'runtime') {
    return null
  }
  const runtime = toRecord(record.runtime)
  if (toString(runtime.resource) !== 'usage') {
    return null
  }
  return toRuntimeUsageSnapshot(runtime.usage)
}

export function parseRuntimeDebugEnvelope(payload: unknown): RuntimeDebugSnapshot | null {
  const record = toRecord(payload)
  if (toString(record.kind) !== 'runtime') {
    return null
  }
  const runtime = toRecord(record.runtime)
  if (toString(runtime.resource) !== 'debug') {
    return null
  }
  return toRuntimeDebugSnapshot(runtime.debug)
}

export function parseHealthEnvelope(payload: unknown): RuntimeHealthSnapshot | null {
  const record = toRecord(payload)
  if (toString(record.kind) !== 'health') {
    return null
  }
  return toRuntimeHealthSnapshot(record.health)
}

export function parseAckEnvelope(payload: unknown): AckPayload | null {
  const record = toRecord(payload)
  if (toString(record.kind) !== 'ack') {
    return null
  }
  return toAckPayload(record.ack)
}

export function parseErrorEnvelope(payload: unknown): RuntimeErrorPayload | null {
  const record = toRecord(payload)
  if (toString(record.kind) !== 'error') {
    return null
  }
  return toRuntimeErrorPayload(record.error)
}

export function parseWsPayload(payload: unknown, now: number = Date.now()): ProtocolUpdate {
  const record = toRecord(payload)
  const kind = toString(record.kind)

  if (kind === 'connection') {
    const connection = toRecord(record.connection)
    return {
      kind: 'connection',
      sessionId: toString(connection.session_id),
      sourceId: toString(connection.source_id),
      status: toString(connection.status) || 'connected',
    }
  }

  if (kind === 'ack') {
    const ack = toAckPayload(record.ack)
    return ack ? { kind: 'ack', ack } : { kind: 'ignore' }
  }

  if (kind === 'error') {
    const error = toRuntimeErrorPayload(record.error)
    return error ? { kind: 'error', error } : { kind: 'ignore' }
  }

  if (kind === 'health') {
    const health = toRuntimeHealthSnapshot(record.health)
    return health ? { kind: 'health', health } : { kind: 'ignore' }
  }

  if (kind === 'runtime') {
    const runtime = toRecord(record.runtime)
    const resource = toString(runtime.resource)
    if (resource === 'state') {
      const snapshot = toRuntimeStateSnapshot(toRecord(runtime.state).session_state ?? runtime.state)
      return snapshot
        ? {
            kind: 'runtime_state',
            snapshot,
            eventId: toString(runtime.event_id),
          }
        : { kind: 'ignore' }
    }
    if (resource === 'usage') {
      const snapshot = toRuntimeUsageSnapshot(runtime.usage)
      return snapshot
        ? {
            kind: 'runtime_usage',
            snapshot,
            eventId: toString(runtime.event_id),
          }
        : { kind: 'ignore' }
    }
    return { kind: 'ignore' }
  }

  if (kind !== 'event') {
    return { kind: 'ignore' }
  }

  const rawEvent = toRecord(record.event)
  const rawStream = toRecord(record.stream)
  const metadata = toRecord(rawEvent.metadata)
  const eventId = toString(rawEvent.event_id)
  const turnId = toString(metadata.turn_id)
  const streamId = toString(rawStream.id)
  const phase = toString(rawStream.phase) || 'chunk'
  const channel = toString(rawStream.channel)
  const content = normalizeContent(rawEvent.content)
  const eventType = toString(rawEvent.type)

  if (eventType === 'confirm_request') {
    const confirm = toRecord(rawEvent.confirm)
    return {
      kind: 'confirm_request',
      eventId,
      payload: {
        requestId: toString(confirm.request_id),
        content,
        timeout: typeof confirm.timeout === 'number' ? confirm.timeout : undefined,
        defaultDecision: typeof confirm.default_decision === 'boolean' ? confirm.default_decision : undefined,
      },
    }
  }

  if (eventType === 'human_input_request') {
    const inputRequest = toRecord(rawEvent.input_request)
    return {
      kind: 'human_input_request',
      eventId,
      payload: {
        requestId: toString(inputRequest.request_id),
        question: toString(inputRequest.question) || content,
        options: toStringArray(inputRequest.options),
        placeholder: toString(inputRequest.placeholder),
        timeout: typeof inputRequest.timeout === 'number' ? inputRequest.timeout : undefined,
      },
    }
  }

  if (eventType === 'runtime_status') {
    const snapshot = toRuntimeStateSnapshot(rawEvent.content)
    return snapshot ? { kind: 'runtime_state', snapshot, eventId } : { kind: 'ignore' }
  }

  if (eventType === 'usage') {
    const snapshot = toRuntimeUsageSnapshot(rawEvent.content)
    return snapshot ? { kind: 'runtime_usage', snapshot, eventId } : { kind: 'ignore' }
  }

  if (eventType === 'status') {
    return {
      kind: 'status',
      eventId,
      activity: {
        id: eventId || `${turnId || streamId || 'activity'}-${now}`,
        turnId,
        streamId,
        phase: toString(metadata.activity_phase) || toString(metadata.search_phase) || 'status',
        content,
        activityKind: toString(metadata.activity_kind) || 'tool_chain',
        toolNames: getToolNames(metadata),
        metadata,
        createdAt: now,
      },
    }
  }

  if (eventType === 'message' || eventType === 'reasoning') {
    return {
      kind: 'message',
      eventId,
      role: toString(rawEvent.role) || 'assistant',
      content,
      streamId,
      turnId,
      channel: channel || (eventType === 'reasoning' ? 'reasoning' : 'answer'),
      phase,
    }
  }

  if (eventType === 'error') {
    const error = toRuntimeErrorPayload(rawEvent.content) ?? {
      code: 'runtime_event_error',
      category: 'runtime',
      message: content || '运行事件发生错误。',
      retryable: false,
      details: metadata,
      occurred_at: '',
    }
    return { kind: 'error', error }
  }

  return { kind: 'ignore' }
}

export function parseClientWsPayload(payload: unknown): ClientWsEvent {
  const record = toRecord(payload)
  if (toString(record.schema) === 'meetyou.endpoint.ws.v4') {
    const frameType = toString(record.type)
    if (frameType === 'endpoint.hello.ack' || frameType === 'subscription.ack') {
      const body = toRecord(record.payload)
      return {
        kind: 'connection',
        threadId: toString(body.target_id),
        status: 'connected',
      }
    }
    if (frameType === 'endpoint.error') {
      const error = toRuntimeErrorPayload(record.payload)
      return error ? { kind: 'error', error } : { kind: 'ignore' }
    }
    if (frameType === 'delivery.operation_update') {
      return toOperationUpdatedEvent(toRecord(record.payload))
    }
    if (frameType !== 'delivery.run_event') {
      return { kind: 'ignore' }
    }
    const outer = toRecord(record.payload)
    const body = toRecord(outer.payload)
    return parseClientWsPayload({
      kind: 'event',
      event: {
        ...body,
        type: toString(outer.type),
        thread_id: toString(outer.thread_id) || toString(body.thread_id),
        session_id: toString(body.session_id) || toString(outer.session_id),
        stream_id: toString(body.stream_id) || toString(outer.stream_id),
        turn_id: toString(body.turn_id) || toString(outer.turn_id),
        event_id: toString(outer.event_id),
      },
    })
  }
  const kind = toString(record.kind)

  if (kind === 'connection') {
    const connection = toRecord(record.connection)
    return {
      kind: 'connection',
      threadId: toString(connection.thread_id),
      status: 'connected',
    }
  }

  if (kind === 'pong') {
    return { kind: 'pong' }
  }

  if (kind === 'ack') {
    const ack = toAckPayload(record.ack)
    return ack ? { kind: 'ack', ack } : { kind: 'ignore' }
  }

  if (kind === 'error') {
    const error = toRuntimeErrorPayload(record.error)
    return error ? { kind: 'error', error } : { kind: 'ignore' }
  }

  if (kind !== 'event') {
    return { kind: 'ignore' }
  }

  const event = toRecord(record.event)
  const eventType = toString(event.type)
  const threadId = resolveEventThreadId(event)
  const sessionId = resolveEventSessionId(event)

  if (eventType === 'message.created') {
    const message = toClientMessage(event.message)
    return message ? { kind: 'message_created', threadId, sessionId, message } : { kind: 'ignore' }
  }

  if (eventType === 'workspace.changed') {
    return {
      kind: 'workspace_changed',
      threadId,
      sessionId,
      activeWorkspaceId: toString(event.active_workspace_id || event.workspace_id),
      workspaceId: toString(event.workspace_id || event.active_workspace_id),
    }
  }

  if (eventType === 'confirm.requested') {
    return {
      kind: 'confirm_requested',
      sessionId,
      payload: {
        requestId: toString(event.request_id),
        content: toString(event.content),
        timeout: toNumber(event.timeout) || undefined,
        defaultDecision: typeof event.default_decision === 'boolean' ? toBoolean(event.default_decision) : undefined,
        approvalId: toString(event.approval_id) || undefined,
        approvalStatus: toString(event.approval_status) || undefined,
        approvalType: toString(event.approval_type) || undefined,
        riskLevel: toString(event.risk_level) || undefined,
        operationId: toString(event.operation_id) || undefined,
      },
    }
  }

  if (eventType === 'confirm.resolved') {
    return {
      kind: 'confirm_resolved',
      sessionId,
      requestId: toString(event.request_id),
      accepted: toBoolean(event.accepted),
    }
  }

  if (eventType === 'human_input.requested') {
    return {
      kind: 'human_input_requested',
      sessionId,
      payload: {
        requestId: toString(event.request_id),
        question: toString(event.question),
        options: toStringArray(event.options),
        placeholder: toString(event.placeholder),
        timeout: toNumber(event.timeout) || undefined,
      },
    }
  }

  if (eventType === 'human_input.resolved') {
    return {
      kind: 'human_input_resolved',
      sessionId,
      requestId: toString(event.request_id),
      answerText: toString(event.answer_text),
      selectedOption: toString(event.selected_option) || undefined,
    }
  }

  if (eventType === 'operation.updated') {
    return toOperationUpdatedEvent(event)
  }

  if (eventType === 'runtime.state') {
    const snapshot = toRuntimeStateSnapshot(event.snapshot)
    return snapshot ? { kind: 'runtime_state', snapshot } : { kind: 'ignore' }
  }

  if (eventType === 'runtime.usage') {
    const snapshot = toRuntimeUsageSnapshot(event.snapshot)
    return snapshot ? { kind: 'runtime_usage', snapshot } : { kind: 'ignore' }
  }

  if (eventType === 'activity.status') {
    const metadata = toRecord(event.metadata)
    return {
      kind: 'activity',
      activity: {
        id: toString(event.event_id) || `${toString(event.turn_id) || toString(event.stream_id) || 'activity'}-${Date.now()}`,
        turnId: toString(event.turn_id),
        streamId: toString(event.stream_id),
        phase: toString(event.phase) || 'status',
        content: toString(event.content),
        activityKind: toString(event.activity_kind) || 'tool_chain',
        toolNames: toStringArray(event.tool_names),
        metadata,
        createdAt: Date.now(),
      },
    }
  }

  if (eventType === 'message.delta') {
    return {
      kind: 'message_delta',
      threadId,
      sessionId,
      streamId: toString(event.stream_id),
      turnId: toString(event.turn_id),
      delta: toString(event.delta) || normalizeContent(event.content),
      channel: 'answer',
      phase: 'chunk',
    }
  }

  if (eventType === 'reasoning.delta') {
    return {
      kind: 'message_delta',
      threadId,
      sessionId,
      streamId: toString(event.stream_id),
      turnId: toString(event.turn_id),
      delta: toString(event.delta) || normalizeContent(event.content),
      channel: 'reasoning',
      phase: toString(event.phase) || 'chunk',
    }
  }

  if (eventType === 'message.completed') {
    const message = toClientMessage(event.message)
    if (!message) {
      return { kind: 'ignore' }
    }
    return {
      kind: 'message_completed',
      threadId,
      sessionId,
      streamId: toString(event.stream_id),
      turnId: toString(event.turn_id),
      message,
    }
  }

  return { kind: 'ignore' }
}
