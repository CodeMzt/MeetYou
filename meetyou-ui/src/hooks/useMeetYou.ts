import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChatTurn, StatusFeedback } from '../types'
import { DEFAULT_BASE_URL, WINDOW_SYNC_CHANNEL } from '../windowBridge'
import { createRuntimeProjectSourceFromMessage, editRetryRuntimeMessage } from '../runtimeApi'
import {
  DESKTOP_TOOL_ENDPOINT_REFRESH_INTERVAL_MS,
  useEndpointContext,
  useMeetYouSocket,
  useChatSession,
  useOperations,
} from './core'
import { parseEndpointWsPayload } from '../protocolClient'

const STATUS_FEEDBACK_TTL_MS = 6000

export function useMeetYou(baseUrl: string = DEFAULT_BASE_URL) {
  const autoInitializeAttemptedRef = useRef(false)
  const [statusFeedback, setStatusFeedback] = useState<StatusFeedback | null>(null)

  const {
    endpointContext,
    desktopToolEndpointId,
    transportState,
    dispatchTransport,
    sessionId,
    endpointId,
    runtimeThreads,
    runtimeProjects,
    activeProjectId,
    defaultThreadId,
    initializeEndpointContext,
    selectRuntimeThread,
    selectRuntimeProject,
    createAndSelectRuntimeThread,
    createRuntimeProjectAndRemember,
    deleteRuntimeThreadAndSelect,
    refreshRuntimeThreads,
    refreshDesktopToolEndpoint,
    refreshWorkspace,
  } = useEndpointContext(baseUrl, async (threadId) => {
    await loadThreadHistory(threadId)
  }, (turn) => {
    dispatchChat({ type: 'append_system_turn', turn })
  })

  const {
    endpointConnectionState,
    refreshHealth,
  } = useMeetYouSocket(
    baseUrl,
    endpointContext,
    (rawPayload) => applyEndpointWsUpdate(rawPayload),
    dispatchTransport
  )

  const {
    chatState,
    dispatchChat,
    loadThreadHistory,
    approvalDisplay,
    turnActivities,
    sendMessage,
    sendConfirmResponse,
    sendHumanInputResponse,
    sendControlCommand,
    processWsUpdateForChat,
    pendingHumanInput,
  } = useChatSession(
    baseUrl,
    endpointContext,
    sessionId,
    endpointId,
    dispatchTransport,
    initializeEndpointContext
  )

  const {
    operations,
    decideOperationApproval,
    processWsUpdateForOperations,
  } = useOperations(
    baseUrl,
    endpointContext,
    initializeEndpointContext,
    dispatchChat
  )

  useEffect(() => {
    if (!statusFeedback) {
      return
    }
    const timer = window.setTimeout(() => {
      setStatusFeedback((current) => current?.id === statusFeedback.id ? null : current)
    }, STATUS_FEEDBACK_TTL_MS)
    return () => window.clearTimeout(timer)
  }, [statusFeedback])

  const applyEndpointWsUpdate = useCallback((rawPayload: unknown) => {
    const update = parseEndpointWsPayload(rawPayload)
    
    // Transport level handlers
    if (update.kind === 'connection') {
      dispatchTransport({ type: 'set_connection_state', connectionState: 'connected' })
      return
    }
    if (update.kind === 'ack') {
      dispatchTransport({ type: 'ack', ack: update.ack })
    }
    if (update.kind === 'error') {
      dispatchTransport({ type: 'error', error: update.error })
    }

    if (update.kind === 'thread_switched') {
      if (update.targetThreadId && update.targetThreadId !== endpointContext?.threadId) {
        void selectRuntimeThread(update.targetThreadId)
      }
      return
    }

    if (update.kind === 'thread_deleted') {
      if (update.deletedThreadId && update.deletedThreadId === endpointContext?.threadId) {
        if (update.fallbackThreadId) {
          void selectRuntimeThread(update.fallbackThreadId)
        } else {
          void initializeEndpointContext()
        }
      } else {
        void refreshRuntimeThreads(update.workspaceId)
      }
      return
    }

    // Domain level handlers
    processWsUpdateForChat(update)
    processWsUpdateForOperations(update)

    if (update.kind === 'workspace_changed') {
      void refreshWorkspace(update.workspaceId || update.activeWorkspaceId)
      void refreshDesktopToolEndpoint()
    }

    if (
      update.kind === 'message_completed' ||
      update.kind === 'confirm_resolved' ||
      update.kind === 'operation_updated'
    ) {
      return
    }
  }, [
    dispatchTransport,
    endpointContext?.threadId,
    initializeEndpointContext,
    processWsUpdateForChat,
    processWsUpdateForOperations,
    refreshDesktopToolEndpoint,
    refreshRuntimeThreads,
    refreshWorkspace,
    selectRuntimeThread,
  ])

  useEffect(() => {
    if (autoInitializeAttemptedRef.current) {
      return
    }
    autoInitializeAttemptedRef.current = true
    void initializeEndpointContext()
  }, [initializeEndpointContext])

  useEffect(() => {
    if (!endpointContext || transportState.connectionState !== 'connected') {
      return
    }
    void refreshHealth()
  }, [endpointContext, refreshHealth, transportState.connectionState])

  useEffect(() => {
    if (!endpointContext) {
      return
    }
    void refreshDesktopToolEndpoint(endpointContext)
    const timer = window.setInterval(() => {
      void refreshDesktopToolEndpoint(endpointContext)
    }, DESKTOP_TOOL_ENDPOINT_REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [endpointContext, refreshDesktopToolEndpoint])

  const effectiveConnectionState = useMemo(() => {
    if (!endpointContext || endpointConnectionState === 'connecting' || transportState.connectionState === 'connecting') {
      return 'connecting' as const
    }
    if (endpointConnectionState === 'disconnected' || transportState.connectionState === 'disconnected') {
      return 'disconnected' as const
    }
    return 'connected' as const
  }, [endpointConnectionState, endpointContext, transportState.connectionState])

  useEffect(() => {
    window.ipcRenderer?.send(WINDOW_SYNC_CHANNEL.runtimeDebug.update, { sessionId, baseUrl })
  }, [baseUrl, sessionId])

  useEffect(() => {
    window.ipcRenderer?.send(WINDOW_SYNC_CHANNEL.context.update, {
      usageSnapshot: chatState.usageSnapshot,
    })
  }, [chatState.usageSnapshot])

  useEffect(() => {
    window.ipcRenderer?.send(WINDOW_SYNC_CHANNEL.workspace.update, {
      baseUrl,
      threadId: endpointContext?.threadId || '',
      workspace: endpointContext?.workspace || null,
      connectionState: effectiveConnectionState,
      desktopToolsAvailable: Boolean(desktopToolEndpointId),
      operations,
      approvalDisplay,
      pendingHumanInput,
    })
  }, [
    approvalDisplay,
    baseUrl,
    endpointContext?.threadId,
    endpointContext?.workspace,
    desktopToolEndpointId,
    effectiveConnectionState,
    operations,
    pendingHumanInput,
  ])

  const saveMessageAsProjectSource = useCallback(async (message: ChatTurn) => {
    const projectId = String(activeProjectId || '').trim()
    const messageId = String(message.id || '').trim()
    if (!projectId) {
      throw new Error('请先选择项目')
    }
    if (!messageId || message.temporary || !messageId.startsWith('msg_')) {
      throw new Error('消息尚未持久化，不能保存为项目源')
    }
    const title = `${message.role === 'assistant' ? 'Assistant' : 'User'} message ${messageId.slice(-8)}`
    const source = await createRuntimeProjectSourceFromMessage(baseUrl, projectId, {
      message_id: messageId,
      title,
      metadata: {
        role: message.role,
        thread_id: endpointContext?.threadId || '',
      },
    })
    setStatusFeedback({
      id: `project-source-${Date.now()}`,
      text: '已保存为项目源',
      tone: 'success',
      createdAt: Date.now(),
    })
    return source
  }, [activeProjectId, baseUrl, endpointContext?.threadId])

  const editRetryMessage = useCallback(async (message: ChatTurn, content: string) => {
    const messageId = String(message.id || '').trim()
    const nextContent = String(content || '').trim()
    if (!messageId || message.temporary || !messageId.startsWith('msg_')) {
      throw new Error('消息尚未持久化，不能编辑重试')
    }
    if (message.role !== 'user') {
      throw new Error('只能编辑用户消息并重试')
    }
    if (!nextContent) {
      throw new Error('编辑内容不能为空')
    }
    const result = await editRetryRuntimeMessage(baseUrl, messageId, {
      content: nextContent,
      title: `Edit retry ${messageId.slice(-8)}`,
    })
    const targetThreadId = result.message.thread_id || endpointContext?.threadId || ''
    if (targetThreadId) {
      await loadThreadHistory(targetThreadId)
    }
    await refreshRuntimeThreads(endpointContext?.workspace.workspace_id)
    setStatusFeedback({
      id: `edit-retry-${Date.now()}`,
      text: result.replay_status === 'queued' ? '已创建分支并开始重试' : '已创建编辑重试分支',
      tone: 'success',
      createdAt: Date.now(),
    })
    return result
  }, [baseUrl, endpointContext?.threadId, endpointContext?.workspace.workspace_id, loadThreadHistory, refreshRuntimeThreads])

  return {
    messages: chatState.messages,
    operations,
    workspace: endpointContext?.workspace || null,
    threads: runtimeThreads,
    projects: runtimeProjects,
    activeProjectId,
    threadId: endpointContext?.threadId || '',
    defaultThreadId,
    sessionId,
    workspaceId: endpointContext?.workspace.workspace_id || '',
    desktopToolsAvailable: Boolean(desktopToolEndpointId),
    connectionState: effectiveConnectionState,
    connected: effectiveConnectionState === 'connected',
    runtimeSnapshot: chatState.runtimeSnapshot,
    usageSnapshot: chatState.usageSnapshot,
    turnActivities,
    approvalDisplay,
    confirmRequest: chatState.confirmRequest,
    pendingHumanInput,
    healthSnapshot: transportState.healthSnapshot,
    lastAck: transportState.lastAck,
    lastError: transportState.lastError,
    archivedTurnCount: chatState.archivedTurnCount,
    statusFeedback,
    sendMessage,
    decideOperationApproval,
    sendConfirmResponse,
    sendHumanInputResponse,
    sendControlCommand,
    saveMessageAsProjectSource,
    editRetryMessage,
    createThread: createAndSelectRuntimeThread,
    createProject: createRuntimeProjectAndRemember,
    deleteThread: deleteRuntimeThreadAndSelect,
    refreshHealth,
    refreshWorkspace,
    selectProject: selectRuntimeProject,
    selectThread: selectRuntimeThread,
    setStatusFeedback,
    baseUrl,
    endpointId,
  }
}
