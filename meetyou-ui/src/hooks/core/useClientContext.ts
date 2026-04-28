import { useCallback, useRef, useState, useReducer } from 'react'
import {
  createClientSession,
  createClientThread,
  listAvailableEndpoints,
  listClientWorkspaces,
} from '../../clientApi'
import { createInitialTransportState, reduceTransportState } from '../../transportState'
import { createSystemTurn } from '../../chatState'
import type { AvailableEndpoint, ClientSession, ClientWorkspace, RuntimeErrorPayload } from '../../types'

export const DESKTOP_TOOL_CLIENT_REFRESH_INTERVAL_MS = 10000

export interface ClientContext {
  workspace: ClientWorkspace
  threadId: string
  session: ClientSession
  clientId: string
}

export function chooseDesktopToolEndpoint(endpoints: AvailableEndpoint[], workspaceId: string, clientId: string): string {
  const matched = endpoints.find(
    (endpoint) =>
      endpoint.provider_type === 'desktop' &&
      endpoint.status === 'online' &&
      endpoint.workspace_ids.includes(workspaceId) &&
      (endpoint.endpoint_id === clientId || endpoint.executable_tools.includes('file.read') || endpoint.executable_tools.includes('shell.exec')),
  )
  return matched?.endpoint_id || ''
}

export async function resolveDesktopToolEndpointId(
  loadAvailableEndpoints: (baseUrl: string, workspaceId: string) => Promise<AvailableEndpoint[]>,
  baseUrl: string,
  workspaceId: string,
  clientId: string,
): Promise<string> {
  const availableEndpoints = await loadAvailableEndpoints(baseUrl, workspaceId)
  return chooseDesktopToolEndpoint(availableEndpoints, workspaceId, clientId)
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
  const [desktopToolEndpointId, setDesktopToolEndpointId] = useState('')
  const clientInitPromiseRef = useRef<Promise<ClientContext> | null>(null)

  const sessionId = clientContext?.session.session_id || transportState.sessionId
  const clientId = clientContext?.clientId || sourceIdRef.current

  const refreshDesktopToolClient = useCallback(async (contextOverride?: ClientContext | null) => {
    const activeContext = contextOverride ?? clientContext
    if (!activeContext) {
      return ''
    }
    try {
      const nextEndpointId = await resolveDesktopToolEndpointId(
        listAvailableEndpoints,
        baseUrl,
        activeContext.workspace.workspace_id,
        activeContext.clientId,
      )
      setDesktopToolEndpointId((current) => (current === nextEndpointId ? current : nextEndpointId))
      return nextEndpointId
    } catch (error) {
      console.warn('加载可用端点工具目标失败:', error)
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
          session: {
            ...current.session,
            active_workspace_id: workspaceId,
            workspace_id: workspaceId,
          },
        }
      })
      return nextWorkspace
    } catch (error) {
      console.warn('刷新工作区失败:', error)
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
        home_workspace_id: workspace.workspace_id,
        workspace_id: workspace.workspace_id,
        title: '桌面聊天',
        mode: workspace.base_mode,
      })
      const session = await createClientSession(baseUrl, {
        thread_id: thread.thread_id,
        active_workspace_id: workspace.workspace_id,
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

      let nextClientId = await refreshDesktopToolClient(nextContext)
      if (!nextClientId) {
        for (let attempt = 0; attempt < 4 && !nextClientId; attempt += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 500))
          nextClientId = await refreshDesktopToolClient(nextContext)
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
  }, [baseUrl, clientContext, onInitSuccess, onError, refreshDesktopToolClient])

  return {
    clientContext,
    desktopToolClientId: desktopToolEndpointId,
    transportState,
    dispatchTransport,
    sessionId,
    clientId,
    initializeClientContext,
    refreshDesktopToolClient,
    refreshWorkspace,
  }
}
