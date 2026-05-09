import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChatTurn, StatusFeedback } from '../types'
import { DEFAULT_BASE_URL, WINDOW_SYNC_CHANNEL } from '../windowBridge'
import {
  checkoutRuntimeThreadCheckpoint,
  createRuntimeProjectSourceFromMessage,
  createRuntimeResearchTask,
  createRuntimeThreadCheckpoint,
  downloadRuntimeArtifact,
  editRetryRuntimeMessage,
  listRuntimeProjectArtifacts,
  listRuntimeProjectSources,
  listRuntimeResearchTasks,
  listRuntimeThreadBranches,
  listRuntimeThreadCheckpoints,
  patchRuntimeResearchTask,
  restoreRuntimeThreadCheckpoint,
} from '../runtimeApi'
import type { RuntimeArtifact, RuntimeConversationCheckpoint, RuntimeProjectSource, RuntimeResearchTask, RuntimeThreadBranch } from '../types'
import {
  DESKTOP_TOOL_ENDPOINT_REFRESH_INTERVAL_MS,
  useEndpointContext,
  useMeetYouSocket,
  useChatSession,
  useOperations,
} from './core'
import { parseEndpointWsPayload } from '../protocolClient'

const STATUS_FEEDBACK_TTL_MS = 6000

export function useMeetYou(baseUrl: string = DEFAULT_BASE_URL) {
  const autoInitializeAttemptedRef = useRef(false)
  const [statusFeedback, setStatusFeedback] = useState<StatusFeedback | null>(null)
  const [threadBranches, setThreadBranches] = useState<RuntimeThreadBranch[]>([])
  const [threadCheckpoints, setThreadCheckpoints] = useState<RuntimeConversationCheckpoint[]>([])
  const [projectSources, setProjectSources] = useState<RuntimeProjectSource[]>([])
  const [projectSourcesBusy, setProjectSourcesBusy] = useState(false)
  const [projectArtifacts, setProjectArtifacts] = useState<RuntimeArtifact[]>([])
  const [projectArtifactsBusy, setProjectArtifactsBusy] = useState(false)
  const [researchTasks, setResearchTasks] = useState<RuntimeResearchTask[]>([])
  const [researchBusy, setResearchBusy] = useState(false)

  const {
    endpointContext,
    desktopToolEndpointId,
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
  } = useEndpointContext(baseUrl, async (threadId) => {
    await loadThreadHistory(threadId)
  }, (turn) => {
    dispatchChat({ type: 'append_system_turn', turn })
  })

  const {
    endpointConnectionState,
    refreshHealth,
  } = useMeetYouSocket(
    baseUrl,
    endpointContext,
    (rawPayload) => applyEndpointWsUpdate(rawPayload),
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
    endpointContext,
    sessionId,
    endpointId,
    dispatchTransport,
    initializeEndpointContext
  )

  const {
    operations,
    decideOperationApproval,
    processWsUpdateForOperations,
  } = useOperations(
    baseUrl,
    endpointContext,
    initializeEndpointContext,
    dispatchChat
  )

  useEffect(() => {
    if (!statusFeedback) {
      return
    }
    const timer = window.setTimeout(() => {
      setStatusFeedback((current) => current?.id === statusFeedback.id ? null : current)
    }, STATUS_FEEDBACK_TTL_MS)
    return () => window.clearTimeout(timer)
  }, [statusFeedback])

  const applyEndpointWsUpdate = useCallback((rawPayload: unknown) => {
    const update = parseEndpointWsPayload(rawPayload)
    
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

    if (update.kind === 'thread_switched') {
      if (update.targetThreadId && update.targetThreadId !== endpointContext?.threadId) {
        void selectRuntimeThread(update.targetThreadId)
      }
      return
    }

    if (update.kind === 'thread_deleted') {
      if (update.deletedThreadId && update.deletedThreadId === endpointContext?.threadId) {
        if (update.fallbackThreadId) {
          void selectRuntimeThread(update.fallbackThreadId)
        } else {
          void initializeEndpointContext()
        }
      } else {
        void refreshRuntimeThreads(update.workspaceId)
      }
      return
    }

    // Domain level handlers
    processWsUpdateForChat(update)
    processWsUpdateForOperations(update)

    if (update.kind === 'workspace_changed') {
      void refreshWorkspace(update.workspaceId || update.activeWorkspaceId)
      void refreshDesktopToolEndpoint()
    }

    if (
      update.kind === 'message_completed' ||
      update.kind === 'confirm_resolved' ||
      update.kind === 'operation_updated'
    ) {
      return
    }
  }, [
    dispatchTransport,
    endpointContext?.threadId,
    initializeEndpointContext,
    processWsUpdateForChat,
    processWsUpdateForOperations,
    refreshDesktopToolEndpoint,
    refreshRuntimeThreads,
    refreshWorkspace,
    selectRuntimeThread,
  ])

  useEffect(() => {
    if (autoInitializeAttemptedRef.current) {
      return
    }
    autoInitializeAttemptedRef.current = true
    void initializeEndpointContext()
  }, [initializeEndpointContext])

  useEffect(() => {
    if (!endpointContext || transportState.connectionState !== 'connected') {
      return
    }
    void refreshHealth()
  }, [endpointContext, refreshHealth, transportState.connectionState])

  useEffect(() => {
    if (!endpointContext) {
      return
    }
    void refreshDesktopToolEndpoint(endpointContext)
    const timer = window.setInterval(() => {
      void refreshDesktopToolEndpoint(endpointContext)
    }, DESKTOP_TOOL_ENDPOINT_REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [endpointContext, refreshDesktopToolEndpoint])

  const refreshThreadVersionState = useCallback(async (threadIdOverride?: string) => {
    const targetThreadId = String(threadIdOverride || endpointContext?.threadId || '').trim()
    if (!targetThreadId) {
      setThreadBranches([])
      setThreadCheckpoints([])
      return { branches: [], checkpoints: [] }
    }
    try {
      const [branches, checkpoints] = await Promise.all([
        listRuntimeThreadBranches(baseUrl, targetThreadId),
        listRuntimeThreadCheckpoints(baseUrl, targetThreadId),
      ])
      setThreadBranches(branches)
      setThreadCheckpoints(checkpoints)
      return { branches, checkpoints }
    } catch (error) {
      console.warn('刷新分支/检查点失败:', error)
      setThreadBranches([])
      setThreadCheckpoints([])
      return { branches: [], checkpoints: [] }
    }
  }, [baseUrl, endpointContext?.threadId])

  useEffect(() => {
    if (!endpointContext?.threadId) {
      setThreadBranches([])
      setThreadCheckpoints([])
      return
    }
    void refreshThreadVersionState(endpointContext.threadId)
  }, [endpointContext?.threadId, refreshThreadVersionState])

  const refreshResearchTasks = useCallback(async (projectIdOverride?: string) => {
    const projectId = String(projectIdOverride ?? activeProjectId ?? '').trim()
    try {
      const tasks = await listRuntimeResearchTasks(baseUrl, {
        project_id: projectId || undefined,
        limit: 50,
      })
      setResearchTasks(tasks)
      return tasks
    } catch (error) {
      console.warn('刷新研究任务失败:', error)
      setResearchTasks([])
      return []
    }
  }, [activeProjectId, baseUrl])

  useEffect(() => {
    void refreshResearchTasks(activeProjectId)
  }, [activeProjectId, refreshResearchTasks])

  const refreshProjectSources = useCallback(async (projectIdOverride?: string) => {
    const projectId = String(projectIdOverride ?? activeProjectId ?? '').trim()
    if (!projectId) {
      setProjectSources([])
      return []
    }
    setProjectSourcesBusy(true)
    try {
      const sources = await listRuntimeProjectSources(baseUrl, projectId, { limit: 100 })
      setProjectSources(sources)
      return sources
    } catch (error) {
      console.warn('刷新项目源失败:', error)
      setProjectSources([])
      return []
    } finally {
      setProjectSourcesBusy(false)
    }
  }, [activeProjectId, baseUrl])

  useEffect(() => {
    void refreshProjectSources(activeProjectId)
  }, [activeProjectId, refreshProjectSources])

  const refreshProjectArtifacts = useCallback(async (projectIdOverride?: string) => {
    const projectId = String(projectIdOverride ?? activeProjectId ?? '').trim()
    if (!projectId) {
      setProjectArtifacts([])
      return []
    }
    setProjectArtifactsBusy(true)
    try {
      const artifacts = await listRuntimeProjectArtifacts(baseUrl, projectId, { limit: 100 })
      setProjectArtifacts(artifacts)
      return artifacts
    } catch (error) {
      console.warn('刷新项目产物失败:', error)
      setProjectArtifacts([])
      return []
    } finally {
      setProjectArtifactsBusy(false)
    }
  }, [activeProjectId, baseUrl])

  useEffect(() => {
    void refreshProjectArtifacts(activeProjectId)
  }, [activeProjectId, refreshProjectArtifacts])

  const effectiveConnectionState = useMemo(() => {
    if (!endpointContext || endpointConnectionState === 'connecting' || transportState.connectionState === 'connecting') {
      return 'connecting' as const
    }
    if (endpointConnectionState === 'disconnected' || transportState.connectionState === 'disconnected') {
      return 'disconnected' as const
    }
    return 'connected' as const
  }, [endpointConnectionState, endpointContext, transportState.connectionState])

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
      threadId: endpointContext?.threadId || '',
      workspace: endpointContext?.workspace || null,
      connectionState: effectiveConnectionState,
      desktopToolsAvailable: Boolean(desktopToolEndpointId),
      operations,
      approvalDisplay,
      pendingHumanInput,
    })
  }, [
    approvalDisplay,
    baseUrl,
    endpointContext?.threadId,
    endpointContext?.workspace,
    desktopToolEndpointId,
    effectiveConnectionState,
    operations,
    pendingHumanInput,
  ])

  const saveMessageAsProjectSource = useCallback(async (message: ChatTurn) => {
    const projectId = String(activeProjectId || '').trim()
    const messageId = String(message.id || '').trim()
    if (!projectId) {
      throw new Error('请先选择项目')
    }
    if (!messageId || message.temporary || !messageId.startsWith('msg_')) {
      throw new Error('消息尚未持久化，不能保存为项目源')
    }
    const title = `${message.role === 'assistant' ? 'Assistant' : 'User'} message ${messageId.slice(-8)}`
    const source = await createRuntimeProjectSourceFromMessage(baseUrl, projectId, {
      message_id: messageId,
      title,
      metadata: {
        role: message.role,
        thread_id: endpointContext?.threadId || '',
      },
    })
    void refreshProjectSources(projectId)
    setStatusFeedback({
      id: `project-source-${Date.now()}`,
      text: '已保存为项目源',
      tone: 'success',
      createdAt: Date.now(),
    })
    return source
  }, [activeProjectId, baseUrl, endpointContext?.threadId, refreshProjectSources])

  const editRetryMessage = useCallback(async (message: ChatTurn, content: string) => {
    const messageId = String(message.id || '').trim()
    const nextContent = String(content || '').trim()
    if (!messageId || message.temporary || !messageId.startsWith('msg_')) {
      throw new Error('消息尚未持久化，不能编辑重试')
    }
    if (message.role !== 'user') {
      throw new Error('只能编辑用户消息并重试')
    }
    if (!nextContent) {
      throw new Error('编辑内容不能为空')
    }
    const result = await editRetryRuntimeMessage(baseUrl, messageId, {
      content: nextContent,
      title: `Edit retry ${messageId.slice(-8)}`,
    })
    const targetThreadId = result.message.thread_id || endpointContext?.threadId || ''
    if (targetThreadId) {
      await loadThreadHistory(targetThreadId)
    }
    await refreshRuntimeThreads(endpointContext?.workspace.workspace_id)
    await refreshThreadVersionState(targetThreadId)
    setStatusFeedback({
      id: `edit-retry-${Date.now()}`,
      text: result.replay_status === 'queued' ? '已创建分支并开始重试' : '已创建编辑重试分支',
      tone: 'success',
      createdAt: Date.now(),
    })
    return result
  }, [baseUrl, endpointContext?.threadId, endpointContext?.workspace.workspace_id, loadThreadHistory, refreshRuntimeThreads, refreshThreadVersionState])

  const createCheckpoint = useCallback(async (title?: string) => {
    const threadId = String(endpointContext?.threadId || '').trim()
    if (!threadId) {
      throw new Error('没有可用会话')
    }
    const checkpoint = await createRuntimeThreadCheckpoint(baseUrl, threadId, {
      title: String(title || '').trim() || `检查点 ${new Date().toLocaleTimeString()}`,
      checkpoint_type: 'manual',
    })
    await refreshThreadVersionState(threadId)
    setStatusFeedback({
      id: `checkpoint-${Date.now()}`,
      text: '已创建检查点',
      tone: 'success',
      createdAt: Date.now(),
    })
    return checkpoint
  }, [baseUrl, endpointContext?.threadId, refreshThreadVersionState])

  const restoreCheckpoint = useCallback(async (checkpointId: string) => {
    const threadId = String(endpointContext?.threadId || '').trim()
    if (!threadId) {
      throw new Error('没有可用会话')
    }
    const checkpoint = await restoreRuntimeThreadCheckpoint(baseUrl, threadId, checkpointId)
    await loadThreadHistory(threadId)
    await refreshThreadVersionState(threadId)
    setStatusFeedback({
      id: `checkpoint-restore-${Date.now()}`,
      text: '已恢复到检查点',
      tone: 'success',
      createdAt: Date.now(),
    })
    return checkpoint
  }, [baseUrl, endpointContext?.threadId, loadThreadHistory, refreshThreadVersionState])

  const checkoutCheckpoint = useCallback(async (checkpointId: string) => {
    const threadId = String(endpointContext?.threadId || '').trim()
    if (!threadId) {
      throw new Error('没有可用会话')
    }
    const branch = await checkoutRuntimeThreadCheckpoint(baseUrl, threadId, checkpointId, {
      title: `签出 ${new Date().toLocaleTimeString()}`,
    })
    await loadThreadHistory(threadId)
    await refreshRuntimeThreads(endpointContext?.workspace.workspace_id)
    await refreshThreadVersionState(threadId)
    setStatusFeedback({
      id: `checkpoint-checkout-${Date.now()}`,
      text: '已从检查点签出分支',
      tone: 'success',
      createdAt: Date.now(),
    })
    return branch
  }, [baseUrl, endpointContext?.threadId, endpointContext?.workspace.workspace_id, loadThreadHistory, refreshRuntimeThreads, refreshThreadVersionState])

  const createResearchTask = useCallback(async (topic: string) => {
    const nextTopic = String(topic || '').trim()
    if (!nextTopic) {
      throw new Error('研究主题不能为空')
    }
    setResearchBusy(true)
    try {
      const task = await createRuntimeResearchTask(baseUrl, {
        topic: nextTopic,
        project_id: activeProjectId || undefined,
        thread_id: endpointContext?.threadId || undefined,
        source_policy: {
          source_adapters: ['web', 'arxiv', 'openalex', 'crossref', 'semantic_scholar'],
          include_project_sources: Boolean(activeProjectId),
        },
        output_format: 'markdown',
        metadata: { created_from: 'desktop.research_panel' },
      })
      await refreshResearchTasks(activeProjectId)
      setStatusFeedback({
        id: `research-create-${Date.now()}`,
        text: '已创建研究计划',
        tone: 'success',
        createdAt: Date.now(),
      })
      return task
    } finally {
      setResearchBusy(false)
    }
  }, [activeProjectId, baseUrl, endpointContext?.threadId, refreshResearchTasks])

  const patchResearchTask = useCallback(async (researchTaskId: string, payload: Parameters<typeof patchRuntimeResearchTask>[2], successText: string) => {
    setResearchBusy(true)
    try {
      const task = await patchRuntimeResearchTask(baseUrl, researchTaskId, payload)
      await refreshResearchTasks(activeProjectId)
      void refreshProjectArtifacts(activeProjectId)
      setStatusFeedback({
        id: `research-${Date.now()}`,
        text: successText,
        tone: 'success',
        createdAt: Date.now(),
      })
      return task
    } finally {
      setResearchBusy(false)
    }
  }, [activeProjectId, baseUrl, refreshProjectArtifacts, refreshResearchTasks])

  const approveResearchTask = useCallback((researchTaskId: string) => (
    patchResearchTask(researchTaskId, { action: 'approve' }, '已确认研究计划')
  ), [patchResearchTask])

  const startResearchTask = useCallback((researchTaskId: string) => (
    patchResearchTask(researchTaskId, { action: 'start' }, '研究任务已开始')
  ), [patchResearchTask])

  const cancelResearchTask = useCallback((researchTaskId: string) => (
    patchResearchTask(researchTaskId, { action: 'cancel' }, '研究任务已取消')
  ), [patchResearchTask])

  const saveResearchTaskPlan = useCallback((researchTaskId: string, plan: Record<string, unknown>) => (
    patchResearchTask(researchTaskId, { plan }, '已保存研究计划')
  ), [patchResearchTask])

  const downloadArtifactFile = useCallback(async (
    artifact: Pick<RuntimeArtifact, 'artifact_id' | 'filename'>,
    fallbackFilename: string,
    successText: string,
  ) => {
    const artifactId = String(artifact.artifact_id || '').trim()
    if (!artifactId) {
      throw new Error('产物不可下载')
    }
    const blob = await downloadRuntimeArtifact(baseUrl, artifactId)
    const filename = String(artifact.filename || fallbackFilename || `${artifactId}.md`)
    const objectUrl = window.URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = filename
    anchor.rel = 'noopener'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 1000)
    setStatusFeedback({
      id: `artifact-download-${Date.now()}`,
      text: successText,
      tone: 'success',
      createdAt: Date.now(),
    })
  }, [baseUrl])

  const downloadResearchTaskArtifact = useCallback(async (task: RuntimeResearchTask) => {
    const artifactId = String(task.artifact?.artifact_id || task.artifact_id || '').trim()
    if (!artifactId) {
      throw new Error('研究任务还没有可下载报告')
    }
    setResearchBusy(true)
    try {
      await downloadArtifactFile(task.artifact || { artifact_id: artifactId, filename: `${artifactId}.md` }, `${artifactId}.md`, '已开始下载研究报告')
    } finally {
      setResearchBusy(false)
    }
  }, [downloadArtifactFile])

  const downloadProjectArtifact = useCallback(async (artifact: RuntimeArtifact) => {
    setProjectArtifactsBusy(true)
    try {
      await downloadArtifactFile(artifact, artifact.filename || `${artifact.artifact_id}.md`, '已开始下载产物')
    } finally {
      setProjectArtifactsBusy(false)
    }
  }, [downloadArtifactFile])

  return {
    messages: chatState.messages,
    operations,
    workspace: endpointContext?.workspace || null,
    threads: runtimeThreads,
    projects: runtimeProjects,
    branches: threadBranches,
    checkpoints: threadCheckpoints,
    projectSources,
    projectSourcesBusy,
    projectArtifacts,
    projectArtifactsBusy,
    researchTasks,
    researchBusy,
    activeProjectId,
    threadId: endpointContext?.threadId || '',
    defaultThreadId,
    sessionId,
    workspaceId: endpointContext?.workspace.workspace_id || '',
    desktopToolsAvailable: Boolean(desktopToolEndpointId),
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
    sendMessage,
    decideOperationApproval,
    sendConfirmResponse,
    sendHumanInputResponse,
    sendControlCommand,
    saveMessageAsProjectSource,
    editRetryMessage,
    createCheckpoint,
    restoreCheckpoint,
    checkoutCheckpoint,
    createResearchTask,
    approveResearchTask,
    startResearchTask,
    cancelResearchTask,
    saveResearchTaskPlan,
    downloadResearchTaskArtifact,
    downloadProjectArtifact,
    refreshResearchTasks,
    createThread: createAndSelectRuntimeThread,
    createProject: createRuntimeProjectAndRemember,
    updateProject: updateRuntimeProjectAndRemember,
    deleteThread: deleteRuntimeThreadAndSelect,
    refreshHealth,
    refreshWorkspace,
    refreshProjectSources,
    refreshProjectArtifacts,
    selectProject: selectRuntimeProject,
    selectThread: selectRuntimeThread,
    setStatusFeedback,
    baseUrl,
    endpointId,
  }
}
