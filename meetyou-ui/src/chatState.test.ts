import { describe, expect, it } from 'vitest'
import {
  createInitialChatState,
  createSystemTurn,
  createUserTurn,
  reduceChatState,
} from './chatState'

describe('chatState', () => {
  it('trims long sessions while keeping recent messages', () => {
    let state = createInitialChatState()

    for (let index = 0; index < 180; index += 1) {
      state = reduceChatState(state, {
        type: 'append_user_turn',
        turn: createUserTurn(`message-${index}`, `turn-${index}`),
      })
    }

    expect(state.messages.length).toBeLessThanOrEqual(160)
    expect(state.archivedTurnCount).toBeGreaterThan(0)
    expect(state.messages[state.messages.length - 1]?.content).toBe('message-179')
  })

  it('trims excessive tool activities on the same turn', () => {
    let state = createInitialChatState()

    for (let index = 0; index < 60; index += 1) {
      state = reduceChatState(state, {
        type: 'append_activity',
        activeTurnId: 'turn-1',
        activity: {
          id: `activity-${index}`,
          turnId: 'turn-1',
          streamId: 'stream-1',
          phase: 'status',
          content: `activity-${index}`,
          activityKind: 'tool_chain',
          toolNames: [],
          metadata: {},
          createdAt: index,
        },
      })
    }

    expect(state.messages[0]?.activities.length).toBeLessThanOrEqual(48)
    expect(state.messages[0]?.trimmedActivityCount).toBeGreaterThan(0)
  })

  it('keeps explicit system notices in chat flow', () => {
    const state = reduceChatState(createInitialChatState(), {
      type: 'append_system_turn',
      turn: createSystemTurn('确认结果已提交，服务继续执行。'),
    })

    expect(state.messages[0]?.role).toBe('system')
    expect(state.messages[0]?.content).toContain('确认结果')
  })

  it('hydrates persisted client messages into chat turns', () => {
    const state = reduceChatState(createInitialChatState(), {
      type: 'hydrate_messages',
      messages: [
        {
          message_id: 'msg_user',
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
        {
          message_id: 'msg_assistant',
          thread_id: 'thr_1',
          session_id: 'sess_1',
          workspace_id: 'personal',
          client_id: '',
          role: 'assistant',
          content: 'hi',
          status: 'completed',
          channel: 'message',
          created_at: '2026-04-08T00:00:01Z',
        },
      ],
    })

    expect(state.messages).toHaveLength(2)
    expect(state.messages[0]?.id).toBe('msg_user')
    expect(state.messages[1]?.content).toBe('hi')
  })

  it('finalizes streaming assistant message using completed payload', () => {
    let state = reduceChatState(createInitialChatState(), {
      type: 'append_message',
      role: 'assistant',
      content: 'hel',
      streamId: 'stream-1',
      turnId: 'turn-1',
      channel: 'answer',
      phase: 'chunk',
      eventId: 'evt-1',
      activeTurnId: 'turn-1',
    })

    state = reduceChatState(state, {
      type: 'complete_stream_message',
      streamId: 'stream-1',
      turnId: 'turn-1',
      message: {
        message_id: 'msg_assistant',
        thread_id: 'thr_1',
        session_id: 'sess_1',
        workspace_id: 'personal',
        client_id: '',
        role: 'assistant',
        content: 'hello',
        status: 'completed',
        channel: 'message',
        created_at: '2026-04-08T00:00:02Z',
      },
    })

    expect(state.messages[0]?.content).toBe('hel')
    expect(state.messages[0]?.isStreaming).toBe(false)
  })

  it('keeps newer ready usage snapshot when hydration returns older bootstrap data', () => {
    let state = reduceChatState(createInitialChatState(), {
      type: 'sync_usage',
      snapshot: {
        session_id: 'sess_1',
        usage_ready: true,
        context_limit_tokens: 128000,
        context_limit_source: 'provider_probe',
        context_limit_model: 'gpt-5.4',
        context_limit_confidence: 'high',
        current_context_tokens_estimated: 4096,
        context_breakdown: {
          system: 128,
          history: 1024,
          tool_history: 64,
          memory_context: 256,
          policy: 64,
          current_input: 256,
          proprioception: 64,
          total: 1856,
        },
        last_turn_usage: {
          prompt_tokens: 1200,
          completion_tokens: 300,
          reasoning_tokens: 200,
          total_tokens: 1700,
        },
        session_totals: {
          prompt_tokens: 2400,
          completion_tokens: 600,
          reasoning_tokens: 400,
          total_tokens: 3400,
          turn_count: 2,
        },
        usage_source: 'provider',
        updated_at: '2026-04-09T12:00:05Z',
      },
    })

    state = reduceChatState(state, {
      type: 'sync_usage',
      snapshot: {
        session_id: 'sess_1',
        usage_ready: false,
        context_limit_tokens: 128000,
        context_limit_source: 'config_override',
        context_limit_model: 'gpt-5.4',
        context_limit_confidence: 'high',
        current_context_tokens_estimated: 0,
        context_breakdown: {
          system: 0,
          history: 0,
          tool_history: 0,
          memory_context: 0,
          policy: 0,
          current_input: 0,
          proprioception: 0,
          total: 0,
        },
        last_turn_usage: {
          prompt_tokens: 0,
          completion_tokens: 0,
          reasoning_tokens: 0,
          total_tokens: 0,
        },
        session_totals: {
          prompt_tokens: 0,
          completion_tokens: 0,
          reasoning_tokens: 0,
          total_tokens: 0,
          turn_count: 0,
        },
        usage_source: 'estimated',
        updated_at: '2026-04-09T12:00:06Z',
      },
    })

    expect(state.usageSnapshot?.usage_ready).toBe(true)
    expect(state.usageSnapshot?.last_turn_usage.total_tokens).toBe(1700)
    expect(state.usageSnapshot?.context_limit_source).toBe('provider_probe')
  })

  it('stores and resolves confirm requests on the current turn', () => {
    let state = reduceChatState(createInitialChatState(), {
      type: 'sync_runtime',
      snapshot: {
        session_id: 'sess_1',
        status: 'waiting_confirm',
        detail: 'need approval',
        active_tools: [],
        current_mode: 'normal',
        route_reason: '',
        action_risk: 'medium',
        source_profile: 'desktop',
        stream_id: 'stream-1',
        turn_id: 'turn-1',
        updated_at: '2026-04-09T12:00:00Z',
      },
    })

    state = reduceChatState(state, {
      type: 'set_confirm_request',
      payload: {
        requestId: 'confirm-1',
        content: '允许执行高风险操作吗？',
        timeout: 30,
        defaultDecision: false,
      },
    })

    expect(state.confirmRequest?.requestId).toBe('confirm-1')
    expect(state.messages[0]?.confirmRequest?.content).toContain('高风险操作')

    state = reduceChatState(state, {
      type: 'resolve_confirm',
      requestId: 'confirm-1',
      accepted: true,
      turnId: 'turn-1',
    })

    expect(state.confirmRequest).toBeNull()
    expect(state.messages[0]?.confirmResponse?.accepted).toBe(true)
  })

  it('stores and resolves human input requests on the current turn', () => {
    let state = reduceChatState(createInitialChatState(), {
      type: 'sync_runtime',
      snapshot: {
        session_id: 'sess_1',
        status: 'waiting_human_input',
        detail: 'need human input',
        active_tools: [],
        current_mode: 'normal',
        route_reason: '',
        action_risk: 'low',
        source_profile: 'desktop',
        stream_id: 'stream-2',
        turn_id: 'turn-2',
        updated_at: '2026-04-09T12:00:01Z',
      },
    })

    state = reduceChatState(state, {
      type: 'set_human_input_request',
      payload: {
        requestId: 'input-1',
        question: '请选择执行环境',
        options: ['桌面端', '服务端'],
        placeholder: '补充说明',
        timeout: 60,
      },
    })

    expect(state.pendingHumanInput?.requestId).toBe('input-1')
    expect(state.messages[0]?.humanInputRequest?.question).toBe('请选择执行环境')

    state = reduceChatState(state, {
      type: 'resolve_human_input',
      requestId: 'input-1',
      answerText: '桌面端',
      selectedOption: '桌面端',
      turnId: 'turn-2',
    })

    expect(state.pendingHumanInput).toBeNull()
    expect(state.messages[0]?.humanInputResponse?.selectedOption).toBe('桌面端')
  })
})
