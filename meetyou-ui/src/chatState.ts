import type {
  ChatTurn,
  ConfirmRequestPayload,
  HumanInputRequestPayload,
  RuntimeDebugSnapshot,
  RuntimeStateSnapshot,
  RuntimeUsageSnapshot,
  TurnActivity,
} from './types'

const MAX_ACTIVITY_ITEMS = 48
const RETAINED_ACTIVITY_ITEMS = 32
const MAX_VISIBLE_TURNS = 160
const RETAINED_VISIBLE_TURNS = 120

export interface ChatState {
  messages: ChatTurn[]
  runtimeSnapshot: RuntimeStateSnapshot | null
  usageSnapshot: RuntimeUsageSnapshot | null
  runtimeDebugSnapshot: RuntimeDebugSnapshot | null
  confirmRequest: ConfirmRequestPayload | null
  pendingHumanInput: HumanInputRequestPayload | null
  archivedTurnCount: number
}

export type ChatAction =
  | { type: 'append_user_turn'; turn: ChatTurn }
  | { type: 'append_system_turn'; turn: ChatTurn }
  | {
      type: 'append_message'
      role: string
      content: string
      streamId: string
      turnId: string
      channel: string
      phase: string
      eventId: string
      activeTurnId: string
    }
  | { type: 'append_activity'; activity: TurnActivity; activeTurnId: string }
  | { type: 'sync_runtime'; snapshot: RuntimeStateSnapshot }
  | { type: 'sync_usage'; snapshot: RuntimeUsageSnapshot }
  | { type: 'sync_debug'; snapshot: RuntimeDebugSnapshot | null }
  | { type: 'set_confirm_request'; payload: ConfirmRequestPayload | null }
  | { type: 'set_human_input_request'; payload: HumanInputRequestPayload | null }

export function createInitialChatState(): ChatState {
  return {
    messages: [],
    runtimeSnapshot: null,
    usageSnapshot: null,
    runtimeDebugSnapshot: null,
    confirmRequest: null,
    pendingHumanInput: null,
    archivedTurnCount: 0,
  }
}

export function createAssistantTurn(streamId: string, turnId: string, role: ChatTurn['role'] = 'assistant'): ChatTurn {
  return {
    id: turnId || streamId || `assistant-${Date.now()}`,
    streamId,
    turnId,
    role,
    content: '',
    reasoning: '',
    activities: [],
    isStreaming: true,
    createdAt: Date.now(),
    trimmedActivityCount: 0,
  }
}

export function createUserTurn(content: string, turnId = ''): ChatTurn {
  return {
    id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    streamId: '',
    turnId,
    role: 'user',
    content,
    reasoning: '',
    activities: [],
    isStreaming: false,
    createdAt: Date.now(),
    trimmedActivityCount: 0,
  }
}

