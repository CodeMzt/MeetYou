import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  AssistantMode,
  ChatTurn,
  ConfirmRequestPayload,
  ConnectionState,
  HumanInputRequestPayload,
  InputRequestPayload,
  RuntimeStateSnapshot,
  RuntimeUsageSnapshot,
  ThinkingOverride,
  TurnActivity,
} from '../types'

interface RuntimeStateResponse {
  session_state: RuntimeStateSnapshot | null
}

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

function getToolNames(metadata: Record<string, unknown>): string[] {
  const toolNames = metadata.tool_names
  if (!Array.isArray(toolNames)) {
    return []
  }

  return toolNames.filter((item): item is string => typeof item === 'string')
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

function createAssistantTurn(streamId: string, turnId: string): ChatTurn {
  return {
    id: turnId || streamId || `assistant-${Date.now()}`,
    streamId,
    turnId,
    role: 'assistant',
    content: '',
    reasoning: '',
    activities: [],
    isStreaming: true,
    createdAt: Date.now(),
  }
}

function createUserTurn(content: string, turnId = ''): ChatTurn {
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
  }
}

function createClientMessageId(): string {
  return `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function upsertAssistantTurn(
  turns: ChatTurn[],
  streamId: string,
  turnId: string,
): { turns: ChatTurn[]; index: number } {
  const currentIndex = findTurnIndex(turns, streamId, turnId)
  if (currentIndex !== -1) {
    const nextTurns = [...turns]
    const current = nextTurns[currentIndex]
    nextTurns[currentIndex] = {
      ...current,
      streamId: current.streamId || streamId,
      turnId: current.turnId || turnId,
    }
    return { turns: nextTurns, index: currentIndex }
  }

  const nextTurns = [...turns, createAssistantTurn(streamId, turnId)]
  return { turns: nextTurns, index: nextTurns.length - 1 }
}

function appendTurnContent(
  turns: ChatTurn[],
  streamId: string,
  turnId: string,
  channel: string,
  phase: string,
  content: string,
): ChatTurn[] {
  const { turns: nextTurns, index } = upsertAssistantTurn(turns, streamId, turnId)
  const current = nextTurns[index]
  const nextTurn = { ...current }

  if (phase === 'start') {
    nextTurn.isStreaming = true
  }

  if (content) {
    if (channel === 'reasoning') {
      nextTurn.reasoning = `${nextTurn.reasoning}${content}`
    } else {
      nextTurn.content = `${nextTurn.content}${content}`
    }
  }

  if (phase === 'end' || phase === 'error') {
    nextTurn.isStreaming = false
    if (phase === 'error' && content) {
      nextTurn.error = content
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

  nextTurns[index] = {
    ...current,
    activities: [...current.activities, activity],
  }
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

function createSystemTurn(content: string, isError = false): ChatTurn {
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
    error: isError ? content : undefined,
  }
}

function lastAssistantActivities(turns: ChatTurn[]): TurnActivity[] {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index]
    if (turn.role === 'assistant' && turn.activities.length > 0) {
      return turn.activities
    }
  }
  return []
}

export function useMeetYou(baseUrl: string = 'http://127.0.0.1:8000') {
  const [messages, setMessages] = useState<ChatTurn[]>([])
  const [sessionId, setSessionId] = useState<string>(
    `desktop-${Math.random().toString(36).substring(2, 9)}`,
  )
  const [sourceId] = useState('desktop-app')
  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting')
  const [runtimeSnapshot, setRuntimeSnapshot] = useState<RuntimeStateSnapshot | null>(null)
  const [usageSnapshot, setUsageSnapshot] = useState<RuntimeUsageSnapshot | null>(null)
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequestPayload | null>(null)
  const [pendingHumanInput, setPendingHumanInput] = useState<HumanInputRequestPayload | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const seenEventIdsRef = useRef<Set<string>>(new Set())
  const seenEventOrderRef = useRef<string[]>([])

  const wsUrl = baseUrl.replace(/^http/, 'ws')

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
      const response = await fetch(
        `${baseUrl}/runtime/state?session_id=${encodeURIComponent(sessionId)}`,
      )
      if (!response.ok) {
        return
      }

      const data: RuntimeStateResponse = await response.json()
      if (!data.session_state) {
        return
      }

      setRuntimeSnapshot(data.session_state)
      startTransition(() => {
        setMessages((prev) => syncRuntimeToTurns(prev, data.session_state as RuntimeStateSnapshot))
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
      const response = await fetch(
        `${baseUrl}/runtime/usage?session_id=${encodeURIComponent(sessionId)}`,
      )
      if (response.status === 404) {
        setUsageSnapshot(null)
        return
      }
      if (!response.ok) {
        return
      }

      const data: RuntimeUsageSnapshot = await response.json()
      setUsageSnapshot(data)
    } catch (error) {
      console.error('Failed to refresh runtime usage:', error)
    }
  }, [baseUrl, sessionId])

  const connectWs = useCallback(() => {
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return
    }

    clearTimeout(reconnectTimeoutRef.current)
    setConnectionState('connecting')

    const url = `${wsUrl}/ws?session_id=${encodeURIComponent(sessionId)}&source_id=${encodeURIComponent(sourceId)}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (wsRef.current !== ws) {
        ws.close()
        return
      }
      setConnectionState('connected')
      void refreshRuntime()
      void refreshUsage()
    }

    ws.onmessage = (event) => {
      if (wsRef.current !== ws) {
        return
      }

      try {
        const data = JSON.parse(event.data)
        if (data.schema !== 'meetyou.ws.v1') {
          return
        }

        if (data.kind === 'connection' && data.connection?.session_id) {
          if (data.connection.session_id !== sessionId) {
            setSessionId(data.connection.session_id)
          }
          return
        }

        if (data.kind !== 'event') {
          return
        }

        const rawEvent = data.event ?? {}
        if (!rememberEventId(rawEvent.event_id)) {
          return
        }

        const rawStream = data.stream ?? {}
        const streamId = typeof rawStream.id === 'string' ? rawStream.id : ''
        const streamPhase = typeof rawStream.phase === 'string' ? rawStream.phase : ''
        const streamChannel = typeof rawStream.channel === 'string' ? rawStream.channel : ''
        const rawMetadata = rawEvent.metadata ?? {}
        const metadata: Record<string, unknown> =
          rawMetadata && typeof rawMetadata === 'object' ? rawMetadata : {}
        const turnId = typeof metadata.turn_id === 'string' ? metadata.turn_id : ''
        const eventType = typeof rawEvent.type === 'string' ? rawEvent.type : ''
        const content =
          typeof rawEvent.content === 'string'
            ? rawEvent.content
            : rawEvent.content == null
              ? ''
              : JSON.stringify(rawEvent.content)

        if (eventType === 'confirm_request') {
          const confirm = data.confirm ?? {}
          setConfirmRequest({
            requestId: confirm.request_id,
            content,
            timeout: confirm.timeout,
          })
          return
        }

        if (eventType === 'human_input_request') {
          const inputRequest = data.input_request ?? {}
          const options = Array.isArray(inputRequest.options)
            ? inputRequest.options.filter((item: unknown): item is string => typeof item === 'string')
            : []
          setPendingHumanInput({
            requestId: typeof inputRequest.request_id === 'string' ? inputRequest.request_id : '',
            question:
              typeof inputRequest.question === 'string' && inputRequest.question
                ? inputRequest.question
                : content,
            options,
            placeholder: typeof inputRequest.placeholder === 'string' ? inputRequest.placeholder : '',
            timeout: typeof inputRequest.timeout === 'number' ? inputRequest.timeout : undefined,
          })
          return
        }

        if (eventType === 'runtime_status' && rawEvent.content && typeof rawEvent.content === 'object') {
          const snapshot = rawEvent.content as RuntimeStateSnapshot
          setRuntimeSnapshot(snapshot)
          startTransition(() => {
            setMessages((prev) => syncRuntimeToTurns(prev, snapshot))
          })
          return
        }

        if (eventType === 'usage' && rawEvent.content && typeof rawEvent.content === 'object') {
          setUsageSnapshot(rawEvent.content as RuntimeUsageSnapshot)
          return
        }

        if (eventType === 'status') {
          const activity: TurnActivity = {
            id: rawEvent.event_id || `${turnId || streamId || 'activity'}-${Date.now()}`,
            turnId,
            streamId,
            phase:
              typeof metadata.activity_phase === 'string'
                ? metadata.activity_phase
                : typeof metadata.search_phase === 'string'
                  ? metadata.search_phase
                  : 'status',
            content,
            activityKind:
              typeof metadata.activity_kind === 'string' ? metadata.activity_kind : 'tool_chain',
            toolNames: getToolNames(metadata),
            metadata,
            createdAt: Date.now(),
          }

          startTransition(() => {
            setMessages((prev) => attachActivity(prev, activity))
          })
          return
        }

        if (eventType === 'message' || eventType === 'reasoning') {
          if (streamId) {
            startTransition(() => {
              setMessages((prev) =>
                appendTurnContent(
                  prev,
                  streamId,
                  turnId,
                  streamChannel || (eventType === 'reasoning' ? 'reasoning' : 'answer'),
                  streamPhase || 'chunk',
                  content,
                ),
              )
            })
            return
          }

          startTransition(() => {
            setMessages((prev) => [
              ...prev,
              {
                id: rawEvent.event_id || `assistant-${Date.now()}`,
                streamId: '',
                turnId,
                role: rawEvent.role || 'assistant',
                content: eventType === 'reasoning' ? '' : content,
                reasoning: eventType === 'reasoning' ? content : '',
                activities: [],
                isStreaming: false,
                createdAt: Date.now(),
              },
            ])
          })
          return
        }

        if (eventType === 'error') {
          startTransition(() => {
            setMessages((prev) => [...prev, createSystemTurn(content || '发生错误', true)])
          })
        }
      } catch (error) {
        console.error('WS parse error:', error)
      }
    }

    ws.onclose = () => {
      if (wsRef.current !== ws) {
        return
      }

      wsRef.current = null
      setConnectionState('disconnected')
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
  }, [baseUrl, rememberEventId, refreshRuntime, refreshUsage, sessionId, sourceId, wsUrl])

  useEffect(() => {
    connectWs()
    return () => {
      clearTimeout(reconnectTimeoutRef.current)
      const ws = wsRef.current
      wsRef.current = null
      ws?.close()
    }
  }, [connectWs])

  useEffect(() => {
    if (connectionState !== 'connected') {
      return
    }

    void refreshRuntime()
    void refreshUsage()
  }, [connectionState, refreshRuntime, refreshUsage, sessionId])

  useEffect(() => {
    if (!runtimeSnapshot) {
      return
    }
    if (runtimeSnapshot.status !== 'waiting_confirm') {
      setConfirmRequest(null)
    }
    if (runtimeSnapshot.status !== 'waiting_human_input') {
      setPendingHumanInput(null)
    }
  }, [runtimeSnapshot?.status])

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

      setMessages((prev) => [...prev, createUserTurn(content)])

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
        const response = await fetch(`${baseUrl}/inputs`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestPayload),
        })

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }

        const data = await response.json()
        if (data.session_id && data.session_id !== sessionId) {
          setSessionId(data.session_id)
        }
      } catch (error) {
        console.error('Failed to send message via HTTP:', error)
        setMessages((prev) => [...prev, createSystemTurn('连接后端失败，请稍后重试', true)])
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
    setConfirmRequest(null)
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
          setMessages((prev) => [...prev, createUserTurn(normalizedAnswer, runtimeSnapshot?.turn_id || '')])
        })
      }
      setPendingHumanInput(null)
    },
    [runtimeSnapshot?.turn_id],
  )

  const turnActivities = useMemo(() => {
    if (runtimeSnapshot?.turn_id) {
      const currentTurn = messages.find((message) => message.turnId === runtimeSnapshot.turn_id)
      if (currentTurn) {
        return currentTurn.activities
      }
    }
    return lastAssistantActivities(messages)
  }, [messages, runtimeSnapshot])

  return {
    messages,
    sessionId,
    connectionState,
    connected: connectionState === 'connected',
    runtimeSnapshot,
    usageSnapshot,
    turnActivities,
    confirmRequest,
    pendingHumanInput,
    sendMessage,
    sendConfirmResponse,
    sendHumanInputResponse,
    refreshRuntime,
    refreshUsage,
    baseUrl,
  }
}
