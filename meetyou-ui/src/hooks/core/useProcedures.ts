import { useState, useCallback, useEffect } from 'react'
import { listClientProcedures, createClientOperation } from '../../clientApi'
import { createSystemTurn } from '../../chatState'
import type { ClientContext } from './useClientContext'
import type { ClientProcedure } from '../../types'

export function useProcedures(
  baseUrl: string,
  clientContext: ClientContext | null,
  desktopAgentId: string,
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
        const preferredCapabilityRef = procedure.preferred_capability_ref || procedure.recommended_capabilities[0] || ''
        const targetAgentId = procedure.default_execution_target === 'specific_agent' ? desktopAgentId : ''
        if (procedure.default_execution_target === 'specific_agent' && !targetAgentId) {
          throw new Error(`规程 ${procedure.title} 需要明确的 Agent，但当前 workspace 没有可用桌面 Agent`)
        }
        
        await createClientOperation(baseUrl, {
          thread_id: clientContext.threadId,
          workspace_id: clientContext.workspace.workspace_id,
          client_id: clientContext.clientId,
          session_id: clientContext.session.session_id,
          title: customTitle || `执行规程: ${procedure.title}`,
          operation_type: 'procedure_call',
          execution_target: procedure.default_execution_target,
          target_agent_id: targetAgentId || undefined,
          capability_id: preferredCapabilityRef || undefined,
          arguments: {
            procedure_id: procedure.procedure_id,
            procedure_title: procedure.title,
            preferred_capability_ref: procedure.preferred_capability_ref || undefined,
            preferred_agent_ids: procedure.preferred_agent_ids,
            preferred_agent_types: procedure.preferred_agent_types,
            agent_routing_policy: procedure.agent_routing_policy,
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
    [baseUrl, clientContext, desktopAgentId, procedures, dispatchTransport, dispatchChat]
  )

  return {
    procedures,
    isLoadingProcedures,
    executeProcedure,
    reloadProcedures: loadProcedures,
  }
}
