import type {
  ChatTurn,
  ClientMessage,
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

export type ChatAction =
  | { type: 'append_user_turn'; turn: ChatTurn }
  | { type: 'append_system_turn'; turn: ChatTurn }
  | { type: 'hydrate_messages'; messages: ClientMessage[] }
  | { type: 'append_client_message'; message: ClientMessage }
  | { type: 'complete_stream_message'; message: ClientMessage; streamId: string; turnId: string }
  | {
      type: 'append_message'
      role: 'assistant'
      content: string
      streamId: string
      turnId: string
      channel: 'answer' | 'reasoning'
      phase: string
      eventId: string
      activeTurnId: string
    }
  | { type: 'append_activity'; activity: TurnActivity; activeTurnId: string }
  | { type: 'sync_runtime'; snapshot: RuntimeStateSnapshot }
  | { type: 'sync_usage'; snapshot: RuntimeUsageSnapshot }
  | { type: 'sync_debug'; snapshot: RuntimeDebugSnapshot }
  | { type: 'set_confirm_request'; payload: ConfirmRequestPayload | null; turnId?: string }
  | { type: 'set_human_input_request'; payload: HumanInputRequestPayload | null; turnId?: string }
  | { type: 'resolve_confirm'; requestId: string; accepted: boolean; turnId?: string }
  | { type: 'resolve_human_input'; requestId: string; answerText: string; selectedOption?: string; turnId?: string }

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
    temporary: false,
  }
}

