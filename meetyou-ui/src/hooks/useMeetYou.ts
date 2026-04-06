import { startTransition, useCallback, useEffect, useMemo, useReducer, useRef } from 'react'
import { createSystemTurn, createUserTurn, reduceChatState, createInitialChatState } from '../chatState'
import {
  parseAckEnvelope,
  parseHealthEnvelope,
  parseRuntimeDebugEnvelope,
  parseRuntimeStateEnvelope,
  parseRuntimeUsageEnvelope,
  parseWsPayload,
} from '../protocolClient'
import { createInitialTransportState, reduceTransportState } from '../transportState'
import type {
  AssistantMode,
  InputRequestPayload,
  ThinkingOverride,
  AckPayload,
  RuntimeErrorPayload,
} from '../types'

function buildThinkingOptions(thinkingOverride: ThinkingOverride) {
  if (thinkingOverride === 'default') {
    return undefined
  }

  if (thinkingOverride === 'off') {
    return {
      thinking: {
        enabled: false,
      },
    }
  }

  return {
    thinking: {
      enabled: true,
      effort: thinkingOverride,
    },
  }
}

function createClientMessageId(): string {
  return `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function lastAssistantActivities(turns: ReturnType<typeof createInitialChatState>['messages']) {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index]
    if (turn.role === 'assistant' && turn.activities.length > 0) {
      return turn.activities
    }
  }
  return []
}

function buildAckMessage(ack: AckPayload): string {
  if (ack.action === 'confirm_response') {
    return '确认结果已提交，服务继续执行。'
  }
  if (ack.action === 'input_response') {
    return '补充信息已发送，服务继续执行。'
  }
  return ''
}

function buildTransportError(error: Error): RuntimeErrorPayload {
  return {
    code: 'transport_error',
    category: 'dependency',
    message: error.message || '连接后端失败，请稍后重试',
    retryable: true,
    details: {},
    occurred_at: '',
  }
}

function getAccessToken(): string {
  try {
    return localStorage.getItem('meetyou_access_token') || ''
  } catch {
    return ''
  }
}

async function fetchWithAuth(url: string, init?: RequestInit): Promise<Response> {
  const token = getAccessToken()
  const headers = new Headers(init?.headers)
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  return fetch(url, { ...init, headers })
}

export function useMeetYou(baseUrl: string = 'http://127.0.0.1:8000') {
  const initialSessionIdRef = useRef(`desktop-${Math.random().toString(36).substring(2, 9)}`)
  const sourceIdRef = useRef('desktop-app')
  const [chatState, dispatchChat] = useReducer(reduceChatState, undefined, createInitialChatState)
  const [transportState, dispatchTransport] = useReducer(
    reduceTransportState,
    createInitialTransportState(initialSessionIdRef.current, sourceIdRef.current),
  )

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const debugRefreshTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const seenEventIdsRef = useRef<Set<string>>(new Set())
  const seenEventOrderRef = useRef<string[]>([])
  const activeTurnIdRef = useRef('')

  const sessionId = transportState.sessionId
  const sourceId = transportState.sourceId
  const wsUrl = baseUrl.replace(/^http/, 'ws')

  activeTurnIdRef.current = chatState.runtimeSnapshot?.turn_id || ''

  const rememberEventId = useCallback((eventId?: string) => {
    if (!eventId) {
      return true
    }
    if (seenEventIdsRef.current.has(eventId)) {
      return false
    }

    seenEventIdsRef.current.add(eventId)
    seenEventOrderRef.current.push(eventId)

    if (seenEventOrderRef.current.length > 2000) {
      const oldest = seenEventOrderRef.current.shift()
      if (oldest) {
        seenEventIdsRef.current.delete(oldest)
      }
    }

    return true
  }, [])

  const refreshRuntime = useCallback(async () => {
    if (!sessionId) {
      return
    }

    try {
      const response = await fetchWithAuth(`${baseUrl}/runtime/state?session_id=${encodeURIComponent(sessionId)}`)
      if (!response.ok) {
        return
      }

      const snapshot = parseRuntimeStateEnvelope(await response.json())
      if (!snapshot) {
        return
      }

      startTransition(() => {
        dispatchChat({ type: 'sync_runtime', snapshot })
      })
    } catch (error) {
      console.error('Failed to refresh runtime state:', error)
    }
  }, [baseUrl, sessionId])

  const refreshUsage = useCallback(async () => {
    if (!sessionId) {
      return
    }

    try {
      const response = await fetchWithAuth(
        `${baseUrl}/runtime/usage?session_id=${encodeURIComponent(sessionId)}`,
      )
      if (response.status === 404) {
        return
      }
      if (!response.ok) {
        return
      }

      const snapshot = parseRuntimeUsageEnvelope(await response.json())
      if (!snapshot) {
        return
      }
      startTransition(() => {
        dispatchChat({ type: 'sync_usage', snapshot })
      })
    } catch (error) {
      console.error('Failed to refresh runtime usage:', error)
    }
  }, [baseUrl, sessionId])

  const refreshDebug = useCallback(async () => {
    if (!sessionId) {
      return
    }

    try {
      const response = await fetchWithAuth(
        `${baseUrl}/runtime/debug?session_id=${encodeURIComponent(sessionId)}`,
      )
      if (response.status === 404) {
        startTransition(() => {
          dispatchChat({ type: 'sync_debug', snapshot: null })
        })
        return
      }
      if (!response.ok) {
        return
      }
      const snapshot = parseRuntimeDebugEnvelope(await response.json())
      startTransition(() => {
        dispatchChat({ type: 'sync_debug', snapshot })
      })
    } catch (error) {
      console.error('Failed to refresh runtime debug:', error)
    }
  }, [baseUrl, sessionId])

  const scheduleDebugRefresh = useCallback(() => {
    clearTimeout(debugRefreshTimeoutRef.current)
    debugRefreshTimeoutRef.current = setTimeout(() => {
      void refreshDebug()
    }, 150)
  }, [refreshDebug])

  const refreshHealth = useCallback(async () => {
    try {
      const response = await fetchWithAuth(`${baseUrl}/health`)
      if (!response.ok) {
        return
      }
      const health = parseHealthEnvelope(await response.json())
      if (!health) {
        return
      }
      dispatchTransport({ type: 'health', health })
    } catch (error) {
      console.error('Failed to refresh health:', error)
    }
  }, [baseUrl])

  const applyWsUpdate = useCallback(
    (rawPayload: unknown) => {
      const update = parseWsPayload(rawPayload)
      if ('eventId' in update && update.eventId && !rememberEventId(update.eventId)) {
        return
      }

      switch (update.kind) {
        case 'ignore':
          return
        case 'connection':
          dispatchTransport({ type: 'set_connection_state', connectionState: 'connected' })
          if (update.sessionId) {
            dispatchTransport({ type: 'sync_session', sessionId: update.sessionId })
          }
          return
        case 'ack': {
          dispatchTransport({ type: 'ack', ack: update.ack })
          const message = buildAckMessage(update.ack)
          if (message) {
            startTransition(() => {
              dispatchChat({ type: 'append_system_turn', turn: createSystemTurn(message) })
            })
          }
          return
        }
        case 'error':
          dispatchTransport({ type: 'error', error: update.error })
          startTransition(() => {
            dispatchChat({
              type: 'append_system_turn',
              turn: createSystemTurn(update.error.message || '发生错误', true),
            })
          })
          scheduleDebugRefresh()
          return
        case 'health':
          dispatchTransport({ type: 'health', health: update.health })
          return
        case 'runtime_state':
          startTransition(() => {
            dispatchChat({ type: 'sync_runtime', snapshot: update.snapshot })
          })
          scheduleDebugRefresh()
          return
        case 'runtime_usage':
          startTransition(() => {
            dispatchChat({ type: 'sync_usage', snapshot: update.snapshot })
          })
          scheduleDebugRefresh()
          return
        case 'confirm_request':
          startTransition(() => {
            dispatchChat({ type: 'set_confirm_request', payload: update.payload })
          })
          return
        case 'human_input_request':
          startTransition(() => {
            dispatchChat({ type: 'set_human_input_request', payload: update.payload })
          })
          return
        case 'status':
          startTransition(() => {
            dispatchChat({
              type: 'append_activity',
              activity: update.activity,
              activeTurnId: activeTurnIdRef.current || update.activity.turnId,
            })
          })
          return
        case 'message':
          startTransition(() => {
            dispatchChat({
              type: 'append_message',
              role: update.role,
              content: update.content,
              streamId: update.streamId,
              turnId: update.turnId,
              channel: update.channel,
              phase: update.phase,
              eventId: update.eventId,
              activeTurnId: activeTurnIdRef.current || update.turnId,
            })
          })
      }
    },
    [rememberEventId, scheduleDebugRefresh],
  )

  const connectWs = useCallback(() => {
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return
    }

    clearTimeout(reconnectTimeoutRef.current)
    dispatchTransport({ type: 'set_connection_state', connectionState: 'connecting' })

    let url = `${wsUrl}/ws?session_id=${encodeURIComponent(sessionId)}&source_id=${encodeURIComponent(sourceId)}`
    const token = getAccessToken()
    if (token) {
      url += `&access_token=${encodeURIComponent(token)}`
    }
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (wsRef.current !== ws) {
        ws.close()
        return
      }
      void refreshRuntime()
      void refreshUsage()
      void refreshDebug()
      void refreshHealth()
    }

    ws.onmessage = (event) => {
      if (wsRef.current !== ws) {
        return
      }

      try {
        const data = JSON.parse(event.data)
        applyWsUpdate(data)
      } catch (error) {
        console.error('WS parse error:', error)
      }
    }

    ws.onclose = () => {
      if (wsRef.current !== ws) {
        return
      }

      wsRef.current = null
      dispatchTransport({ type: 'set_connection_state', connectionState: 'disconnected' })
      reconnectTimeoutRef.current = setTimeout(() => {
        if (!wsRef.current) {
          connectWs()
        }
      }, 3000)
    }

    ws.onerror = (error) => {
      if (wsRef.current !== ws) {
        return
      }
      console.error('WS Error:', error)
    }
  }, [applyWsUpdate, refreshDebug, refreshHealth, refreshRuntime, refreshUsage, sessionId, sourceId, wsUrl])

  useEffect(() => {
    connectWs()
    return () => {
      clearTimeout(reconnectTimeoutRef.current)
      clearTimeout(debugRefreshTimeoutRef.current)
      const ws = wsRef.current
      wsRef.current = null
      ws?.close()
    }
  }, [connectWs])

  useEffect(() => {
    if (transportState.connectionState !== 'connected') {
      return
    }

    void refreshRuntime()
    void refreshUsage()
    void refreshDebug()
    void refreshHealth()
  }, [refreshDebug, refreshHealth, refreshRuntime, refreshUsage, sessionId, transportState.connectionState])

  const sendMessage = useCallback(
    async (
      text: string,
      thinkingOverride: ThinkingOverride = 'default',
      preferredMode: AssistantMode = 'normal',
    ) => {
      const content = text.trim()
      if (!content) {
        return
      }

      startTransition(() => {
        dispatchChat({ type: 'append_user_turn', turn: createUserTurn(content) })
      })

      try {
        const requestPayload: InputRequestPayload = {
          content,
          session_id: sessionId,
          source_id: sourceId,
          client_message_id: createClientMessageId(),
          role: 'user',
          preferred_mode: preferredMode === 'auto' ? undefined : preferredMode,
          options: buildThinkingOptions(thinkingOverride),
        }
        const response = await fetchWithAuth(`${baseUrl}/inputs`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestPayload),
        })

        if (!response.ok) {
          const rawError = await response.json().catch(() => null)
          if (rawError?.kind === 'error' && rawError.error) {
            dispatchTransport({ type: 'error', error: rawError.error })
            startTransition(() => {
              dispatchChat({
                type: 'append_system_turn',
                turn: createSystemTurn(rawError.error.message || `HTTP ${response.status}`, true),
              })
            })
            return
          }
          throw new Error(`HTTP ${response.status}`)
        }

        const ack = parseAckEnvelope(await response.json())
        if (ack?.session_id && ack.session_id !== sessionId) {
          dispatchTransport({ type: 'sync_session', sessionId: ack.session_id })
        }
      } catch (error) {
        console.error('Failed to send message via HTTP:', error)
        const transportError = buildTransportError(
          error instanceof Error ? error : new Error('连接后端失败，请稍后重试'),
        )
        dispatchTransport({ type: 'error', error: transportError })
        startTransition(() => {
          dispatchChat({
            type: 'append_system_turn',
            turn: createSystemTurn(transportError.message, true),
          })
        })
      }
    },
    [baseUrl, sessionId, sourceId],
  )

  const sendConfirmResponse = useCallback((requestId: string, accepted: boolean) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          action: 'confirm_response',
          request_id: requestId,
          accepted,
          metadata: { from: 'confirm-dialog' },
        }),
      )
    }
    startTransition(() => {
      dispatchChat({ type: 'set_confirm_request', payload: null })
    })
  }, [])

  const sendHumanInputResponse = useCallback(
    (requestId: string, answerText: string, selectedOption: string | null = null) => {
      const normalizedAnswer = answerText.trim() || selectedOption || ''
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            action: 'input_response',
            request_id: requestId,
            answer_text: normalizedAnswer,
            selected_option: selectedOption,
            metadata: { from: 'human-input-panel' },
          }),
        )
      }
      if (normalizedAnswer) {
        startTransition(() => {
          dispatchChat({
            type: 'append_user_turn',
            turn: createUserTurn(normalizedAnswer, chatState.runtimeSnapshot?.turn_id || ''),
          })
        })
      }
      startTransition(() => {
        dispatchChat({ type: 'set_human_input_request', payload: null })
      })
    },
    [chatState.runtimeSnapshot?.turn_id],
  )

  const sendControlCommand = useCallback(
    (
      action: 'stop' | 'append_guidance' | 'regenerate' | 'rollback',
      params: { guidance?: string; checkpoint_id?: string; turn_id?: string; stream_id?: string } = {},
    ) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            action,
            ...params,
            metadata: { from: 'ui-control' },
          }),
        )
      }
    },
    [],
  )

  const turnActivities = useMemo(() => {
    if (chatState.runtimeSnapshot?.turn_id) {
      const currentTurn = chatState.messages.find((message) => message.turnId === chatState.runtimeSnapshot?.turn_id)
      if (currentTurn) {
        return currentTurn.activities
      }
    }
    return lastAssistantActivities(chatState.messages)
  }, [chatState.messages, chatState.runtimeSnapshot?.turn_id])

  return {
    messages: chatState.messages,
    sessionId,
    connectionState: transportState.connectionState,
    connected: transportState.connectionState === 'connected',
    runtimeSnapshot: chatState.runtimeSnapshot,
    usageSnapshot: chatState.usageSnapshot,
    runtimeDebugSnapshot: chatState.runtimeDebugSnapshot,
    turnActivities,
    confirmRequest: chatState.confirmRequest,
    pendingHumanInput: chatState.pendingHumanInput,
    healthSnapshot: transportState.healthSnapshot,
    lastAck: transportState.lastAck,
    lastError: transportState.lastError,
    archivedTurnCount: chatState.archivedTurnCount,
    sendMessage,
    sendConfirmResponse,
    sendHumanInputResponse,
    sendControlCommand,
    refreshRuntime,
    refreshUsage,
    refreshDebug,
    refreshHealth,
    baseUrl,
  }
}
