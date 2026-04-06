import type { AckPayload, ConnectionState, RuntimeErrorPayload, RuntimeHealthSnapshot } from './types'

export interface TransportState {
  sessionId: string
  sourceId: string
  connectionState: ConnectionState
  healthSnapshot: RuntimeHealthSnapshot | null
  lastAck: AckPayload | null
  lastError: RuntimeErrorPayload | null
}

export type TransportAction =
  | { type: 'set_connection_state'; connectionState: ConnectionState }
  | { type: 'sync_session'; sessionId: string }
  | { type: 'ack'; ack: AckPayload }
  | { type: 'error'; error: RuntimeErrorPayload }
  | { type: 'health'; health: RuntimeHealthSnapshot }

export function createInitialTransportState(sessionId: string, sourceId: string): TransportState {
  return {
    sessionId,
    sourceId,
    connectionState: 'connecting',
    healthSnapshot: null,
    lastAck: null,
    lastError: null,
  }
}

export function reduceTransportState(state: TransportState, action: TransportAction): TransportState {
  switch (action.type) {
    case 'set_connection_state':
      return {
        ...state,
        connectionState: action.connectionState,
      }
    case 'sync_session':
      if (!action.sessionId || action.sessionId === state.sessionId) {
        return state
      }
      return {
        ...state,
        sessionId: action.sessionId,
      }
    case 'ack':
      return {
        ...state,
        lastAck: action.ack,
      }
    case 'error':
      return {
        ...state,
        lastError: action.error,
      }
    case 'health':
      return {
        ...state,
        healthSnapshot: action.health,
      }
    default:
      return state
  }
}
