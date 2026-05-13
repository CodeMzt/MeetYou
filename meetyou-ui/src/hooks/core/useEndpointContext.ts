import { useCallback, useRef, useState, useReducer } from 'react'
import {
  createRuntimeProject,
  createRuntimeThread,
  createRuntimeSession,
  deleteRuntimeThread,
  ensureDefaultRuntimeThread,
  listAvailableEndpoints,
  listRuntimeProjects,
  listRuntimeThreads,
  listRuntimeWorkspaces,
  updateRuntimeProject,
} from '../../runtimeApi'
import { createInitialTransportState, reduceTransportState } from '../../transportState'
import { createSystemTurn } from '../../chatState'
import type { AvailableEndpoint, RuntimeProject, RuntimeSession, RuntimeThread, RuntimeWorkspace, RuntimeErrorPayload } from '../../types'

export const DESKTOP_TOOL_ENDPOINT_REFRESH_INTERVAL_MS = 10000
const RUNTIME_THREAD_LIST_LIMIT = 200

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

function threadBelongsToProject(thread: RuntimeThread, projectId: string): boolean {
  return !projectId || String(thread.project_id || '') === projectId
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

export function mergeRuntimeProjectList(projects: RuntimeProject[], project: RuntimeProject): RuntimeProject[] {
  const nextProjects = projects.map((item) => (
    item.project_id === project.project_id ? project : item
  ))
  return nextProjects.some((item) => item.project_id === project.project_id)
    ? nextProjects
    : [project, ...nextProjects]
}

export function runtimeThreadDeleteErrorMessage(reason: string): string {
  switch (String(reason || '').trim()) {
    case 'default_thread':
      return '这是受保护的默认会话，未被删除。'
    case 'not_found':
      return '会话不存在或已经被删除。'
    case 'already_deleted':
      return ''
    default:
      return '删除会话线程失败。'
  }
}

export async function resolveInitializedEndpointContext(
  currentContext: EndpointContext | null,
  pendingInitialization: Promise<EndpointContext> | null | undefined,
): Promise<EndpointContext | null> {
  if (currentContext) {
    return currentContext
  }
  return pendingInitialization ? await pendingInitialization : null
}

export function useEndpointContext(baseUrl: string, onInitSuccess: (threadId: string) => Promise<void> | void, onError: (turn: any) => void) {
  const initialSessionIdRef = useRef(`desktop-${Math.random().toString(36).substring(2, 9)}`)
  const sourceIdRef = useRef('desktop-app')
  
  const [transportState, dispatchTransport] = useReducer(
    reduceTransportState,
    undefined,
    () => createInitialTransportState(initialSessionIdRef.current, sourceIdRef.current),
  )
  
  const [endpointContext, setEndpointContext] = useState<EndpointContext | null>(null)
  const [desktopToolEndpointId, setDesktopToolEndpointId] = useState('')
  const [runtimeThreads, setRuntimeThreads] = useState<RuntimeThread[]>([])
  const [runtimeProjects, setRuntimeProjects] = useState<RuntimeProject[]>([])
  const [activeProjectId, setActiveProjectId] = useState('')
  const [defaultThreadId, setDefaultThreadId] = useState('')
  const endpointInitPromiseRef = useRef<Promise<EndpointContext> | null>(null)

  const sessionId = endpointContext?.session.session_id || transportState.sessionId
  const endpointId = endpointContext?.endpointId || sourceIdRef.current

  const loadRuntimeThreads = useCallback(async (workspaceId: string) => {
    const threads = await listRuntimeThreads(baseUrl, {
      workspace_id: workspaceId,
      limit: RUNTIME_THREAD_LIST_LIMIT,
    })
    setRuntimeThreads(threads)
    return threads
  }, [baseUrl])

  const loadRuntimeProjects = useCallback(async (workspaceId: string) => {
    const projects = await listRuntimeProjects(baseUrl, {
      workspace_id: workspaceId,
      limit: 200,
    })
    setRuntimeProjects(projects)
    setActiveProjectId((currentProjectId) => {
      if (!currentProjectId || projects.some((project) => project.project_id === currentProjectId)) {
        return currentProjectId
      }
      return ''
    })
    return projects
  }, [baseUrl])

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

  const createContextForThread = useCallback(async (workspace: RuntimeWorkspace, thread: RuntimeThread) => {
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
    await onInitSuccess(thread.thread_id)
    setEndpointContext(nextContext)
    dispatchTransport({ type: 'sync_session', sessionId: session.session_id })
    let nextEndpointId = await refreshDesktopToolEndpoint(nextContext)
    if (!nextEndpointId) {
      for (let attempt = 0; attempt < 4 && !nextEndpointId; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 500))
        nextEndpointId = await refreshDesktopToolEndpoint(nextContext)
      }
    }
    return nextContext
  }, [baseUrl, onInitSuccess, refreshDesktopToolEndpoint])

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
      await loadRuntimeProjects(workspace.workspace_id)
      const thread = await ensureDefaultRuntimeThread(baseUrl, {
        workspace_id: workspace.workspace_id,
        default_key: 'frontend.default',
        title: '桌面聊天',
        mode: workspace.base_mode,
      })
      setDefaultThreadId(thread.thread_id)
      const threads = await loadRuntimeThreads(workspace.workspace_id)
      setRuntimeThreads(threads.some((item) => item.thread_id === thread.thread_id) ? threads : [thread, ...threads])
      return await createContextForThread(workspace, thread)
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
  }, [baseUrl, createContextForThread, endpointContext, loadRuntimeProjects, loadRuntimeThreads, onError])

  const selectRuntimeThread = useCallback(async (threadId: string) => {
    const normalizedThreadId = String(threadId || '').trim()
    if (!normalizedThreadId) {
      return null
    }
    const activeContext = await resolveInitializedEndpointContext(endpointContext, endpointInitPromiseRef.current)
    if (activeContext?.threadId === normalizedThreadId) {
      return activeContext
    }
    const workspaces = await listRuntimeWorkspaces(baseUrl)
    const activeWorkspace = activeContext?.workspace ?? chooseWorkspace(workspaces)
    if (!activeWorkspace) {
      throw new Error('没有可用工作空间')
    }
    const threads = await loadRuntimeThreads(activeWorkspace.workspace_id)
    const thread = threads.find((item) => item.thread_id === normalizedThreadId)
    if (!thread) {
      throw new Error('会话线程不存在或不可见')
    }
    const workspace = workspaces.find((item) => item.workspace_id === (thread.workspace_id || thread.home_workspace_id)) ?? activeWorkspace
    return await createContextForThread(workspace, thread)
  }, [baseUrl, createContextForThread, endpointContext, loadRuntimeThreads])

  const selectRuntimeProject = useCallback(async (projectId: string) => {
    const normalizedProjectId = String(projectId || '').trim()
    if (normalizedProjectId === activeProjectId && endpointContext) {
      return endpointContext
    }
    setActiveProjectId(normalizedProjectId)
    const activeContext = endpointContext ?? (await initializeEndpointContext())
    if (!activeContext) {
      return null
    }
    const threads = await loadRuntimeThreads(activeContext.workspace.workspace_id)
    const currentThread = threads.find((item) => item.thread_id === activeContext.threadId)
    if (currentThread && threadBelongsToProject(currentThread, normalizedProjectId)) {
      return activeContext
    }
    let fallback = normalizedProjectId
      ? threads.find((item) => threadBelongsToProject(item, normalizedProjectId)) ?? null
      : threads.find((item) => item.thread_id === defaultThreadId) ?? threads[0] ?? null
    if (!fallback && normalizedProjectId) {
      const createdThread = await createRuntimeThread(baseUrl, {
        workspace_id: activeContext.workspace.workspace_id,
        title: '新会话',
        mode: activeContext.workspace.base_mode,
        project_id: normalizedProjectId,
      })
      fallback = createdThread
      setRuntimeThreads((currentThreads) => (
        currentThreads.some((item) => item.thread_id === createdThread.thread_id)
          ? currentThreads
          : [createdThread, ...currentThreads]
      ))
    }
    if (!fallback) {
      return null
    }
    return await createContextForThread(activeContext.workspace, fallback)
  }, [activeProjectId, baseUrl, createContextForThread, defaultThreadId, endpointContext, initializeEndpointContext, loadRuntimeThreads])

  const createRuntimeProjectAndRemember = useCallback(async (title: string) => {
    const normalizedTitle = String(title || '').trim()
    if (!normalizedTitle) {
      return null
    }
    const activeContext = await resolveInitializedEndpointContext(endpointContext, endpointInitPromiseRef.current)
    const workspaces = await listRuntimeWorkspaces(baseUrl)
    const activeWorkspace = activeContext?.workspace ?? chooseWorkspace(workspaces)
    if (!activeWorkspace) {
      throw new Error('没有可用工作空间')
    }
    const project = await createRuntimeProject(baseUrl, {
      workspace_id: activeWorkspace.workspace_id,
      title: normalizedTitle,
    })
    setRuntimeProjects((currentProjects) => (
      currentProjects.some((item) => item.project_id === project.project_id)
        ? currentProjects
        : [project, ...currentProjects]
    ))
    return project
  }, [baseUrl, endpointContext])

  const updateRuntimeProjectAndRemember = useCallback(async (
    projectId: string,
    payload: {
      title?: string
      description?: string
      instructions?: string
      memory_scope?: Record<string, unknown>
      metadata?: Record<string, unknown>
    },
  ) => {
    const normalizedProjectId = String(projectId || '').trim()
    if (!normalizedProjectId) {
      throw new Error('项目不可用')
    }
    const project = await updateRuntimeProject(baseUrl, normalizedProjectId, payload)
    setRuntimeProjects((currentProjects) => mergeRuntimeProjectList(currentProjects, project))
    return project
  }, [baseUrl])

  const createAndSelectRuntimeThread = useCallback(async (title?: string, projectIdOverride?: string) => {
    const activeContext = await resolveInitializedEndpointContext(endpointContext, endpointInitPromiseRef.current)
    const workspaces = await listRuntimeWorkspaces(baseUrl)
    const activeWorkspace = activeContext?.workspace ?? chooseWorkspace(workspaces)
    if (!activeWorkspace) {
      throw new Error('没有可用工作空间')
    }
    const projectId = String(projectIdOverride ?? activeProjectId ?? '').trim()
    const thread = await createRuntimeThread(baseUrl, {
      workspace_id: activeWorkspace.workspace_id,
      title: String(title || '').trim() || '新会话',
      mode: activeWorkspace.base_mode,
      project_id: projectId || undefined,
    })
    setActiveProjectId(projectId)
    const threads = await loadRuntimeThreads(activeWorkspace.workspace_id)
    setRuntimeThreads(threads.some((item) => item.thread_id === thread.thread_id) ? threads : [thread, ...threads])
    const workspace = workspaces.find((item) => item.workspace_id === (thread.workspace_id || thread.home_workspace_id)) ?? activeWorkspace
    return await createContextForThread(workspace, thread)
  }, [activeProjectId, baseUrl, createContextForThread, endpointContext, loadRuntimeThreads])

  const deleteRuntimeThreadAndSelect = useCallback(async (threadIdOrIds: string | string[]) => {
    const normalizedThreadIds = Array.from(new Set(
      (Array.isArray(threadIdOrIds) ? threadIdOrIds : [threadIdOrIds])
        .map((threadId) => String(threadId || '').trim())
        .filter(Boolean),
    ))
    if (normalizedThreadIds.length === 0) {
      return null
    }
    const activeContext = endpointContext ?? (await initializeEndpointContext())
    const deletingDefaultThread = Boolean(defaultThreadId && normalizedThreadIds.includes(defaultThreadId))
    for (const normalizedThreadId of normalizedThreadIds) {
      const result = await deleteRuntimeThread(baseUrl, normalizedThreadId, { force: true })
      if (!result.deleted) {
        const message = runtimeThreadDeleteErrorMessage(result.reason)
        if (message) {
          throw new Error(message)
        }
      }
    }
    const threads = await loadRuntimeThreads(activeContext.workspace.workspace_id)
    if (deletingDefaultThread) {
      setDefaultThreadId('')
    }
    if (!normalizedThreadIds.includes(activeContext.threadId)) {
      return null
    }
    const projectThreads = threads.filter((item) => threadBelongsToProject(item, activeProjectId))
    let fallback = deletingDefaultThread
      ? projectThreads[0] ?? threads[0] ?? null
      : projectThreads.find((item) => item.thread_id === defaultThreadId) ?? projectThreads[0] ?? threads[0] ?? null
    if (!fallback) {
      if (activeProjectId) {
        fallback = await createRuntimeThread(baseUrl, {
          workspace_id: activeContext.workspace.workspace_id,
          title: '新会话',
          mode: activeContext.workspace.base_mode,
          project_id: activeProjectId,
        })
      } else {
        fallback = await ensureDefaultRuntimeThread(baseUrl, {
          workspace_id: activeContext.workspace.workspace_id,
          default_key: 'frontend.default',
          title: '桌面聊天',
          mode: activeContext.workspace.base_mode,
        })
        setDefaultThreadId(fallback.thread_id)
      }
      setRuntimeThreads([fallback])
    }
    return await createContextForThread(activeContext.workspace, fallback)
  }, [activeProjectId, baseUrl, createContextForThread, defaultThreadId, endpointContext, initializeEndpointContext, loadRuntimeThreads])

  const refreshRuntimeThreads = useCallback(async (workspaceIdOverride?: string) => {
    const workspaceId = String(workspaceIdOverride || endpointContext?.workspace.workspace_id || '').trim()
    if (!workspaceId) {
      return []
    }
    return await loadRuntimeThreads(workspaceId)
  }, [endpointContext?.workspace.workspace_id, loadRuntimeThreads])

  return {
    endpointContext,
    desktopToolEndpointId: desktopToolEndpointId,
    transportState,
    dispatchTransport,
    sessionId,
    endpointId,
    runtimeThreads,
    runtimeProjects,
    activeProjectId,
    defaultThreadId,
    initializeEndpointContext,
    selectRuntimeThread,
    selectRuntimeProject,
    createAndSelectRuntimeThread,
    createRuntimeProjectAndRemember,
    updateRuntimeProjectAndRemember,
    deleteRuntimeThreadAndSelect,
    refreshRuntimeThreads,
    refreshDesktopToolEndpoint,
    refreshWorkspace,
  }
}
