import { describe, expect, it } from 'vitest'
import {
  parseAckEnvelope,
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
})
