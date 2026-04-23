import { describe, expect, it } from 'vitest'
import {
  parseAckEnvelope,
  parseClientWsPayload,
  parseErrorEnvelope,
  parseRuntimeDebugEnvelope,
  parseRuntimeStateEnvelope,
  parseRuntimeUsageEnvelope,
  parseUiProtocolSchemaEnvelope,
  parseWsPayload,
} from './protocolClient'

describe('protocolClient', () => {
  it('parses runtime state envelope from HTTP response', () => {
    const snapshot = parseRuntimeStateEnvelope({
      schema: 'meetyou.http.v1',
      kind: 'runtime',
      runtime: {
        resource: 'state',
        session_id: 'session-1',
        state: {
          global_state: { session_id: 'global', status: 'idle' },
          heartbeat_state: { session_id: 'heart', status: 'heartbeat' },
          session_state: {
            session_id: 'session-1',
            status: 'thinking',
            detail: 'Calling model',
            active_tools: ['search_web'],
            current_mode: 'research',
            route_reason: 'latest',
            action_risk: 'read',
            source_profile: 'tech_global',
            stream_id: 'stream-1',
            turn_id: 'turn-1',
            updated_at: '2026-04-01T00:00:02Z',
          },
        },
      },
    })

    expect(snapshot?.status).toBe('thinking')
    expect(snapshot?.active_tools).toEqual(['search_web'])
  })

  it('parses runtime usage envelope from HTTP response', () => {
    const snapshot = parseRuntimeUsageEnvelope({
      schema: 'meetyou.http.v1',
      kind: 'runtime',
      runtime: {
        resource: 'usage',
        session_id: 'session-1',
        usage: {
          session_id: 'session-1',
          usage_ready: true,
          context_limit_tokens: 128000,
          context_limit_source: 'config_override',
          context_limit_model: 'gpt-5.4',
          context_limit_confidence: 'high',
          current_context_tokens_estimated: 2048,
          context_breakdown: { total: 2048 },
          last_turn_usage: { total_tokens: 42 },
          session_totals: { total_tokens: 84, turn_count: 2 },
          usage_source: 'provider',
          updated_at: '2026-04-01T00:00:03Z',
        },
      },
    })

    expect(snapshot?.usage_ready).toBe(true)
    expect(snapshot?.session_totals.turn_count).toBe(2)
  })

  it('parses runtime debug envelope from HTTP response', () => {
    const snapshot = parseRuntimeDebugEnvelope({
      schema: 'meetyou.http.v1',
      kind: 'runtime',
      runtime: {
        resource: 'debug',
        session_id: 'session-1',
        debug: {
          session_id: 'session-1',
          route: {},
          route_history: [],
          context_plan: {},
          memory_scope: {},
          authorization: {},
          object_operations: [
            {
              action: 'delete',
              object_type: 'memory',
              status: 'success',
              summary: '已删除记忆。',
            },
          ],
          task_state: {},
          runtime_state: {},
          usage: {},
          request: {
            provider_name: 'openai',
            model: 'deepseek-reasoner',
            api_target: { host: 'api.deepseek.com', path: '/chat/completions' },
            transport_mode: 'openai_compatible_chat',
            message_count: 12,
            tool_count: 2,
            request_tokens_estimated: 4096,
            context_limit_tokens: 128000,
            pressure_ratio: 0.72,
            near_limit: false,
            length_policy: {
              provider_family: 'openai',
              target_input_tokens: 8192,
              reserved_response_tokens: 1024,
              reserve_ratio: 0.72,
            },
            budget: {
              context_limit_tokens: 128000,
              target_input_tokens: 8192,
              reserved_response_tokens: 1024,
              breakdown_total: 4096,
            },
            layers: {
              conversation_summary: true,
              memory_recall: true,
              session_preload: false,
              prefer_live_web: false,
              history_message_count: 5,
            },
          },
          compression: {
            triggered: true,
            level: 'history_summary',
            trimmed_messages: 6,
            before_tokens: 9300,
            after_tokens: 4100,
            usable_tokens: 8192,
            summary_tokens: 520,
          },
          last_failure: {
            code: 'provider_bad_request',
            category: 'validation',
            message: 'HTTP 400',
            retryable: false,
            details: {},
            occurred_at: '2026-04-01T00:00:04Z',
          },
          updated_at: '2026-04-01T00:00:04Z',
        },
      },
    })

    expect(snapshot?.request?.transport_mode).toBe('openai_compatible_chat')
    expect(snapshot?.compression?.triggered).toBe(true)
    expect(snapshot?.last_failure?.code).toBe('provider_bad_request')
    expect(snapshot?.object_operations[0]?.summary).toBe('已删除记忆。')
  })

  it('parses schema envelope from backend single source', () => {
    const schema = parseUiProtocolSchemaEnvelope({
      schema: 'meetyou.http.v1',
      kind: 'schema',
      ui_schema: {
        http_schema: 'meetyou.http.v1',
        ws_schema: 'meetyou.ws.v1',
        ws_frame_kinds: ['connection', 'event', 'runtime', 'ack', 'error', 'health'],
        ws_event_types: ['message', 'status', 'runtime_status'],
        ws_runtime_resources: ['state', 'usage'],
        runtime_statuses: ['idle', 'thinking'],
        providers: [{ label: 'OpenAI', value: 'openai' }],
        thinking_efforts: [{ label: '高', value: 'high' }],
        config_groups: [{ key: 'model', title: '模型', description: 'desc' }],
        config_fields: [
          {
            key: 'api_provider',
            title: '主模型提供商',
            description: 'desc',
            group: 'model',
            input: 'select',
            options: [{ label: 'OpenAI', value: 'openai' }],
            placeholder: '',
            advanced: false,
          },
        ],
      },
    })

    expect(schema?.providers[0]?.value).toBe('openai')
    expect(schema?.config_fields[0]?.key).toBe('api_provider')
  })

  it('parses websocket runtime and control frames', () => {
    const runtimeUpdate = parseWsPayload({
      schema: 'meetyou.ws.v1',
      kind: 'runtime',
      runtime: {
        resource: 'state',
        event_id: 'runtime-1',
        state: {
          session_id: 'session-1',
          status: 'waiting_confirm',
          detail: 'Waiting for confirmation',
          active_tools: ['run_command'],
          current_mode: 'normal',
          route_reason: '',
          action_risk: 'write',
          source_profile: '',
          stream_id: 'stream-1',
          turn_id: 'turn-1',
          updated_at: '2026-04-01T00:00:02Z',
        },
      },
    })
    const ack = parseAckEnvelope({
      schema: 'meetyou.ws.v1',
      kind: 'ack',
      ack: {
        action: 'confirm_response',
        accepted: true,
        session_id: 'session-1',
        event_id: '',
        request_id: 'req-1',
      },
    })

    expect(runtimeUpdate.kind).toBe('runtime_state')
    expect(runtimeUpdate.kind === 'runtime_state' ? runtimeUpdate.snapshot.status : '').toBe('waiting_confirm')
    expect(ack?.request_id).toBe('req-1')
  })

  it('parses HTTP error envelope', () => {
    const error = parseErrorEnvelope({
      schema: 'meetyou.http.v1',
      kind: 'error',
      error: {
        code: 'invalid_config_update',
        category: 'validation',
        message: '配置值无效',
        retryable: false,
        details: { key: 'mode_router' },
        occurred_at: '2026-04-01T00:00:05Z',
      },
    })

    expect(error?.code).toBe('invalid_config_update')
    expect(error?.message).toBe('配置值无效')
    expect(error?.details.key).toBe('mode_router')
  })

  it('parses client websocket message events', () => {
    const created = parseClientWsPayload({
      schema: 'meetyou.client.ws.v1',
      kind: 'event',
      event: {
        type: 'message.created',
        thread_id: 'thr_1',
        session_id: 'sess_1',
        message: {
          message_id: 'msg_1',
          thread_id: 'thr_1',
          session_id: 'sess_1',
          workspace_id: 'personal',
          client_id: 'desktop-app',
          role: 'user',
          content: 'hello',
          status: 'completed',
          channel: 'message',
          created_at: '2026-04-08T00:00:00Z',
        },
      },
    })
    const delta = parseClientWsPayload({
      schema: 'meetyou.client.ws.v1',
      kind: 'event',
      event: {
        type: 'message.delta',
        thread_id: 'thr_1',
        session_id: 'sess_1',
        stream_id: 'stream_1',
        turn_id: 'turn_1',
        delta: 'partial',
      },
    })
    const completed = parseClientWsPayload({
      schema: 'meetyou.client.ws.v1',
      kind: 'event',
      event: {
        type: 'message.completed',
        thread_id: 'thr_1',
        session_id: 'sess_1',
        stream_id: 'stream_1',
        turn_id: 'turn_1',
        message: {
          message_id: 'msg_2',
          thread_id: 'thr_1',
          session_id: 'sess_1',
          workspace_id: 'personal',
          client_id: '',
          role: 'assistant',
          content: 'done',
          status: 'completed',
          channel: 'message',
          created_at: '2026-04-08T00:00:02Z',
          temporary: true,
        },
      },
    })

    expect(created.kind).toBe('message_created')
    expect(created.kind === 'message_created' ? created.message.message_id : '').toBe('msg_1')
    expect(delta.kind).toBe('message_delta')
    expect(delta.kind === 'message_delta' ? delta.delta : '').toBe('partial')
    expect(completed.kind).toBe('message_completed')
    expect(completed.kind === 'message_completed' ? completed.message.content : '').toBe('done')
    expect(completed.kind === 'message_completed' ? completed.message.temporary : false).toBe(true)
  })

  it('parses bridged client websocket message events with nested message fallback', () => {
    const delta = parseClientWsPayload({
      schema: 'meetyou.client.ws.v1',
      kind: 'event',
      event: {
        type: 'message.delta',
        thread_id: 'thr_1',
        session_id: 'system:agent:desktop-main-agent',
        stream_id: 'stream_1',
        turn_id: 'turn_1',
        content: 'partial-from-content',
      },
    })
    const completed = parseClientWsPayload({
      schema: 'meetyou.client.ws.v1',
      kind: 'event',
      event: {
        type: 'message.completed',
        stream_id: 'stream_1',
        turn_id: 'turn_1',
        message: {
          message_id: 'msg_transient_1',
          thread_id: 'thr_1',
          session_id: 'system:agent:desktop-main-agent',
          workspace_id: 'desktop-main',
          client_id: 'desktop-app',
          role: 'assistant',
          content: 'done',
          status: 'completed',
          channel: 'message',
          created_at: '2026-04-08T00:00:03Z',
        },
      },
    })

    expect(delta.kind).toBe('message_delta')
    expect(delta.kind === 'message_delta' ? delta.delta : '').toBe('partial-from-content')
    expect(completed.kind).toBe('message_completed')
    expect(completed.kind === 'message_completed' ? completed.threadId : '').toBe('thr_1')
    expect(completed.kind === 'message_completed' ? completed.sessionId : '').toBe('system:agent:desktop-main-agent')
  })

  it('parses client websocket interactive events', () => {
    const confirm = parseClientWsPayload({
      schema: 'meetyou.client.ws.v1',
      kind: 'event',
      event: {
        type: 'confirm.requested',
        thread_id: 'thr_1',
        session_id: 'sess_1',
        request_id: 'req_1',
        content: '允许执行吗？',
        timeout: 30,
        default_decision: false,
        approval_id: 'approval_1',
        approval_status: 'pending',
        approval_type: 'chat_confirmation',
        risk_level: 'system',
        operation_id: 'op_confirm_1',
      },
    })
    const humanInput = parseClientWsPayload({
      schema: 'meetyou.client.ws.v1',
      kind: 'event',
      event: {
        type: 'human_input.requested',
        thread_id: 'thr_1',
        session_id: 'sess_1',
        request_id: 'req_2',
        question: '请选择模式',
        options: ['A', 'B'],
        placeholder: '输入',
        timeout: 60,
      },
    })

    expect(confirm.kind).toBe('confirm_requested')
    expect(confirm.kind === 'confirm_requested' ? confirm.payload.requestId : '').toBe('req_1')
    expect(confirm.kind === 'confirm_requested' ? confirm.payload.approvalId : '').toBe('approval_1')
    expect(humanInput.kind).toBe('human_input_requested')
    expect(humanInput.kind === 'human_input_requested' ? humanInput.payload.options : []).toEqual(['A', 'B'])
  })

  it('parses operation updated events', () => {
    const event = parseClientWsPayload({
      schema: 'meetyou.client.ws.v1',
      kind: 'event',
      event: {
        type: 'operation.updated',
        thread_id: 'thr_1',
        operation_id: 'op_1',
        call_id: 'call_1',
        status: 'running',
        phase: 'accepted',
        detail: 'Dispatching',
      },
    })

    expect(event.kind).toBe('operation_updated')
    expect(event.kind === 'operation_updated' ? event.operationId : '').toBe('op_1')
    expect(event.kind === 'operation_updated' ? event.status : '').toBe('running')
  })

  it('parses runtime and activity events from client websocket', () => {
    const runtimeState = parseClientWsPayload({
      schema: 'meetyou.client.ws.v1',
      kind: 'event',
      event: {
        type: 'runtime.state',
        snapshot: {
          session_id: 'sess_1',
          status: 'thinking',
          detail: 'Working',
          active_tools: ['search_web'],
          current_mode: 'research',
          route_reason: 'need_web',
          action_risk: 'read',
          source_profile: 'tech_updates',
          stream_id: 'stream_1',
          turn_id: 'turn_1',
          updated_at: '2026-04-08T00:00:00Z',
        },
      },
    })
    const runtimeUsage = parseClientWsPayload({
      schema: 'meetyou.client.ws.v1',
      kind: 'event',
      event: {
        type: 'runtime.usage',
        snapshot: {
          session_id: 'sess_1',
          usage_ready: true,
          context_limit_tokens: 1000,
          context_limit_source: 'config',
          context_limit_model: 'gpt-5.4',
          context_limit_confidence: 'high',
          current_context_tokens_estimated: 250,
          context_breakdown: {
            system: 10,
            history: 20,
            tool_history: 5,
            memory_context: 7,
            policy: 3,
            current_input: 4,
            proprioception: 1,
            total: 50,
          },
          last_turn_usage: { prompt_tokens: 1, completion_tokens: 2, reasoning_tokens: 3, total_tokens: 6 },
          session_totals: { prompt_tokens: 1, completion_tokens: 2, reasoning_tokens: 3, total_tokens: 6, turn_count: 1 },
          usage_source: 'estimated',
          updated_at: '2026-04-08T00:00:01Z',
        },
      },
    })
    const activity = parseClientWsPayload({
      schema: 'meetyou.client.ws.v1',
      kind: 'event',
      event: {
        type: 'activity.status',
        turn_id: 'turn_1',
        stream_id: 'stream_1',
        phase: 'searching',
        content: 'Searching web',
        activity_kind: 'tool_chain',
        tool_names: ['search_web'],
        event_id: 'evt_1',
      },
    })
    const reasoning = parseClientWsPayload({
      schema: 'meetyou.client.ws.v1',
      kind: 'event',
      event: {
        type: 'reasoning.delta',
        thread_id: 'thr_1',
        session_id: 'sess_1',
        stream_id: 'stream_1',
        turn_id: 'turn_1',
        phase: 'chunk',
        delta: 'thinking...',
      },
    })

    expect(runtimeState.kind).toBe('runtime_state')
    expect(runtimeUsage.kind).toBe('runtime_usage')
    expect(activity.kind).toBe('activity')
    expect(activity.kind === 'activity' ? activity.activity.content : '').toBe('Searching web')
    expect(reasoning.kind).toBe('message_delta')
    expect(reasoning.kind === 'message_delta' ? reasoning.channel : '').toBe('reasoning')
  })
})