export function createSystemTurn(content: string, isError = false): ChatTurn {
  return {
    id: `system-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    streamId: '',
    turnId: '',
    role: 'system',
    content,
    reasoning: '',
    activities: [],
    isStreaming: false,
    createdAt: Date.now(),
    trimmedActivityCount: 0,
    error: isError ? content : undefined,
  }
}

function findTurnIndex(turns: ChatTurn[], streamId: string, turnId: string): number {
  if (turnId) {
    const byTurnId = turns.findIndex((turn) => turn.turnId === turnId)
    if (byTurnId !== -1) {
      return byTurnId
    }
  }

  if (streamId) {
    return turns.findIndex((turn) => turn.streamId === streamId)
  }

  return -1
}

function upsertAssistantTurn(
  turns: ChatTurn[],
  streamId: string,
  turnId: string,
  role: ChatTurn['role'] = 'assistant',
): { turns: ChatTurn[]; index: number } {
  const currentIndex = findTurnIndex(turns, streamId, turnId)
  if (currentIndex !== -1) {
    const nextTurns = [...turns]
    const current = nextTurns[currentIndex]
    nextTurns[currentIndex] = {
      ...current,
      streamId: current.streamId || streamId,
      turnId: current.turnId || turnId,
      role: current.role || role,
    }
    return { turns: nextTurns, index: currentIndex }
  }

  const nextTurns = [...turns, createAssistantTurn(streamId, turnId, role)]
  return { turns: nextTurns, index: nextTurns.length - 1 }
}

function trimActivities(turn: ChatTurn): ChatTurn {
  if (turn.activities.length <= MAX_ACTIVITY_ITEMS) {
    return turn
  }
  const removedCount = turn.activities.length - RETAINED_ACTIVITY_ITEMS
  return {
    ...turn,
    activities: turn.activities.slice(-RETAINED_ACTIVITY_ITEMS),
    trimmedActivityCount: (turn.trimmedActivityCount ?? 0) + removedCount,
  }
}

function pruneTurns(turns: ChatTurn[], activeTurnId: string): { turns: ChatTurn[]; archivedCount: number } {
  if (turns.length <= MAX_VISIBLE_TURNS) {
    return { turns, archivedCount: 0 }
  }
  const keepIds = new Set(turns.slice(-RETAINED_VISIBLE_TURNS).map((turn) => turn.id))
  if (activeTurnId) {
    turns.forEach((turn) => {
      if (turn.turnId === activeTurnId) {
        keepIds.add(turn.id)
      }
    })
  }
  const nextTurns = turns.filter((turn) => keepIds.has(turn.id))
  return {
    turns: nextTurns,
    archivedCount: Math.max(0, turns.length - nextTurns.length),
  }
}

function appendTurnContent(
  turns: ChatTurn[],
  action: Extract<ChatAction, { type: 'append_message' }>,
): ChatTurn[] {
  const { turns: nextTurns, index } = upsertAssistantTurn(turns, action.streamId, action.turnId, 'assistant')
  const current = nextTurns[index]
  const nextTurn = { ...current }

  if (action.phase === 'start') {
    nextTurn.isStreaming = true
  }

  if (action.content) {
    if (action.channel === 'reasoning') {
      nextTurn.reasoning = `${nextTurn.reasoning}${action.content}`
    } else {
      nextTurn.content = `${nextTurn.content}${action.content}`
    }
  }

  if (action.phase === 'end' || action.phase === 'error') {
    nextTurn.isStreaming = false
    if (action.phase === 'error' && action.content) {
      nextTurn.error = action.content
    }
  }

  nextTurns[index] = nextTurn
  return nextTurns
}

function attachActivity(turns: ChatTurn[], activity: TurnActivity): ChatTurn[] {
  const { turns: nextTurns, index } = upsertAssistantTurn(turns, activity.streamId, activity.turnId)
  const current = nextTurns[index]
  if (current.activities.some((item) => item.id === activity.id)) {
    return nextTurns
  }

  nextTurns[index] = trimActivities({
    ...current,
    activities: [...current.activities, activity],
  })
  return nextTurns
}

function syncRuntimeToTurns(turns: ChatTurn[], snapshot: RuntimeStateSnapshot): ChatTurn[] {
  if (!snapshot.turn_id && !snapshot.stream_id) {
    return turns
  }

  const shouldCreateTurn =
    snapshot.status !== 'idle' &&
    snapshot.status !== 'initializing' &&
    snapshot.status !== 'heartbeat' &&
    snapshot.status !== 'shutting_down'

  const index = findTurnIndex(turns, snapshot.stream_id, snapshot.turn_id)
  if (index === -1 && !shouldCreateTurn) {
    return turns
  }

  const { turns: nextTurns, index: ensuredIndex } = upsertAssistantTurn(
    turns,
    snapshot.stream_id,
    snapshot.turn_id,
  )
  const current = nextTurns[ensuredIndex]
  nextTurns[ensuredIndex] = {
    ...current,
    streamId: snapshot.stream_id || current.streamId,
    turnId: snapshot.turn_id || current.turnId,
    isStreaming: snapshot.status !== 'idle' && snapshot.status !== 'error',
    error: snapshot.status === 'error' ? snapshot.detail : current.error,
  }
  return nextTurns
}

function withPrunedMessages(state: ChatState, messages: ChatTurn[], activeTurnId: string): ChatState {
  const pruned = pruneTurns(messages, activeTurnId)
  return {
    ...state,
    messages: pruned.turns,
    archivedTurnCount: state.archivedTurnCount + pruned.archivedCount,
  }
}

export function reduceChatState(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'append_user_turn':
      return withPrunedMessages(state, [...state.messages, action.turn], action.turn.turnId)
    case 'append_system_turn':
      return withPrunedMessages(state, [...state.messages, action.turn], state.runtimeSnapshot?.turn_id || '')
    case 'append_message':
      return withPrunedMessages(
        state,
        appendTurnContent(state.messages, action),
        action.activeTurnId,
      )
    case 'append_activity':
      return withPrunedMessages(
        state,
        attachActivity(state.messages, action.activity),
        action.activeTurnId,
      )
    case 'sync_runtime':
      return {
        ...withPrunedMessages(
          state,
          syncRuntimeToTurns(state.messages, action.snapshot),
          action.snapshot.turn_id,
        ),
        runtimeSnapshot: action.snapshot,
        confirmRequest: action.snapshot.status === 'waiting_confirm' ? state.confirmRequest : null,
        pendingHumanInput:
          action.snapshot.status === 'waiting_human_input' ? state.pendingHumanInput : null,
      }
    case 'sync_usage':
      return {
        ...state,
        usageSnapshot: action.snapshot,
      }
    case 'sync_debug':
      return {
        ...state,
        runtimeDebugSnapshot: action.snapshot,
      }
    case 'set_confirm_request':
      return {
        ...state,
        confirmRequest: action.payload,
      }
    case 'set_human_input_request':
      return {
        ...state,
        pendingHumanInput: action.payload,
      }
    default:
      return state
  }
}
