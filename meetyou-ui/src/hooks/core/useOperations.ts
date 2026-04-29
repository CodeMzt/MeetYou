import { startTransition, useCallback, useState } from 'react'
import { decideRuntimeApproval } from '../../runtimeApi'
import { normalizeAttachmentObjects } from '../../attachmentObject'
import { createSystemTurn } from '../../chatState'
import { parseEndpointWsPayload } from '../../protocolClient'
import type { EndpointContext } from './useEndpointContext'
import type { OperationView } from '../../types'

function upsertOperationView(operations: OperationView[], operation: OperationView): OperationView[] {
  const index = operations.findIndex((item) => item.operation_id === operation.operation_id)
  if (index === -1) {
    return [operation, ...operations]
  }
  const next = [...operations]
  next[index] = operation
  return next
}

function deriveOperationTone(status: string): OperationView['tone'] {
  if (status === 'succeeded') return 'success'
  if (status === 'failed' || status === 'rejected' || status === 'cancelled') return 'failed'
  if (status === 'running' || status === 'dispatching') return 'running'
  return 'pending'
}

function deriveOperationSummary(result: Record<string, unknown>, error: Record<string, unknown>, detail: string, phase: string, status: string): string {
  if (status === 'waiting_approval') {
    return detail || '等待审批'
  }
  if (typeof result.summary === 'string' && result.summary) {
    return result.summary
  }
  if (typeof error.message === 'string' && error.message) {
    return error.message
  }
  if (detail) {
    return detail
  }
  return phase || status
}

function applyOperationEvent(
  operations: OperationView[],
  event: Extract<import('../../types').EndpointWsEvent, { kind: 'operation_updated' }>,
): OperationView[] {
  const existing = operations.find((item) => item.operation_id === event.operationId)
  const nextResult = event.result || {}
  const hasResultPayload = Object.keys(nextResult).length > 0
  const status = event.status || existing?.status || 'queued'
  const phase = event.phase || existing?.phase || ''
  const detail = event.detail || existing?.detail || ''
  const result = hasResultPayload ? nextResult : existing?.result || {}
  const error = event.error || existing?.error || {}
  const attachments = hasResultPayload
    ? normalizeAttachmentObjects(nextResult.attachment_outputs)
    : existing?.attachments || []
  
  const next: OperationView = {
    operation_id: event.operationId,
    thread_id: event.threadId,
    workspace_id: event.workspaceId || existing?.workspace_id || '',
    title: event.title || existing?.title || event.operationId,
    operation_type: event.operationType || existing?.operation_type || 'tool_call',
    execution_target: event.executionTarget || existing?.execution_target || 'endpoint',
    target_endpoint_id: event.targetEndpointId || existing?.target_endpoint_id || '',
    tool_key: event.toolKey || existing?.tool_key || '',
    tool_id: event.toolId || existing?.tool_id || '',
    status,
    approval_id: event.approvalId || existing?.approval_id,
    approval_status: event.approvalStatus || existing?.approval_status,
    approval_required: event.approvalRequired || existing?.approval_required,
    call_id: event.callId || existing?.call_id || '',
    phase,
    detail,
    result,
    error,
    attachments,
    tone: deriveOperationTone(status),
    summary: deriveOperationSummary(result, error, detail, phase, status),
    isBlocking: false,
  }
  return upsertOperationView(operations, next)
}

export function useOperations(
  baseUrl: string,
  endpointContext: EndpointContext | null,
  initializeEndpointContext: () => Promise<EndpointContext>,
  dispatchChat: any
) {
  const [operations, setOperations] = useState<OperationView[]>([])

  const decideOperationApproval = useCallback(
    async (approvalId: string, decision: 'approve' | 'reject') => {
      const context = endpointContext ?? (await initializeEndpointContext())
      await decideRuntimeApproval(baseUrl, approvalId, {
        decision,
        endpoint_id: context.endpointId,
      })
      startTransition(() => {
        dispatchChat({
          type: 'append_system_turn',
          turn: createSystemTurn(decision === 'approve' ? '操作已允许。' : '操作已拒绝。'),
        })
        setOperations((current) =>
          current.map((item) =>
            item.approval_id === approvalId
              ? {
                  ...item,
                  approval_status: decision === 'approve' ? 'approved' : 'rejected',
                  status: decision === 'approve' ? 'queued' : 'rejected',
                  tone: decision === 'approve' ? 'pending' : 'failed',
                  summary: decision === 'approve' ? '已允许，等待执行。' : '已拒绝。',
                }
              : item,
          ),
        )
      })
    },
    [baseUrl, endpointContext, initializeEndpointContext, dispatchChat],
  )

  const processWsUpdateForOperations = useCallback((update: ReturnType<typeof parseEndpointWsPayload>) => {
    if (update.kind === 'operation_updated') {
      startTransition(() => {
        setOperations((current) => applyOperationEvent(current, update))
      })
    }
  }, [])

  return {
    operations,
    decideOperationApproval,
    processWsUpdateForOperations,
  }
}
