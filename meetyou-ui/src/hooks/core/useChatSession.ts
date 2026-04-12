import { startTransition, useCallback, useEffect, useMemo, useReducer, useRef } from 'react'
import { fetchRuntimeUsageSnapshot, listThreadMessages, sendClientMessage, submitClientConfirmResponse, submitClientHumanInputResponse } from '../../clientApi'
import { createInitialChatState, createSystemTurn, reduceChatState } from '../../chatState'
import { parseClientWsPayload } from '../../protocolClient'
import type { ClientContext } from './useClientContext'
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

export function useChatSession(
  baseUrl: string,
  clientContext: ClientContext | null,
  sessionId: string,
  clientId: string,
  sendClientWsCommand: (payload: Record<string, unknown>) => boolean,
  dispatchTransport: any,
  initializeClientContext: () => Promise<ClientContext>
) {
  const [chatState, dispatchChat] = useReducer(reduceChatState, undefined, createInitialChatState)
  const activeTurnIdRef = useRef('')

  activeTurnIdRef.current = chatState.runtimeSnapshot?.turn_id || ''

  const loadThreadHistory = useCallback(
    async (threadId: string) => {
      try {
        const messages = await listThreadMessages(baseUrl, threadId)
        startTransition(() => {
          dispatchChat({ type: 'hydrate_messages', messages })
        })
      } catch (error) {
        console.error('Failed to load thread history:', error)
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
        console.warn('Failed to hydrate runtime usage snapshot:', error)
      }
    },
    [baseUrl],
  )

  useEffect(() => {
    if (!clientContext?.session.session_id) {
      return
    }
    void hydrateRuntimeUsage(clientContext.session.session_id)
  }, [clientContext?.session.session_id, hydrateRuntimeUsage])

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
        const context = clientContext ?? (await initializeClientContext())
        const message = await sendClientMessage(baseUrl, {
          thread_id: context.threadId,
          workspace_id: context.workspace.workspace_id,
          client_id: context.clientId,
          session_id: context.session.session_id,
          client_type: 'electron',
          display_name: '桌面应用',
          role: 'user',
          content,
          client_message_id: createClientMessageId(),
          preferred_mode: preferredMode,
          options: buildThinkingOptions(thinkingOverride),
        })
        startTransition(() => {
          dispatchChat({ type: 'append_client_message', message })
        })
      } catch (error) {
        console.error('Failed to send message via client API:', error)
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
    [baseUrl, clientContext, initializeClientContext, dispatchTransport],
  )

  const sendConfirmResponse = useCallback(async (requestId: string, accepted: boolean, approvalId?: string) => {
    const turnId = activeTurnIdRef.current
    const resolvedSessionId = clientContext?.session.session_id || sessionId
    try {
      await submitClientConfirmResponse(baseUrl, resolvedSessionId, {
        accepted,
        request_id: requestId,
        client_id: clientId,
      })
      startTransition(() => {
        dispatchChat({ type: 'resolve_confirm', requestId, accepted, turnId })
      })
      return
    } catch {
      const sent = sendClientWsCommand({
        action: 'confirm_response',
        session_id: resolvedSessionId,
        request_id: requestId,
        accepted,
        client_id: clientId,
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
  }, [baseUrl, clientContext?.session.session_id, clientId, sendClientWsCommand, sessionId, dispatchTransport])

  const sendHumanInputResponse = useCallback(
    async (requestId: string, answerText: string, selectedOption?: string) => {
      const normalizedAnswer = answerText.trim() || selectedOption || ''
      const turnId = activeTurnIdRef.current
      const resolvedSessionId = clientContext?.session.session_id || sessionId
      try {
        await submitClientHumanInputResponse(baseUrl, resolvedSessionId, {
          request_id: requestId,
          answer_text: normalizedAnswer,
          selected_option: selectedOption,
          client_id: clientId,
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
        const sent = sendClientWsCommand({
          action: 'input_response',
          session_id: resolvedSessionId,
          request_id: requestId,
          answer_text: normalizedAnswer,
          selected_option: selectedOption,
          client_id: clientId,
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
    [baseUrl, clientContext?.session.session_id, clientId, sendClientWsCommand, sessionId, dispatchTransport],
  )

  const sendControlCommand = useCallback(
    (
      action: 'stop' | 'append_guidance' | 'regenerate' | 'rollback',
      params: { guidance?: string; checkpoint_id?: string; turn_id?: string; stream_id?: string } = {},
    ) => {
      const sent = sendClientWsCommand({
        action,
        session_id: clientContext?.session.session_id || sessionId,
        client_id: clientId,
        client_request_id: createClientMessageId(),
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
    [clientContext?.session.session_id, clientId, sendClientWsCommand, sessionId, dispatchTransport],
  )

  const processWsUpdateForChat = useCallback((update: ReturnType<typeof parseClientWsPayload>) => {
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
          dispatchChat({ type: 'append_client_message', message: update.message })
        })
        break
      case 'message_delta':
        startTransition(() => {
          dispatchChat({
            type: 'append_message',
            role: 'assistant',
            content: update.delta,
            streamId: update.streamId,
            turnId: update.turnId,
            channel: update.channel,
            phase: update.phase,
            eventId: `${update.channel}:${update.streamId}:${update.turnId}:${update.delta.length}`,
            activeTurnId: activeTurnIdRef.current || update.turnId,
          })
        })
        break
      case 'message_completed':
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
  }, [])

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
