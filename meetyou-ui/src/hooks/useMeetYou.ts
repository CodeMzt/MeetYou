import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { triggerAttachmentDownload } from '../attachmentTransfers'
import type { StatusFeedback } from '../types'
import { DEFAULT_BASE_URL, WINDOW_SYNC_CHANNEL } from '../windowBridge'
import {
  DESKTOP_TOOL_CLIENT_REFRESH_INTERVAL_MS,
  useClientContext,
  useMeetYouSocket,
  useChatSession,
  useOperations,
} from './core'
import { parseClientWsPayload } from '../protocolClient'
import {
  completeClientAttachment,
  createClientAttachmentUploadTicket,
  uploadClientAttachmentContent
} from '../clientApi'

const STATUS_FEEDBACK_TTL_MS = 6000

export function useMeetYou(baseUrl: string = DEFAULT_BASE_URL) {
  const autoInitializeAttemptedRef = useRef(false)
  const [statusFeedback, setStatusFeedback] = useState<StatusFeedback | null>(null)
  const [attachmentInventoryVersion, setAttachmentInventoryVersion] = useState(0)

  const {
    clientContext,
    desktopToolClientId,
    transportState,
    dispatchTransport,
    sessionId,
    clientId,
    initializeClientContext,
    refreshDesktopToolClient,
    refreshWorkspace,
  } = useClientContext(baseUrl, (threadId) => {
    void loadThreadHistory(threadId)
  }, (turn) => {
    dispatchChat({ type: 'append_system_turn', turn })
  })

  const {
    clientConnectionState,
    sendClientWsCommand,
    refreshHealth,
  } = useMeetYouSocket(
    baseUrl,
    clientContext,
    (rawPayload) => applyClientWsUpdate(rawPayload),
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
    clientContext,
    sessionId,
    clientId,
    sendClientWsCommand,
    dispatchTransport,
    initializeClientContext
  )

  const {
    operations,
    decideOperationApproval,
    processWsUpdateForOperations,
  } = useOperations(
    baseUrl,
    clientContext,
    initializeClientContext,
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

  const publishStatusFeedback = useCallback((text: string, tone: StatusFeedback['tone']) => {
    setStatusFeedback({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      text,
      tone,
      createdAt: Date.now(),
    })
  }, [])

  const applyClientWsUpdate = useCallback((rawPayload: unknown) => {
    const update = parseClientWsPayload(rawPayload)
    
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

    // Domain level handlers
    processWsUpdateForChat(update)
    processWsUpdateForOperations(update)

    if (update.kind === 'workspace_changed') {
      void refreshWorkspace(update.workspaceId || update.activeWorkspaceId)
      void refreshDesktopToolClient()
    }

    if (
      update.kind === 'message_completed' ||
      update.kind === 'confirm_resolved' ||
      update.kind === 'operation_updated'
    ) {
      return
    }
  }, [dispatchTransport, processWsUpdateForChat, processWsUpdateForOperations, refreshDesktopToolClient, refreshWorkspace])

  useEffect(() => {
    if (autoInitializeAttemptedRef.current) {
      return
    }
    autoInitializeAttemptedRef.current = true
    void initializeClientContext()
  }, [initializeClientContext])

  useEffect(() => {
    if (!clientContext || transportState.connectionState !== 'connected') {
      return
    }
    void refreshHealth()
  }, [clientContext, refreshHealth, transportState.connectionState])

  useEffect(() => {
    if (!clientContext) {
      return
    }
    void refreshDesktopToolClient(clientContext)
    const timer = window.setInterval(() => {
      void refreshDesktopToolClient(clientContext)
    }, DESKTOP_TOOL_CLIENT_REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [clientContext, refreshDesktopToolClient])

  const effectiveConnectionState = useMemo(() => {
    if (!clientContext || clientConnectionState === 'connecting' || transportState.connectionState === 'connecting') {
      return 'connecting' as const
    }
    if (clientConnectionState === 'disconnected' || transportState.connectionState === 'disconnected') {
      return 'disconnected' as const
    }
    return 'connected' as const
  }, [clientConnectionState, clientContext, transportState.connectionState])

  const uploadAttachment = useCallback(async (file: File) => {
    try {
      const context = clientContext ?? (await initializeClientContext())
      const ticket = await createClientAttachmentUploadTicket(baseUrl, {
        owner_type: 'thread',
        owner_id: context.threadId,
        kind: file.type.startsWith('image/') ? 'image' : 'file',
        mime_type: file.type || 'application/octet-stream',
        file_name: file.name,
        size_bytes: file.size,
        client_id: context.clientId,
      })
      const uploadResult = await uploadClientAttachmentContent(ticket.upload_url, file)
      const attachment = await completeClientAttachment(baseUrl, ticket.attachment_id, {
        ticket_id: ticket.ticket_id,
        sha256: uploadResult.sha256,
        size_bytes: uploadResult.size_bytes,
      })
      setAttachmentInventoryVersion((current) => current + 1)
      publishStatusFeedback(`附件上传成功：${file.name}`, 'success')
      return attachment
    } catch (error) {
      publishStatusFeedback(`附件上传失败：${error instanceof Error ? error.message : '未知错误'}`, 'error')
      return null
    }
  }, [baseUrl, clientContext, initializeClientContext, publishStatusFeedback])

  const downloadAttachment = useCallback(async (attachmentId: string) => {
    try {
      const context = clientContext ?? (await initializeClientContext())
      await triggerAttachmentDownload(baseUrl, attachmentId, context.clientId)
      return true
    } catch (error) {
      publishStatusFeedback(`附件下载失败：${error instanceof Error ? error.message : '未知错误'}`, 'error')
      return null
    }
  }, [baseUrl, clientContext, initializeClientContext, publishStatusFeedback])

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
      threadId: clientContext?.threadId || '',
      workspace: clientContext?.workspace || null,
      connectionState: effectiveConnectionState,
      desktopToolsAvailable: Boolean(desktopToolClientId),
      operations,
      approvalDisplay,
      pendingHumanInput,
    })
  }, [
    approvalDisplay,
    baseUrl,
    clientContext?.threadId,
    clientContext?.workspace,
    desktopToolClientId,
    effectiveConnectionState,
    operations,
    pendingHumanInput,
  ])

  useEffect(() => {
    window.ipcRenderer?.send(WINDOW_SYNC_CHANNEL.attachments.update, {
      baseUrl,
      threadId: clientContext?.threadId || '',
      clientId,
      workspaceTitle: clientContext?.workspace?.title || clientContext?.workspace?.workspace_id || '',
      attachmentInventoryVersion,
    })
  }, [attachmentInventoryVersion, baseUrl, clientContext?.threadId, clientContext?.workspace, clientId])

  return {
    messages: chatState.messages,
    operations,
    workspace: clientContext?.workspace || null,
    threadId: clientContext?.threadId || '',
    sessionId,
    workspaceId: clientContext?.workspace.workspace_id || '',
    desktopToolsAvailable: Boolean(desktopToolClientId),
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
    attachmentInventoryVersion,
    sendMessage,
    decideOperationApproval,
    sendConfirmResponse,
    sendHumanInputResponse,
    sendControlCommand,
    uploadAttachment,
    downloadAttachment,
    refreshHealth,
    refreshWorkspace,
    setStatusFeedback,
    baseUrl,
    clientId,
  }
}
