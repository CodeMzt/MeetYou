import { startTransition, useCallback, useEffect, useMemo } from 'react'
import { normalizeAttachmentObject } from '../attachmentObject'
import {
  DESKTOP_AGENT_REFRESH_INTERVAL_MS,
  useClientContext,
  useMeetYouSocket,
  useChatSession,
  useOperations,
  useProcedures,
} from './core'
import { parseClientWsPayload } from '../protocolClient'
import { createSystemTurn } from '../chatState'
import {
  completeClientAttachment,
  downloadClientAttachmentContent,
  createClientAttachmentDownloadTicket,
  createClientAttachmentUploadTicket,
  uploadClientAttachmentContent,
} from '../clientApi'

export function useMeetYou(baseUrl: string = 'http://127.0.0.1:8000') {
  const {
    clientContext,
    desktopAgentId,
    transportState,
    dispatchTransport,
    sessionId,
    clientId,
    initializeClientContext,
    refreshExecutionTargets,
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
    sendAgentEchoOperation,
    decideOperationApproval,
    processWsUpdateForOperations,
  } = useOperations(
    baseUrl,
    clientContext,
    desktopAgentId,
    initializeClientContext,
    dispatchChat
  )

  const {
    procedures,
    executeProcedure,
    reloadProcedures,
  } = useProcedures(
    baseUrl,
    clientContext,
    desktopAgentId,
    dispatchTransport,
    dispatchChat
  )

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
  }, [dispatchTransport, processWsUpdateForChat, processWsUpdateForOperations])

  useEffect(() => {
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
    void refreshExecutionTargets(clientContext)
    const timer = window.setInterval(() => {
      void refreshExecutionTargets(clientContext)
    }, DESKTOP_AGENT_REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [clientContext, refreshExecutionTargets])

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
      const downloadTicket = await createClientAttachmentDownloadTicket(baseUrl, attachment.attachment_id, context.clientId)
      const attachmentView = normalizeAttachmentObject({
        ...attachment,
        file_name: file.name,
        download_url: downloadTicket.download_url,
      })
      if (!attachmentView) {
        throw new Error('附件对象视图构建失败')
      }
      startTransition(() => {
        dispatchChat({
          type: 'append_system_turn',
          turn: createSystemTurn(
            `附件已上传：${file.name}`,
            false,
            [attachmentView],
          ),
        })
      })
      return attachment
    } catch (error) {
      startTransition(() => {
        dispatchChat({
          type: 'append_system_turn',
          turn: createSystemTurn(`附件上传失败：${error instanceof Error ? error.message : 'unknown error'}`, true),
        })
      })
      return null
    }
  }, [baseUrl, clientContext, dispatchChat, initializeClientContext])

  const downloadAttachment = useCallback(async (attachmentId: string) => {
    try {
      const context = clientContext ?? (await initializeClientContext())
      const ticket = await createClientAttachmentDownloadTicket(baseUrl, attachmentId, context.clientId)
      const blob = await downloadClientAttachmentContent(ticket.download_url)
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = ticket.file_name || attachmentId
      link.rel = 'noopener noreferrer'
      link.style.display = 'none'
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
      return ticket
    } catch (error) {
      startTransition(() => {
        dispatchChat({
          type: 'append_system_turn',
          turn: createSystemTurn(`附件下载失败：${error instanceof Error ? error.message : 'unknown error'}`, true),
        })
      })
      return null
    }
  }, [baseUrl, clientContext, dispatchChat, initializeClientContext])

  return {
    messages: chatState.messages,
    operations,
    procedures,
    workspace: clientContext?.workspace || null,
    threadId: clientContext?.threadId || '',
    sessionId,
    workspaceId: clientContext?.workspace.workspace_id || '',
    desktopAgentConnected: Boolean(desktopAgentId),
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
    sendMessage,
    sendAgentEchoOperation,
    decideOperationApproval,
    executeProcedure,
    reloadProcedures,
    sendConfirmResponse,
    sendHumanInputResponse,
    sendControlCommand,
    uploadAttachment,
    downloadAttachment,
    refreshHealth,
    baseUrl,
    clientId,
  }
}
