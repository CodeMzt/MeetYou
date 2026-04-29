import { useCallback, useRef, useState, useReducer } from 'react'
import {
  createRuntimeSession,
  createRuntimeThread,
  listAvailableEndpoints,
  listRuntimeWorkspaces,
} from '../../runtimeApi'
import { createInitialTransportState, reduceTransportState } from '../../transportState'
import { createSystemTurn } from '../../chatState'
import type { AvailableEndpoint, RuntimeSession, RuntimeWorkspace, RuntimeErrorPayload } from '../../types'

export const DESKTOP_TOOL_ENDPOINT_REFRESH_INTERVAL_MS = 10000

export interface EndpointContext {
  workspace: RuntimeWorkspace
  threadId: string
  session: RuntimeSession
  endpointId: string
}

export function chooseDesktopToolEndpoint(endpoints: AvailableEndpoint[], workspaceId: string, endpointId: string): string {
  const matched = endpoints.find(
    (endpoint) =>
      endpoint.provider_type === 'desktop' &&
      endpoint.status === 'online' &&
      endpoint.workspace_ids.includes(workspaceId) &&
      (endpoint.endpoint_id === endpointId || endpoint.executable_tools.includes('file.read') || endpoint.executable_tools.includes('shell.exec')),
  )
  return matched?.endpoint_id || ''
}

export async function resolveDesktopToolEndpointId(
  loadAvailableEndpoints: (baseUrl: string, workspaceId: string) => Promise<AvailableEndpoint[]>,
  baseUrl: string,
  workspaceId: string,
  endpointId: string,
): Promise<string> {
  const availableEndpoints = await loadAvailableEndpoints(baseUrl, workspaceId)
  return chooseDesktopToolEndpoint(availableEndpoints, workspaceId, endpointId)
}

function chooseWorkspace(workspaces: RuntimeWorkspace[]): RuntimeWorkspace | null {
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

export function useEndpointContext(baseUrl: string, onInitSuccess: (threadId: string) => void, onError: (turn: any) => void) {
  const initialSessionIdRef = useRef(`desktop-${Math.random().toString(36).substring(2, 9)}`)
  const sourceIdRef = useRef('desktop-app')
  
  const [transportState, dispatchTransport] = useReducer(
    reduceTransportState,
    undefined,
    () => createInitialTransportState(initialSessionIdRef.current, sourceIdRef.current),
  )
  
  const [endpointContext, setEndpointContext] = useState<EndpointContext | null>(null)
  const [desktopToolEndpointId, setDesktopToolEndpointId] = useState('')
  const endpointInitPromiseRef = useRef<Promise<EndpointContext> | null>(null)

  const sessionId = endpointContext?.session.session_id || transportState.sessionId
  const endpointId = endpointContext?.endpointId || sourceIdRef.current

  const refreshDesktopToolEndpoint = useCallback(async (contextOverride?: EndpointContext | null) => {
    const activeContext = contextOverride ?? endpointContext
    if (!activeContext) {
      return ''
    }
    try {
      const nextEndpointId = await resolveDesktopToolEndpointId(
        listAvailableEndpoints,
        baseUrl,
        activeContext.workspace.workspace_id,
        activeContext.endpointId,
      )
      setDesktopToolEndpointId((current) => (current === nextEndpointId ? current : nextEndpointId))
      return nextEndpointId
    } catch (error) {
      console.warn('加载可用端点工具目标失败:', error)
      return ''
    }
  }, [baseUrl, endpointContext])

  const refreshWorkspace = useCallback(async (workspaceIdOverride?: string) => {
    const activeContext = endpointContext
    const workspaceId = String(workspaceIdOverride || activeContext?.workspace.workspace_id || '').trim()
    if (!activeContext || !workspaceId) {
      return null
    }
    try {
      const workspaces = await listRuntimeWorkspaces(baseUrl)
      const nextWorkspace = workspaces.find((item) => item.workspace_id === workspaceId) ?? null
      if (!nextWorkspace) {
        return null
      }
      setEndpointContext((current) => {
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
  }, [baseUrl, endpointContext])

  const initializeEndpointContext = useCallback(async () => {
    if (endpointContext) {
      return endpointContext
    }
    if (endpointInitPromiseRef.current) {
      return endpointInitPromiseRef.current
    }

    const promise = (async () => {
      const workspaces = await listRuntimeWorkspaces(baseUrl)
      const workspace = chooseWorkspace(workspaces)
      if (!workspace) {
        throw new Error('没有可用工作空间')
      }
      const thread = await createRuntimeThread(baseUrl, {
        home_workspace_id: workspace.workspace_id,
        workspace_id: workspace.workspace_id,
        title: '桌面聊天',
        mode: workspace.base_mode,
      })
      const session = await createRuntimeSession(baseUrl, {
        thread_id: thread.thread_id,
        active_workspace_id: workspace.workspace_id,
        workspace_id: workspace.workspace_id,
        endpoint_id: sourceIdRef.current,
        endpoint_type: 'electron',
        display_name: '桌面应用',
      })
      const nextContext: EndpointContext = {
        workspace,
        threadId: thread.thread_id,
        session,
        endpointId: sourceIdRef.current,
      }
      setEndpointContext(nextContext)

      let nextEndpointId = await refreshDesktopToolEndpoint(nextContext)
      if (!nextEndpointId) {
        for (let attempt = 0; attempt < 4 && !nextEndpointId; attempt += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 500))
          nextEndpointId = await refreshDesktopToolEndpoint(nextContext)
        }
      }
      dispatchTransport({ type: 'sync_session', sessionId: session.session_id })
      onInitSuccess(thread.thread_id)
      return nextContext
    })()

    endpointInitPromiseRef.current = promise
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
      if (endpointInitPromiseRef.current === promise) {
        endpointInitPromiseRef.current = null
      }
    }
  }, [baseUrl, endpointContext, onInitSuccess, onError, refreshDesktopToolEndpoint])

  return {
    endpointContext,
    desktopToolEndpointId: desktopToolEndpointId,
    transportState,
    dispatchTransport,
    sessionId,
    endpointId,
    initializeEndpointContext,
    refreshDesktopToolEndpoint,
    refreshWorkspace,
  }
}
