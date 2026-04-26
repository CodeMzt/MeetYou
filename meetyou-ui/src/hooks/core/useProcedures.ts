import { useState, useCallback, useEffect } from 'react'
import { listClientProcedures, createClientOperation } from '../../clientApi'
import { createSystemTurn } from '../../chatState'
import type { ClientContext } from './useClientContext'
import type { ClientProcedure } from '../../types'

export function useProcedures(
  baseUrl: string,
  clientContext: ClientContext | null,
  desktopToolClientId: string,
  dispatchTransport: any,
  dispatchChat: any
) {
  const [procedures, setProcedures] = useState<ClientProcedure[]>([])
  const [isLoadingProcedures, setIsLoadingProcedures] = useState(false)

  const loadProcedures = useCallback(async () => {
    if (!baseUrl) return
    setIsLoadingProcedures(true)
    try {
      const list = await listClientProcedures(baseUrl)
      setProcedures(list)
    } catch (error) {
      console.error('Failed to load procedures:', error)
    } finally {
      setIsLoadingProcedures(false)
    }
  }, [baseUrl])

  useEffect(() => {
    void loadProcedures()
  }, [loadProcedures])

  const executeProcedure = useCallback(
    async (procedureId: string, customTitle?: string) => {
      if (!clientContext) {
        console.warn('Cannot execute procedure without client context')
        return
      }

      const procedure = procedures.find(p => p.procedure_id === procedureId)
      if (!procedure) {
        console.warn(`Procedure ${procedureId} not found`)
        return
      }

      try {
        const preferredToolKey = procedure.preferred_tool_key || procedure.recommended_tools[0] || ''
        const targetClientId = procedure.default_execution_target === 'specific_client' ? desktopToolClientId : ''
        if (procedure.default_execution_target === 'specific_client' && !targetClientId) {
          throw new Error(`规程 ${procedure.title} 需要明确的 Client，但当前 workspace 没有可用桌面工具 Client`)
        }
        
        await createClientOperation(baseUrl, {
          thread_id: clientContext.threadId,
          workspace_id: clientContext.workspace.workspace_id,
          client_id: clientContext.clientId,
          session_id: clientContext.session.session_id,
          title: customTitle || `执行规程: ${procedure.title}`,
          operation_type: 'procedure_call',
          execution_target: procedure.default_execution_target,
          target_client_id: targetClientId || undefined,
          tool_key: preferredToolKey || undefined,
          arguments: {
            procedure_id: procedure.procedure_id,
            procedure_title: procedure.title,
            preferred_tool_key: procedure.preferred_tool_key || undefined,
            preferred_target_client_ids: procedure.preferred_target_client_ids,
            preferred_target_client_types: procedure.preferred_target_client_types,
            tool_target_routing_policy: procedure.tool_target_routing_policy,
          },
        })

        dispatchChat({
          type: 'append_system_turn',
          turn: createSystemTurn(`已发起规程执行: ${procedure.title}`),
        })
      } catch (error) {
        console.error('Failed to execute procedure:', error)
        const transportError = {
          code: 'procedure_error',
          category: 'runtime' as const,
          message: error instanceof Error ? error.message : '执行规程失败',
          retryable: true,
          details: {},
          occurred_at: '',
        }
        dispatchTransport({ type: 'error', error: transportError })
        dispatchChat({
          type: 'append_system_turn',
          turn: createSystemTurn(transportError.message, true),
        })
      }
    },
    [baseUrl, clientContext, desktopToolClientId, procedures, dispatchTransport, dispatchChat]
  )

  return {
    procedures,
    isLoadingProcedures,
    executeProcedure,
    reloadProcedures: loadProcedures,
  }
}
