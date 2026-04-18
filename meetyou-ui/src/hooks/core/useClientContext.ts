import { useCallback, useRef, useState, useReducer } from 'react'
import {
  createClientSession,
  createClientThread,
  listClientAvailableAgents,
  listClientWorkspaces,
} from '../../clientApi'
import { createInitialTransportState, reduceTransportState } from '../../transportState'
import { createSystemTurn } from '../../chatState'
import type { ClientAvailableAgent, ClientSession, ClientWorkspace, RuntimeErrorPayload } from '../../types'

export const DESKTOP_AGENT_REFRESH_INTERVAL_MS = 10000

export interface ClientContext {
  workspace: ClientWorkspace
  threadId: string
  session: ClientSession
  clientId: string
}

export function chooseDesktopAgent(agents: ClientAvailableAgent[], workspaceId: string, clientId: string): string {
  const matched = agents.find(
    (agent) =>
      agent.agent_type === 'desktop' &&
      agent.status === 'online' &&
      agent.workspace_ids.includes(workspaceId) &&
      (!agent.owner_client_id || agent.owner_client_id === clientId),
  )
  return matched?.agent_id || ''
}

export async function resolveDesktopAgentId(
  loadAvailableAgents: (baseUrl: string, workspaceId: string) => Promise<ClientAvailableAgent[]>,
  baseUrl: string,
  workspaceId: string,
  clientId: string,
): Promise<string> {
  const availableAgents = await loadAvailableAgents(baseUrl, workspaceId)
  return chooseDesktopAgent(availableAgents, workspaceId, clientId)
}

function chooseWorkspace(workspaces: ClientWorkspace[]): ClientWorkspace | null {
  return workspaces.find((item) => item.workspace_id === 'personal') ?? workspaces[0] ?? null
}

function buildTransportError(error: Error): RuntimeErrorPayload {
  return {
    code: 'transport_error',
    category: 'dependency',
    message: error.message || '连接后端失败，请稍后重试',
    retryable: true,
    details: {},
    occurred_at: '',
  }
}

export function useClientContext(baseUrl: string, onInitSuccess: (threadId: string) => void, onError: (turn: any) => void) {
  const initialSessionIdRef = useRef(`desktop-${Math.random().toString(36).substring(2, 9)}`)
  const sourceIdRef = useRef('desktop-app')
  
  const [transportState, dispatchTransport] = useReducer(
    reduceTransportState,
    undefined,
    () => createInitialTransportState(initialSessionIdRef.current, sourceIdRef.current),
  )
  
  const [clientContext, setClientContext] = useState<ClientContext | null>(null)
  const [desktopAgentId, setDesktopAgentId] = useState('')
  const clientInitPromiseRef = useRef<Promise<ClientContext> | null>(null)

  const sessionId = clientContext?.session.session_id || transportState.sessionId
  const clientId = clientContext?.clientId || sourceIdRef.current

  const refreshAvailableAgents = useCallback(async (contextOverride?: ClientContext | null) => {
    const activeContext = contextOverride ?? clientContext
    if (!activeContext) {
      return ''
    }
    try {
      const nextAgentId = await resolveDesktopAgentId(
        listClientAvailableAgents,
        baseUrl,
        activeContext.workspace.workspace_id,
        activeContext.clientId,
      )
      setDesktopAgentId((current) => (current === nextAgentId ? current : nextAgentId))
      return nextAgentId
    } catch (error) {
      console.warn('Failed to load available agents:', error)
      return ''
    }
  }, [baseUrl, clientContext])

  const refreshWorkspace = useCallback(async (workspaceIdOverride?: string) => {
    const activeContext = clientContext
    const workspaceId = String(workspaceIdOverride || activeContext?.workspace.workspace_id || '').trim()
    if (!activeContext || !workspaceId) {
      return null
    }
    try {
      const workspaces = await listClientWorkspaces(baseUrl)
      const nextWorkspace = workspaces.find((item) => item.workspace_id === workspaceId) ?? null
      if (!nextWorkspace) {
        return null
      }
      setClientContext((current) => {
        if (!current || current.workspace.workspace_id !== workspaceId) {
          return current
        }
        return {
          ...current,
          workspace: nextWorkspace,
        }
      })
      return nextWorkspace
    } catch (error) {
      console.warn('Failed to refresh workspace:', error)
      return null
    }
  }, [baseUrl, clientContext])

  const initializeClientContext = useCallback(async () => {
    if (clientContext) {
      return clientContext
    }
    if (clientInitPromiseRef.current) {
      return clientInitPromiseRef.current
    }

    const promise = (async () => {
      const workspaces = await listClientWorkspaces(baseUrl)
      const workspace = chooseWorkspace(workspaces)
      if (!workspace) {
        throw new Error('没有可用工作空间')
      }
      const thread = await createClientThread(baseUrl, {
        workspace_id: workspace.workspace_id,
        title: 'Desktop Chat',
        mode: workspace.base_mode,
      })
      const session = await createClientSession(baseUrl, {
        thread_id: thread.thread_id,
        workspace_id: workspace.workspace_id,
        client_id: sourceIdRef.current,
        client_type: 'electron',
        display_name: '桌面应用',
      })
      const nextContext: ClientContext = {
        workspace,
        threadId: thread.thread_id,
        session,
        clientId: sourceIdRef.current,
      }
      setClientContext(nextContext)

      let nextAgentId = await refreshAvailableAgents(nextContext)
      if (!nextAgentId) {
        for (let attempt = 0; attempt < 4 && !nextAgentId; attempt += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 500))
          nextAgentId = await refreshAvailableAgents(nextContext)
        }
      }
      dispatchTransport({ type: 'sync_session', sessionId: session.session_id })
      onInitSuccess(thread.thread_id)
      return nextContext
    })()

    clientInitPromiseRef.current = promise
    try {
      return await promise
    } catch (error) {
      const transportError = buildTransportError(
        error instanceof Error ? error : new Error('初始化客户端上下文失败'),
      )
      dispatchTransport({ type: 'error', error: transportError })
      onError(createSystemTurn(transportError.message, true))
      throw error
    } finally {
      if (clientInitPromiseRef.current === promise) {
        clientInitPromiseRef.current = null
      }
    }
  }, [baseUrl, clientContext, onInitSuccess, onError, refreshAvailableAgents])

  return {
    clientContext,
    desktopAgentId,
    transportState,
    dispatchTransport,
    sessionId,
    clientId,
    initializeClientContext,
    refreshAvailableAgents,
    refreshWorkspace,
  }
}
