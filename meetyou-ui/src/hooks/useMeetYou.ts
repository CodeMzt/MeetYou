import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { triggerAttachmentDownload } from '../attachmentTransfers'
import type { ClientThreadProcedureContext, StatusFeedback } from '../types'
import { DEFAULT_BASE_URL, WINDOW_SYNC_CHANNEL } from '../windowBridge'
import {
  DESKTOP_AGENT_REFRESH_INTERVAL_MS,
  useClientContext,
  useMeetYouSocket,
  useChatSession,
  useOperations,
  useProcedures,
} from './core'
import { parseClientWsPayload } from '../protocolClient'
import {
  completeClientAttachment,
  getClientThreadProcedureContext,
  createClientAttachmentUploadTicket,
  uploadClientAttachmentContent
} from '../clientApi'

const STATUS_FEEDBACK_TTL_MS = 6000

function procedureDetailSignature(procedure: ClientThreadProcedureContext['effective_procedure']): string {
  if (!procedure) {
    return ''
  }
  return JSON.stringify({
    procedure_id: procedure.procedure_id,
    title: procedure.title,
    description: procedure.description,
    applicable_modes: procedure.applicable_modes,
    recommended_capabilities: procedure.recommended_capabilities,
    preferred_capability_ref: procedure.preferred_capability_ref,
    preferred_agent_ids: procedure.preferred_agent_ids,
    preferred_agent_types: procedure.preferred_agent_types,
    agent_routing_policy: procedure.agent_routing_policy,
    default_execution_target: procedure.default_execution_target,
    risk_profile: procedure.risk_profile,
    status: procedure.status,
    prompt_overlay: procedure.prompt_overlay,
    recommended_source_profiles: procedure.recommended_source_profiles,
    infer_keywords: procedure.infer_keywords,
  })
}

function sameProcedureContext(
  current: ClientThreadProcedureContext | null,
  next: ClientThreadProcedureContext | null,
): boolean {
  if (current === next) {
    return true
  }
  if (!current || !next) {
    return false
  }
  return (
    current.source === next.source &&
    current.latest_inferred_reason === next.latest_inferred_reason &&
    current.latest_inferred_score === next.latest_inferred_score &&
    current.latest_inferred_at === next.latest_inferred_at &&
    procedureDetailSignature(current.pinned_procedure) === procedureDetailSignature(next.pinned_procedure) &&
    procedureDetailSignature(current.latest_inferred_procedure) === procedureDetailSignature(next.latest_inferred_procedure) &&
    procedureDetailSignature(current.effective_procedure) === procedureDetailSignature(next.effective_procedure)
  )
}

export function useMeetYou(baseUrl: string = DEFAULT_BASE_URL) {
  const autoInitializeAttemptedRef = useRef(false)
  const [procedureContext, setProcedureContext] = useState<ClientThreadProcedureContext | null>(null)
  const [statusFeedback, setStatusFeedback] = useState<StatusFeedback | null>(null)
  const [attachmentInventoryVersion, setAttachmentInventoryVersion] = useState(0)

  const {
    clientContext,
    desktopAgentId,
    transportState,
    dispatchTransport,
    sessionId,
    clientId,
    initializeClientContext,
    refreshAvailableAgents,
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

  const reloadProcedureContext = useCallback(async (threadIdOverride?: string) => {
    const threadId = String(threadIdOverride || clientContext?.threadId || '').trim()
    if (!threadId) {
      setProcedureContext(null)
      return null
    }
    try {
      const nextContext = await getClientThreadProcedureContext(baseUrl, threadId)
      setProcedureContext((current) => {
        if (sameProcedureContext(current, nextContext)) {
          return current
        }
        return nextContext
      })
      return nextContext
    } catch (error) {
      console.warn('Failed to load thread procedure context:', error)
      return null
    }
  }, [baseUrl, clientContext?.threadId])

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
      void refreshAvailableAgents()
    }

    if (
      update.kind === 'message_completed' ||
      update.kind === 'confirm_resolved' ||
      update.kind === 'operation_updated'
    ) {
      void reloadProcedureContext()
    }
  }, [dispatchTransport, processWsUpdateForChat, processWsUpdateForOperations, refreshAvailableAgents, refreshWorkspace, reloadProcedureContext])

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
    void refreshAvailableAgents(clientContext)
    void reloadProcedureContext(clientContext.threadId)
    const timer = window.setInterval(() => {
      void refreshAvailableAgents(clientContext)
    }, DESKTOP_AGENT_REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [clientContext, refreshAvailableAgents, reloadProcedureContext])

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
      publishStatusFeedback(`附件上传失败：${error instanceof Error ? error.message : 'unknown error'}`, 'error')
      return null
    }
  }, [baseUrl, clientContext, initializeClientContext, publishStatusFeedback])

  const downloadAttachment = useCallback(async (attachmentId: string) => {
    try {
      const context = clientContext ?? (await initializeClientContext())
      await triggerAttachmentDownload(baseUrl, attachmentId, context.clientId)
      return true
    } catch (error) {
      publishStatusFeedback(`附件下载失败：${error instanceof Error ? error.message : 'unknown error'}`, 'error')
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
      procedureContext,
      connectionState: effectiveConnectionState,
      desktopAgentConnected: Boolean(desktopAgentId),
      operations,
      approvalDisplay,
      pendingHumanInput,
    })
  }, [
    approvalDisplay,
    baseUrl,
    clientContext?.threadId,
    clientContext?.workspace,
    desktopAgentId,
    effectiveConnectionState,
    operations,
    pendingHumanInput,
    procedureContext,
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
    procedures,
    procedureContext,
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
    statusFeedback,
    attachmentInventoryVersion,
    sendMessage,
    decideOperationApproval,
    executeProcedure,
    reloadProcedures,
    reloadProcedureContext,
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
