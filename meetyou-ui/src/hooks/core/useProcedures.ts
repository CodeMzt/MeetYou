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
        const targetEndpointId = procedure.default_execution_target === 'specific_client' ? desktopToolClientId : ''
        if (procedure.default_execution_target === 'specific_client' && !targetEndpointId) {
          throw new Error(`瑙勭▼ ${procedure.title} 闇€瑕佹槑纭殑 Client锛屼絾褰撳墠 workspace 娌℃湁鍙敤妗岄潰宸ュ叿 Client`)
        }
        
        await createClientOperation(baseUrl, {
          thread_id: clientContext.threadId,
          workspace_id: clientContext.workspace.workspace_id,
          client_id: clientContext.clientId,
          session_id: clientContext.session.session_id,
          title: customTitle || `鎵ц瑙勭▼: ${procedure.title}`,
          operation_type: 'procedure_call',
          execution_target: procedure.default_execution_target,
          target_endpoint_id: targetEndpointId || undefined,
          tool_key: preferredToolKey || undefined,
          arguments: {
            procedure_id: procedure.procedure_id,
            procedure_title: procedure.title,
            preferred_tool_key: procedure.preferred_tool_key || undefined,
            preferred_target_endpoint_ids: procedure.preferred_target_endpoint_ids,
            preferred_endpoint_provider_types: procedure.preferred_endpoint_provider_types,
            tool_target_routing_policy: procedure.tool_target_routing_policy,
          },
        })

        dispatchChat({
          type: 'append_system_turn',
          turn: createSystemTurn(`宸插彂璧疯绋嬫墽琛? ${procedure.title}`),
        })
      } catch (error) {
        console.error('Failed to execute procedure:', error)
        const transportError = {
          code: 'procedure_error',
          category: 'runtime' as const,
          message: error instanceof Error ? error.message : '鎵ц瑙勭▼澶辫触',
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