export function createSystemTurn(
  content: string,
  isError = false,
  attachments: ChatTurn['attachments'] = [],
): ChatTurn {
  return {
    id: `sys-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    streamId: '',
    turnId: '',
    role: 'system',
    content,
    reasoning: '',
    activities: [],
    isStreaming: false,
    createdAt: Date.now(),
    error: isError ? content : undefined,
    attachments,
    temporary: false,
  }
}

function buildMessageError(status: string | undefined, role: ChatTurn['role']): string | undefined {
  if (status !== 'failed') {
    return undefined
  }
  return role === 'assistant' ? 'Assistant response failed.' : 'Message delivery failed.'
}

function findTurnIndex(turns: ChatTurn[], streamId: string, turnId: string): number {
  if (turnId) {
    const byTurnId = turns.findIndex((turn) => turn.turnId === turnId && turn.role === 'assistant')
    if (byTurnId !== -1) {
      return byTurnId
    }
  }
  if (streamId) {
    return turns.findIndex((turn) => turn.streamId === streamId && turn.role === 'assistant')
  }
  return -1
}

function upsertAssistantTurn(turns: ChatTurn[], streamId: string, turnId: string): { turns: ChatTurn[]; index: number } {
  const index = findTurnIndex(turns, streamId, turnId)
  if (index !== -1) {
    return { turns: [...turns], index }
  }

  const newTurn: ChatTurn = {
    id: `turn-${turnId || streamId || Date.now()}`,
    streamId: streamId || '',
    turnId: turnId || '',
    role: 'assistant',
    content: '',
    reasoning: '',
    activities: [],
    isStreaming: true,
    createdAt: Date.now(),
    temporary: false,
  }
  return { turns: [...turns, newTurn], index: turns.length }
}

function trimActivities(turn: ChatTurn): ChatTurn {
  if (turn.activities.length <= MAX_ACTIVITY_ITEMS) {
    return turn
  }
  const trimmedCount = turn.activities.length - RETAINED_ACTIVITY_ITEMS
  return {
    ...turn,
    activities: turn.activities.slice(-RETAINED_ACTIVITY_ITEMS),
    trimmedActivityCount: (turn.trimmedActivityCount || 0) + trimmedCount,
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

function appendSystemTurn(turns: ChatTurn[], nextTurn: ChatTurn): ChatTurn[] {
  const previousTurn = turns[turns.length - 1]
  if (
    previousTurn &&
    previousTurn.role === 'system' &&
    previousTurn.content === nextTurn.content &&
    previousTurn.error === nextTurn.error
  ) {
    return turns
  }
  return [...turns, nextTurn]
}

function hydrateClientMessages(messages: ClientMessage[]): ChatTurn[] {
  return messages.map((message) => ({
    id: message.message_id,
    streamId: '',
    turnId: message.role === 'assistant' ? message.message_id : '',
    role: message.role,
    content: message.content,
    reasoning: '',
    activities: [],
    isStreaming: false,
    createdAt: Date.parse(message.created_at) || Date.now(),
    error: buildMessageError(message.status, message.role),
    temporary: Boolean(message.temporary),
  }))
}

function appendClientMessage(turns: ChatTurn[], message: ClientMessage): ChatTurn[] {
  const logicalTurnId = message.role === 'assistant' ? message.message_id : ''
  const existing = turns.findIndex(
    (turn) =>
      turn.id === message.message_id ||
      (logicalTurnId && turn.turnId === logicalTurnId),
  )
  if (existing !== -1) {
    return turns
  }
  const nextTurn = {
    id: message.message_id,
    streamId: '',
    turnId: logicalTurnId,
    role: message.role,
    content: message.content,
    reasoning: '',
    activities: [],
    isStreaming: false,
    createdAt: Date.parse(message.created_at) || Date.now(),
    error: buildMessageError(message.status, message.role),
    temporary: Boolean(message.temporary),
  }
  if (message.channel === 'short_reply') {
    const last = turns[turns.length - 1]
    if (last?.role === 'assistant' && last.isStreaming && !last.content && !last.reasoning) {
      return [...turns.slice(0, -1), nextTurn, last]
    }
  }
  return [...turns, nextTurn]
}

function completeStreamMessage(turns: ChatTurn[], message: ClientMessage, streamId: string, turnId: string): ChatTurn[] {
  if (message.channel === 'short_reply' || message.temporary) {
    return appendClientMessage(turns, message)
  }
  const index = findTurnIndex(turns, streamId, turnId)
  if (index === -1) {
    return [
      ...turns,
      {
        id: message.message_id,
        streamId: streamId || '',
        turnId: turnId || '',
        role: message.role,
        content: message.content,
        reasoning: '',
        activities: [],
        isStreaming: Boolean(message.temporary),
        createdAt: Date.parse(message.created_at) || Date.now(),
        error: buildMessageError(message.status, message.role),
        temporary: Boolean(message.temporary),
      },
    ]
  }

  const nextTurns = [...turns]
  const current = nextTurns[index]
  const isTemporary = Boolean(message.temporary)
  nextTurns[index] = {
    ...current,
    id: isTemporary ? current.id : message.message_id || current.id,
    streamId: streamId || current.streamId,
    turnId: turnId || current.turnId,
    content: message.content || current.content,
    isStreaming: isTemporary,
    error: buildMessageError(message.status, message.role) || current.error,
    temporary: isTemporary,
  }
  return nextTurns
}

function appendTurnContent(turns: ChatTurn[], action: Extract<ChatAction, { type: 'append_message' }>): ChatTurn[] {
  const { turns: nextTurns, index } = upsertAssistantTurn(turns, action.streamId, action.turnId)
  const current = nextTurns[index]
  nextTurns[index] = {
    ...current,
    content:
      action.channel === 'answer'
        ? current.content + action.content
        : current.content,
    reasoning: action.channel === 'reasoning' ? current.reasoning + action.content : current.reasoning,
    temporary: action.channel === 'answer' ? false : current.temporary,
    isStreaming: true,
  }
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

function toSnapshotTime(snapshot: RuntimeUsageSnapshot | null): number {
  if (!snapshot?.updated_at) {
    return 0
  }
  const timestamp = Date.parse(snapshot.updated_at)
  return Number.isFinite(timestamp) ? timestamp : 0
}

function shouldReplaceUsageSnapshot(
  currentSnapshot: RuntimeUsageSnapshot | null,
  nextSnapshot: RuntimeUsageSnapshot,
): boolean {
  if (!currentSnapshot) {
    return true
  }
  if (currentSnapshot.usage_ready && !nextSnapshot.usage_ready) {
    return false
  }
  if (!currentSnapshot.usage_ready && nextSnapshot.usage_ready) {
    return true
  }
  return toSnapshotTime(nextSnapshot) >= toSnapshotTime(currentSnapshot)
}

export function reduceChatState(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'append_user_turn':
      return withPrunedMessages(state, [...state.messages, action.turn], action.turn.turnId)
    case 'append_system_turn':
      return withPrunedMessages(
        state,
        appendSystemTurn(state.messages, action.turn),
        state.runtimeSnapshot?.turn_id || '',
      )
    case 'hydrate_messages':
      return {
        ...state,
        messages: hydrateClientMessages(action.messages),
        archivedTurnCount: 0,
      }
    case 'append_client_message':
      return withPrunedMessages(
        state,
        appendClientMessage(state.messages, action.message),
        state.runtimeSnapshot?.turn_id || '',
      )
    case 'complete_stream_message':
      return withPrunedMessages(
        state,
        completeStreamMessage(state.messages, action.message, action.streamId, action.turnId),
        action.turnId || state.runtimeSnapshot?.turn_id || '',
      )
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
        confirmRequest:
          action.snapshot.status === 'waiting_confirm'
            ? state.confirmRequest
            : action.snapshot.status === 'idle'
              ? null
              : state.confirmRequest,
        pendingHumanInput:
          action.snapshot.status === 'waiting_human_input'
            ? state.pendingHumanInput
            : action.snapshot.status === 'idle'
              ? null
              : state.pendingHumanInput,
      }
    case 'sync_usage':
      if (!shouldReplaceUsageSnapshot(state.usageSnapshot, action.snapshot)) {
        return state
      }
      return {
        ...state,
        usageSnapshot: action.snapshot,
      }
    case 'sync_debug':
      return {
        ...state,
        runtimeDebugSnapshot: action.snapshot,
      }
    case 'set_confirm_request': {
      const turnId = action.turnId || state.runtimeSnapshot?.turn_id
      const nextMessages = [...state.messages]
      const index = nextMessages.findIndex((message) => message.turnId === turnId)
      if (index !== -1) {
        nextMessages[index] = { ...nextMessages[index], confirmRequest: action.payload }
      }
      return { ...state, messages: nextMessages, confirmRequest: action.payload }
    }
    case 'set_human_input_request': {
      const turnId = action.turnId || state.runtimeSnapshot?.turn_id
      const nextMessages = [...state.messages]
      const index = nextMessages.findIndex((message) => message.turnId === turnId)
      if (index !== -1) {
        nextMessages[index] = { ...nextMessages[index], humanInputRequest: action.payload }
      }
      return { ...state, messages: nextMessages, pendingHumanInput: action.payload }
    }
    case 'resolve_confirm': {
      const nextMessages = [...state.messages]
      const index = nextMessages.findIndex(
        (message) => message.confirmRequest?.requestId === action.requestId || message.turnId === action.turnId,
      )
      if (index !== -1) {
        nextMessages[index] = {
          ...nextMessages[index],
          confirmResponse: { accepted: action.accepted },
        }
      }
      return { ...state, messages: nextMessages, confirmRequest: null }
    }
    case 'resolve_human_input': {
      const nextMessages = [...state.messages]
      const index = nextMessages.findIndex(
        (message) => message.humanInputRequest?.requestId === action.requestId || message.turnId === action.turnId,
      )
      if (index !== -1) {
        nextMessages[index] = {
          ...nextMessages[index],
          humanInputResponse: { answerText: action.answerText, selectedOption: action.selectedOption },
        }
      }
      return { ...state, messages: nextMessages, pendingHumanInput: null }
    }
  }
}
