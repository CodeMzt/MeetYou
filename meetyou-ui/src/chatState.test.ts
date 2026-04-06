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
})
