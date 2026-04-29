import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { triggerAttachmentDownload } from '../attachmentTransfers'
import type { StatusFeedback } from '../types'
import { DEFAULT_BASE_URL, WINDOW_SYNC_CHANNEL } from '../windowBridge'
import {
  DESKTOP_TOOL_ENDPOINT_REFRESH_INTERVAL_MS,
  useEndpointContext,
  useMeetYouSocket,
  useChatSession,
  useOperations,
} from './core'
import { parseEndpointWsPayload } from '../protocolClient'
import {
  completeRuntimeAttachment,
  createRuntimeAttachmentUploadTicket,
  uploadRuntimeAttachmentContent
} from '../runtimeApi'

const STATUS_FEEDBACK_TTL_MS = 6000

export function useMeetYou(baseUrl: string = DEFAULT_BASE_URL) {
  const autoInitializeAttemptedRef = useRef(false)
  const [statusFeedback, setStatusFeedback] = useState<StatusFeedback | null>(null)
  const [attachmentInventoryVersion, setAttachmentInventoryVersion] = useState(0)

  const {
    endpointContext,
    desktopToolEndpointId,
    transportState,
    dispatchTransport,
    sessionId,
    endpointId,
    initializeEndpointContext,
    refreshDesktopToolEndpoint,
    refreshWorkspace,
  } = useEndpointContext(baseUrl, (threadId) => {
    void loadThreadHistory(threadId)
  }, (turn) => {
    dispatchChat({ type: 'append_system_turn', turn })
  })

  const {
    endpointConnectionState,
    sendEndpointWsCommand,
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
    sendEndpointWsCommand,
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

  const publishStatusFeedback = useCallback((text: string, tone: StatusFeedback['tone']) => {
    setStatusFeedback({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      text,
      tone,
      createdAt: Date.now(),
    })
  }, [])

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
  }, [dispatchTransport, processWsUpdateForChat, processWsUpdateForOperations, refreshDesktopToolEndpoint, refreshWorkspace])

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

  const uploadAttachment = useCallback(async (file: File) => {
    try {
      const context = endpointContext ?? (await initializeEndpointContext())
      const ticket = await createRuntimeAttachmentUploadTicket(baseUrl, {
        owner_type: 'thread',
        owner_id: context.threadId,
        kind: file.type.startsWith('image/') ? 'image' : 'file',
        mime_type: file.type || 'application/octet-stream',
        file_name: file.name,
        size_bytes: file.size,
        endpoint_id: context.endpointId,
      })
      const uploadResult = await uploadRuntimeAttachmentContent(ticket.upload_url, file)
      const attachment = await completeRuntimeAttachment(baseUrl, ticket.attachment_id, {
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
  }, [baseUrl, endpointContext, initializeEndpointContext, publishStatusFeedback])

  const downloadAttachment = useCallback(async (attachmentId: string) => {
    try {
      const context = endpointContext ?? (await initializeEndpointContext())
      await triggerAttachmentDownload(baseUrl, attachmentId, context.endpointId)
      return true
    } catch (error) {
      publishStatusFeedback(`附件下载失败：${error instanceof Error ? error.message : '未知错误'}`, 'error')
      return null
    }
  }, [baseUrl, endpointContext, initializeEndpointContext, publishStatusFeedback])

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

  useEffect(() => {
    window.ipcRenderer?.send(WINDOW_SYNC_CHANNEL.attachments.update, {
      baseUrl,
      threadId: endpointContext?.threadId || '',
      endpointId,
      workspaceTitle: endpointContext?.workspace?.title || endpointContext?.workspace?.workspace_id || '',
      attachmentInventoryVersion,
    })
  }, [attachmentInventoryVersion, baseUrl, endpointContext?.threadId, endpointContext?.workspace, endpointId])

  return {
    messages: chatState.messages,
    operations,
    workspace: endpointContext?.workspace || null,
    threadId: endpointContext?.threadId || '',
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
    endpointId,
  }
}
