import { startTransition, useCallback, useEffect, useMemo, useReducer, useRef } from 'react'
import { fetchRuntimeUsageSnapshot, listThreadMessages, sendRuntimeMessage, submitRuntimeConfirmResponse, submitRuntimeHumanInputResponse } from '../../runtimeApi'
import { createInitialChatState, createSystemTurn, reduceChatState } from '../../chatState'
import { parseEndpointWsPayload } from '../../protocolClient'
import type { EndpointContext } from './useEndpointContext'
import type { AckPayload, AssistantMode, ThinkingOverride, ApprovalDisplayModel } from '../../types'

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

function createEndpointRequestId(): string {
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

type BufferedDelta = {
  content: string
  streamId: string
  turnId: string
  channel: 'answer' | 'reasoning'
  phase: string
}

export function useChatSession(
  baseUrl: string,
  endpointContext: EndpointContext | null,
  sessionId: string,
  endpointId: string,
  sendEndpointWsCommand: (payload: Record<string, unknown>) => boolean,
  dispatchTransport: any,
  initializeEndpointContext: () => Promise<EndpointContext>
) {
  const [chatState, dispatchChat] = useReducer(reduceChatState, undefined, createInitialChatState)
  const activeTurnIdRef = useRef('')
  const deltaBufferRef = useRef<Map<string, BufferedDelta>>(new Map())
  const deltaFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  activeTurnIdRef.current = chatState.runtimeSnapshot?.turn_id || ''

  const loadThreadHistory = useCallback(
    async (threadId: string) => {
      try {
        const messages = await listThreadMessages(baseUrl, threadId)
        startTransition(() => {
          dispatchChat({ type: 'hydrate_messages', messages })
        })
      } catch (error) {
        console.error('加载会话历史失败:', error)
      }
    },
    [baseUrl],
  )

  const hydrateRuntimeUsage = useCallback(
    async (targetSessionId: string) => {
      if (!targetSessionId) {
        return
      }
      try {
        const snapshot = await fetchRuntimeUsageSnapshot(baseUrl, targetSessionId)
        startTransition(() => {
          dispatchChat({ type: 'sync_usage', snapshot })
        })
      } catch (error) {
        console.warn('同步运行用量快照失败:', error)
      }
    },
    [baseUrl],
  )

  useEffect(() => {
    if (!endpointContext?.session.session_id) {
      return
    }
    void hydrateRuntimeUsage(endpointContext.session.session_id)
  }, [endpointContext?.session.session_id, hydrateRuntimeUsage])

  const flushBufferedDeltas = useCallback(() => {
    if (deltaFlushTimerRef.current) {
      clearTimeout(deltaFlushTimerRef.current)
      deltaFlushTimerRef.current = null
    }
    const buffered = Array.from(deltaBufferRef.current.values())
    deltaBufferRef.current.clear()
    if (buffered.length === 0) {
      return
    }
    startTransition(() => {
      for (const item of buffered) {
        dispatchChat({
          type: 'append_message',
          role: 'assistant',
          content: item.content,
          streamId: item.streamId,
          turnId: item.turnId,
          channel: item.channel,
          phase: item.phase,
          eventId: `${item.channel}:${item.streamId}:${item.turnId}:${item.content.length}:${Date.now()}`,
          activeTurnId: activeTurnIdRef.current || item.turnId,
        })
      }
    })
  }, [])

  const scheduleDeltaFlush = useCallback(() => {
    if (deltaFlushTimerRef.current) {
      return
    }
    deltaFlushTimerRef.current = setTimeout(flushBufferedDeltas, 50)
  }, [flushBufferedDeltas])

  useEffect(() => {
    return () => {
      if (deltaFlushTimerRef.current) {
        clearTimeout(deltaFlushTimerRef.current)
        deltaFlushTimerRef.current = null
      }
      deltaBufferRef.current.clear()
    }
  }, [])

  const approvalDisplay = useMemo((): ApprovalDisplayModel | null => {
    if (!chatState.confirmRequest) return null
    return {
      requestId: chatState.confirmRequest.requestId,
      title: '请求确认',
      content: chatState.confirmRequest.content,
      timeoutSeconds: chatState.confirmRequest.timeout,
      defaultDecision: chatState.confirmRequest.defaultDecision,
      isBlocking: true,
    }
  }, [chatState.confirmRequest])

  const turnActivities = useMemo(() => {
    if (chatState.runtimeSnapshot?.turn_id) {
      const currentTurn = chatState.messages.find((message) => message.turnId === chatState.runtimeSnapshot?.turn_id)
      if (currentTurn) {
        return currentTurn.activities
      }
    }
    return lastAssistantActivities(chatState.messages)
  }, [chatState.messages, chatState.runtimeSnapshot?.turn_id])

  const sendMessage = useCallback(
    async (
      text: string,
      thinkingOverride: ThinkingOverride = 'default',
      preferredMode: AssistantMode = 'general',
    ) => {
      const content = text.trim()
      if (!content) {
        return
      }

      try {
        const context = endpointContext ?? (await initializeEndpointContext())
        const message = await sendRuntimeMessage(baseUrl, {
          thread_id: context.threadId,
          active_workspace_id: context.workspace.workspace_id,
          workspace_id: context.workspace.workspace_id,
          endpoint_id: context.endpointId,
          session_id: context.session.session_id,
          endpoint_type: 'electron',
          display_name: '桌面应用',
          role: 'user',
          content,
          endpoint_message_id: createEndpointRequestId(),
          preferred_mode: preferredMode,
          options: buildThinkingOptions(thinkingOverride),
        })
        startTransition(() => {
          dispatchChat({ type: 'append_runtime_message', message })
        })
      } catch (error) {
        console.error('通过端点 API 发送消息失败:', error)
        const transportError = {
          code: 'transport_error',
          category: 'dependency' as const,
          message: error instanceof Error ? error.message : '连接后端失败，请稍后重试',
          retryable: true,
          details: {},
          occurred_at: '',
        }
        dispatchTransport({ type: 'error', error: transportError })
        startTransition(() => {
          dispatchChat({
            type: 'append_system_turn',
            turn: createSystemTurn(transportError.message, true),
          })
        })
      }
    },
    [baseUrl, endpointContext, initializeEndpointContext, dispatchTransport],
  )

  const sendConfirmResponse = useCallback(async (requestId: string, accepted: boolean, approvalId?: string) => {
    const turnId = activeTurnIdRef.current
    const resolvedSessionId = endpointContext?.session.session_id || sessionId
    try {
      await submitRuntimeConfirmResponse(baseUrl, resolvedSessionId, {
        accepted,
        request_id: requestId,
        endpoint_id: endpointId,
      })
      startTransition(() => {
        dispatchChat({ type: 'resolve_confirm', requestId, accepted, turnId })
      })
      return
    } catch {
      const sent = sendEndpointWsCommand({
        action: 'confirm_response',
        session_id: resolvedSessionId,
        request_id: requestId,
        accepted,
        endpoint_id: endpointId,
        metadata: {
          from: 'confirm-dialog',
          ...(approvalId ? { approval_id: approvalId } : {}),
        },
      })
      if (!sent) {
        const error = {
          code: 'transport_error',
          category: 'dependency' as const,
          message: '交互通道未连接，无法提交确认结果',
          retryable: true,
          details: {},
          occurred_at: '',
        }
        dispatchTransport({ type: 'error', error })
        startTransition(() => {
          dispatchChat({ type: 'append_system_turn', turn: createSystemTurn(error.message, true) })
        })
        return
      }
      startTransition(() => {
        dispatchChat({ type: 'resolve_confirm', requestId, accepted, turnId })
      })
    }
  }, [baseUrl, endpointContext?.session.session_id, endpointId, sendEndpointWsCommand, sessionId, dispatchTransport])

  const sendHumanInputResponse = useCallback(
    async (requestId: string, answerText: string, selectedOption?: string) => {
      const normalizedAnswer = answerText.trim() || selectedOption || ''
      const turnId = activeTurnIdRef.current
      const resolvedSessionId = endpointContext?.session.session_id || sessionId
      try {
        await submitRuntimeHumanInputResponse(baseUrl, resolvedSessionId, {
          request_id: requestId,
          answer_text: normalizedAnswer,
          selected_option: selectedOption,
          endpoint_id: endpointId,
        })
        startTransition(() => {
          dispatchChat({
            type: 'resolve_human_input',
            requestId,
            answerText: normalizedAnswer,
            selectedOption,
            turnId,
          })
        })
        return
      } catch {
        const sent = sendEndpointWsCommand({
          action: 'input_response',
          session_id: resolvedSessionId,
          request_id: requestId,
          answer_text: normalizedAnswer,
          selected_option: selectedOption,
          endpoint_id: endpointId,
          metadata: { from: 'human-input-panel' },
        })
        if (!sent) {
          const error = {
            code: 'transport_error',
            category: 'dependency' as const,
            message: '交互通道未连接，无法提交补充信息',
            retryable: true,
            details: {},
            occurred_at: '',
          }
          dispatchTransport({ type: 'error', error })
          startTransition(() => {
            dispatchChat({ type: 'append_system_turn', turn: createSystemTurn(error.message, true) })
          })
          return
        }
        startTransition(() => {
          dispatchChat({
            type: 'resolve_human_input',
            requestId,
            answerText: normalizedAnswer,
            selectedOption,
            turnId,
          })
        })
      }
    },
    [baseUrl, endpointContext?.session.session_id, endpointId, sendEndpointWsCommand, sessionId, dispatchTransport],
  )

  const sendControlCommand = useCallback(
    (
      action: 'stop' | 'append_guidance' | 'regenerate' | 'rollback',
      params: { guidance?: string; checkpoint_id?: string; turn_id?: string; stream_id?: string } = {},
    ) => {
      const sent = sendEndpointWsCommand({
        action,
        session_id: endpointContext?.session.session_id || sessionId,
        endpoint_id: endpointId,
        endpoint_request_id: createEndpointRequestId(),
        ...params,
        metadata: { from: 'ui-control' },
      })
      if (!sent) {
        const error = {
          code: 'transport_error',
          category: 'dependency' as const,
          message: '交互通道未连接，无法提交控制命令',
          retryable: true,
          details: {},
          occurred_at: '',
        }
        dispatchTransport({ type: 'error', error })
        startTransition(() => {
          dispatchChat({ type: 'append_system_turn', turn: createSystemTurn(error.message, true) })
        })
      }
    },
    [endpointContext?.session.session_id, endpointId, sendEndpointWsCommand, sessionId, dispatchTransport],
  )

  const processWsUpdateForChat = useCallback((update: ReturnType<typeof parseEndpointWsPayload>) => {
    switch (update.kind) {
      case 'ack':
        {
          const message = buildAckMessage(update.ack)
          if (message) {
            startTransition(() => {
              dispatchChat({ type: 'append_system_turn', turn: createSystemTurn(message) })
            })
          }
        }
        break
      case 'error':
        startTransition(() => {
          dispatchChat({
            type: 'append_system_turn',
            turn: createSystemTurn(update.error.message || '发生错误', true),
          })
        })
        break
      case 'runtime_state':
        startTransition(() => {
          dispatchChat({ type: 'sync_runtime', snapshot: update.snapshot })
        })
        break
      case 'runtime_usage':
        startTransition(() => {
          dispatchChat({ type: 'sync_usage', snapshot: update.snapshot })
        })
        break
      case 'activity':
        startTransition(() => {
          dispatchChat({
            type: 'append_activity',
            activity: update.activity,
            activeTurnId: activeTurnIdRef.current || update.activity.turnId,
          })
        })
        break
      case 'confirm_requested':
        startTransition(() => {
          dispatchChat({ type: 'set_confirm_request', payload: update.payload })
        })
        break
      case 'confirm_resolved':
        startTransition(() => {
          dispatchChat({ type: 'set_confirm_request', payload: null })
        })
        break
      case 'human_input_requested':
        startTransition(() => {
          dispatchChat({ type: 'set_human_input_request', payload: update.payload })
        })
        break
      case 'human_input_resolved':
        startTransition(() => {
          dispatchChat({ type: 'set_human_input_request', payload: null })
        })
        break
      case 'message_created':
        startTransition(() => {
          dispatchChat({ type: 'append_runtime_message', message: update.message })
        })
        break
      case 'message_delta':
        {
          const key = `${update.channel}:${update.streamId}:${update.turnId}`
          const existing = deltaBufferRef.current.get(key)
          deltaBufferRef.current.set(key, {
            content: `${existing?.content || ''}${update.delta}`,
            streamId: update.streamId,
            turnId: update.turnId,
            channel: update.channel === 'reasoning' ? 'reasoning' : 'answer',
            phase: update.phase,
          })
          scheduleDeltaFlush()
        }
        break
      case 'message_completed':
        flushBufferedDeltas()
        startTransition(() => {
          dispatchChat({
            type: 'complete_stream_message',
            message: update.message,
            streamId: update.streamId,
            turnId: update.turnId,
          })
        })
        break
    }
  }, [flushBufferedDeltas, scheduleDeltaFlush])

  return {
    chatState,
    dispatchChat,
    loadThreadHistory,
    hydrateRuntimeUsage,
    approvalDisplay,
    turnActivities,
    sendMessage,
    sendConfirmResponse,
    sendHumanInputResponse,
    sendControlCommand,
    processWsUpdateForChat,
    pendingHumanInput: chatState.pendingHumanInput,
  }
}
