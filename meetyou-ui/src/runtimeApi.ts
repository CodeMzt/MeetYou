import { fetchWithAuth, readErrorMessage, resolveAccessToken } from './apiClient'
import { parseRuntimeUsageEnvelope } from './protocolClient'
import type {
  AssistantMode,
  AvailableEndpoint,
  ContextPoolQueryResponse,
  DanxiActionResponse,
  DanxiListResponse,
  DanxiMessageTargetResponse,
  DanxiPostResponse,
  DanxiSearchResponse,
  DanxiSessionStatus,
  DanxiSummaryResponse,
  DanxiUserProfileResponse,
  RuntimeMessage,
  RuntimeMessageCreatePayload,
  RuntimeMessageEditRetryResult,
  RuntimeArtifact,
  RuntimeConversationCheckpoint,
  RuntimeOperation,
  RuntimeProject,
  RuntimeProjectSource,
  RuntimeResearchTask,
  OperatorSourceProfile,
  RuntimeSession,
  RuntimeThread,
  RuntimeThreadBranch,
  RuntimeThreadDeleteResult,
  RuntimeUsageSnapshot,
  RuntimeWorkspace,
  WorkspaceMembershipMutationResult,
  WorkspaceTopology,
} from './types'

export interface MemoryClearResult {
  ok: boolean
  cleared_record_count: number
  cleared_edge_count: number
  cleared_session_summary_count: number
  cleared_global_summary: boolean
  cleared_session_count: number
  active_session_count: number
  updated_at: string
}

export interface MemoryRecordMutationResult {
  ok: boolean
  memory_id: string
  status: string
  deleted: boolean
  updated_at: string
  record: Record<string, unknown> | null
}

function buildDesktopUrl(baseUrl: string, path: string): string {
  return `${baseUrl}/desktop${path}`
}

function toEndpointWsBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/^http/i, 'ws')
}

async function encryptDanxiCredentials(
  purpose: 'danxi.client.login.v1' | 'danxi.client.webvpn_cookie.v1',
  data: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const encryptor = window?.ipcRenderer?.invoke
  if (typeof encryptor !== 'function') {
    throw new Error('旦夕加密凭证传输仅在桌面端可用。')
  }
  return (await encryptor('encrypt-danxi-credentials', { purpose, data })) as Record<string, unknown>
}

async function readJsonOrThrow<T>(response: Response, fallback: string): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T
  }
  const failure = await readErrorMessage(response, fallback)
  throw new Error(failure.message)
}

export async function listRuntimeWorkspaces(baseUrl: string): Promise<RuntimeWorkspace[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/workspaces'))
  return readJsonOrThrow<RuntimeWorkspace[]>(response, '加载工作空间失败')
}

export async function listWorkspaceTopology(baseUrl: string, includeArchived = false): Promise<WorkspaceTopology> {
  const url = new URL(buildDesktopUrl(baseUrl, '/workspace-topology'))
  if (includeArchived) {
    url.searchParams.set('include_archived', 'true')
  }
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<WorkspaceTopology>(response, '加载工作区拓扑失败')
}

export async function loginDanxiSession(
  baseUrl: string,
  payload: {
    email: string
    password: string
    session_key?: string
    use_webvpn?: boolean
    webvpn_cookie?: string
  },
): Promise<DanxiSessionStatus> {
  const encryptedCredentials = await encryptDanxiCredentials('danxi.client.login.v1', payload)
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/danxi/session/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_key: payload.session_key || 'default',
      encrypted_credentials: encryptedCredentials,
    }),
  })
  return readJsonOrThrow<DanxiSessionStatus>(response, '旦夕登录失败')
}

export async function getDanxiSessionStatus(baseUrl: string, sessionKey = 'default'): Promise<DanxiSessionStatus> {
  const response = await fetchWithAuth(
    `${buildDesktopUrl(baseUrl, '/danxi/session')}?session_key=${encodeURIComponent(sessionKey)}`,
  )
  return readJsonOrThrow<DanxiSessionStatus>(response, '读取旦夕登录状态失败')
}

export async function updateDanxiWebvpnCookie(
  baseUrl: string,
  payload: {
    session_key?: string
    cookie_header: string
    enable_webvpn?: boolean
  },
): Promise<DanxiSessionStatus> {
  const encryptedCredentials = await encryptDanxiCredentials('danxi.client.webvpn_cookie.v1', payload)
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/danxi/session/webvpn-cookie'), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_key: payload.session_key || 'default',
      encrypted_credentials: encryptedCredentials,
    }),
  })
  return readJsonOrThrow<DanxiSessionStatus>(response, '更新旦夕 WebVPN 登录状态失败')
}

export async function getDanxiProfile(
  baseUrl: string,
  payload: {
    session_key?: string
    refresh?: boolean
  } = {},
): Promise<DanxiUserProfileResponse> {
  const url = new URL(buildDesktopUrl(baseUrl, '/danxi/profile'))
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<DanxiUserProfileResponse>(response, '读取旦夕用户信息失败')
}

export async function listDanxiDivisions(baseUrl: string, sessionKey = 'default'): Promise<DanxiListResponse> {
  const response = await fetchWithAuth(
    `${buildDesktopUrl(baseUrl, '/danxi/divisions')}?session_key=${encodeURIComponent(sessionKey)}`,
  )
  return readJsonOrThrow<DanxiListResponse>(response, '加载旦夕分区失败')
}

export async function listDanxiPosts(
  baseUrl: string,
  payload: {
    session_key?: string
    division_id?: number
    start_time?: string
    length?: number
    offset?: string | number
    tag?: string
    order?: string
  } = {},
): Promise<DanxiListResponse> {
  const url = new URL(buildDesktopUrl(baseUrl, '/danxi/posts'))
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<DanxiListResponse>(response, '加载旦夕帖子失败')
}

export async function getDanxiPost(
  baseUrl: string,
  holeId: number,
  sessionKey = 'default',
): Promise<DanxiPostResponse> {
  const response = await fetchWithAuth(
    `${buildDesktopUrl(baseUrl, `/danxi/posts/${holeId}`)}?session_key=${encodeURIComponent(sessionKey)}`,
  )
  return readJsonOrThrow<DanxiPostResponse>(response, '加载旦夕帖子详情失败')
}

export async function listDanxiFloors(
  baseUrl: string,
  holeId: number,
  payload: {
    session_key?: string
    offset?: number
    size?: number
    include_all?: boolean
  } = {},
): Promise<DanxiListResponse> {
  const url = new URL(buildDesktopUrl(baseUrl, `/danxi/posts/${holeId}/floors`))
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<DanxiListResponse>(response, '加载旦夕楼层失败')
}

export async function createDanxiReply(
  baseUrl: string,
  holeId: number,
  payload: {
    session_key?: string
    content: string
  },
): Promise<DanxiActionResponse> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/danxi/posts/${holeId}/replies`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<DanxiActionResponse>(response, '发布旦夕回复失败')
}

export async function updateDanxiReply(
  baseUrl: string,
  floorId: number,
  payload: {
    session_key?: string
    content: string
  },
): Promise<DanxiActionResponse> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/danxi/floors/${floorId}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<DanxiActionResponse>(response, '编辑旦夕回复失败')
}

export async function deleteDanxiReply(
  baseUrl: string,
  floorId: number,
  payload: {
    session_key?: string
    confirm?: boolean
  } = {},
): Promise<DanxiActionResponse> {
  const url = new URL(buildDesktopUrl(baseUrl, `/danxi/floors/${floorId}`))
  url.searchParams.set('confirm', String(payload.confirm ?? true))
  if (payload.session_key) {
    url.searchParams.set('session_key', payload.session_key)
  }
  const response = await fetchWithAuth(url.toString(), {
    method: 'DELETE',
  })
  return readJsonOrThrow<DanxiActionResponse>(response, '删除旦夕回复失败')
}

export async function getDanxiPostSummary(
  baseUrl: string,
  holeId: number,
  payload: {
    session_key?: string
    floor_limit?: number
  } = {},
): Promise<DanxiSummaryResponse> {
  const url = new URL(buildDesktopUrl(baseUrl, `/danxi/posts/${holeId}/summary`))
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<DanxiSummaryResponse>(response, '生成旦夕智能摘要失败')
}

export async function searchDanxiPosts(
  baseUrl: string,
  payload: {
    query: string
    session_key?: string
    accurate?: boolean
    length?: number
    start_floor?: number
    start_time?: string
    end_time?: string
  },
): Promise<DanxiSearchResponse> {
  const url = new URL(buildDesktopUrl(baseUrl, '/danxi/search'))
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<DanxiSearchResponse>(response, '搜索旦夕帖子失败')
}

export async function listDanxiMessages(
  baseUrl: string,
  payload: {
    session_key?: string
    unread_only?: boolean
    start_time?: string
  } = {},
): Promise<DanxiListResponse> {
  const url = new URL(buildDesktopUrl(baseUrl, '/danxi/messages'))
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<DanxiListResponse>(response, '加载旦夕消息失败')
}

export async function resolveDanxiMessageTarget(
  baseUrl: string,
  floorId: number,
  sessionKey = 'default',
): Promise<DanxiMessageTargetResponse> {
  const response = await fetchWithAuth(
    `${buildDesktopUrl(baseUrl, `/danxi/floors/${floorId}/target`)}?session_key=${encodeURIComponent(sessionKey)}`,
  )
  return readJsonOrThrow<DanxiMessageTargetResponse>(response, '解析旦夕消息跳转目标失败')
}

export async function updateOperatorWorkspaceGovernance(
  baseUrl: string,
  workspaceId: string,
  payload: {
    title?: string
    description?: string
    prompt_overlay?: string
    base_mode?: AssistantMode
    default_execution_target?: string
    tool_policy?: string
    allowed_tool_ids?: string[]
    preferred_target_endpoint_ids?: string[]
    preferred_endpoint_provider_types?: string[]
    preferred_source_profiles?: string[]
    tool_target_routing_policy?: string
    memory_ranking_policy?: string
    tool_routing_overrides?: Record<string, unknown>
  },
): Promise<RuntimeWorkspace> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/workspaces/${encodeURIComponent(workspaceId)}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeWorkspace>(response, '更新工作区治理失败')
}

export async function createOperatorWorkspace(
  baseUrl: string,
  payload: {
    workspace_id: string
    title?: string
    description?: string
    base_mode?: AssistantMode
    prompt_overlay?: string
    default_execution_target?: string
  },
): Promise<RuntimeWorkspace> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/workspaces'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeWorkspace>(response, '创建工作区失败')
}

export async function archiveOperatorWorkspace(baseUrl: string, workspaceId: string): Promise<RuntimeWorkspace> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/workspaces/${encodeURIComponent(workspaceId)}`), {
    method: 'DELETE',
  })
  return readJsonOrThrow<RuntimeWorkspace>(response, '归档工作区失败')
}

export async function restoreOperatorWorkspace(baseUrl: string, workspaceId: string): Promise<RuntimeWorkspace> {
  const response = await fetchWithAuth(
    buildDesktopUrl(baseUrl, `/workspaces/${encodeURIComponent(workspaceId)}/restore`),
    {
      method: 'POST',
    },
  )
  return readJsonOrThrow<RuntimeWorkspace>(response, '恢复工作区失败')
}

export async function addEndpointWorkspace(
  baseUrl: string,
  endpointId: string,
  payload: { workspace_id: string; make_primary?: boolean },
): Promise<WorkspaceMembershipMutationResult> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/endpoints/${encodeURIComponent(endpointId)}/workspaces`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<WorkspaceMembershipMutationResult>(response, '添加 Endpoint 工作区归属失败')
}

export async function removeEndpointWorkspace(
  baseUrl: string,
  endpointId: string,
  workspaceId: string,
): Promise<WorkspaceMembershipMutationResult> {
  const response = await fetchWithAuth(
    buildDesktopUrl(baseUrl, `/endpoints/${encodeURIComponent(endpointId)}/workspaces/${encodeURIComponent(workspaceId)}`),
    {
      method: 'DELETE',
    },
  )
  return readJsonOrThrow<WorkspaceMembershipMutationResult>(response, '移除 Endpoint 工作区归属失败')
}

export async function setEndpointPrimaryWorkspace(
  baseUrl: string,
  endpointId: string,
  workspaceId: string,
): Promise<WorkspaceMembershipMutationResult> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/endpoints/${encodeURIComponent(endpointId)}/primary-workspace`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace_id: workspaceId }),
  })
  return readJsonOrThrow<WorkspaceMembershipMutationResult>(response, '设置 Endpoint 主工作区失败')
}

export async function addAddressWorkspace(
  baseUrl: string,
  addressId: string,
  payload: { workspace_id: string; make_primary?: boolean },
): Promise<WorkspaceMembershipMutationResult> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/addresses/${encodeURIComponent(addressId)}/workspaces`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<WorkspaceMembershipMutationResult>(response, '添加地址工作区归属失败')
}

export async function removeAddressWorkspace(
  baseUrl: string,
  addressId: string,
  workspaceId: string,
): Promise<WorkspaceMembershipMutationResult> {
  const response = await fetchWithAuth(
    buildDesktopUrl(baseUrl, `/addresses/${encodeURIComponent(addressId)}/workspaces/${encodeURIComponent(workspaceId)}`),
    {
      method: 'DELETE',
    },
  )
  return readJsonOrThrow<WorkspaceMembershipMutationResult>(response, '移除地址工作区归属失败')
}

export async function setAddressPrimaryWorkspace(
  baseUrl: string,
  addressId: string,
  workspaceId: string,
): Promise<WorkspaceMembershipMutationResult> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/addresses/${encodeURIComponent(addressId)}/primary-workspace`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace_id: workspaceId }),
  })
  return readJsonOrThrow<WorkspaceMembershipMutationResult>(response, '设置地址主工作区失败')
}

export async function listOperatorSourceProfiles(baseUrl: string): Promise<OperatorSourceProfile[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/source-profiles'))
  return readJsonOrThrow<OperatorSourceProfile[]>(response, '加载来源档案目录失败')
}

export async function createRuntimeThread(
  baseUrl: string,
  payload: Pick<RuntimeThread, 'title'> & { home_workspace_id?: string; workspace_id?: string; project_id?: string; mode?: string },
): Promise<RuntimeThread> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/threads'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeThread>(response, '创建会话线程失败')
}

export async function ensureDefaultRuntimeThread(
  baseUrl: string,
  payload: { workspace_id?: string; default_key?: string; title?: string; mode?: string },
): Promise<RuntimeThread> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/threads/default'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeThread>(response, '加载默认会话线程失败')
}

export async function listRuntimeThreads(
  baseUrl: string,
  payload: { workspace_id?: string; project_id?: string; limit?: number; cursor?: string } = {},
): Promise<RuntimeThread[]> {
  const url = new URL(buildDesktopUrl(baseUrl, '/threads'))
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<RuntimeThread[]>(response, '加载会话线程列表失败')
}

export async function listRuntimeProjects(
  baseUrl: string,
  payload: { workspace_id?: string; include_archived?: boolean; limit?: number } = {},
): Promise<RuntimeProject[]> {
  const url = new URL(buildDesktopUrl(baseUrl, '/projects'))
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<RuntimeProject[]>(response, '加载项目列表失败')
}

export async function createRuntimeProject(
  baseUrl: string,
  payload: {
    workspace_id?: string
    title: string
    description?: string
    instructions?: string
    memory_scope?: Record<string, unknown>
    metadata?: Record<string, unknown>
  },
): Promise<RuntimeProject> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/projects'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeProject>(response, '创建项目失败')
}

export async function createRuntimeProjectSourceFromMessage(
  baseUrl: string,
  projectId: string,
  payload: {
    message_id: string
    title?: string
    metadata?: Record<string, unknown>
  },
): Promise<RuntimeProjectSource> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/projects/${encodeURIComponent(projectId)}/sources/from-message`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeProjectSource>(response, '保存项目源失败')
}

export async function listRuntimeProjectSources(
  baseUrl: string,
  projectId: string,
  params: { include_archived?: boolean; limit?: number } = {},
): Promise<RuntimeProjectSource[]> {
  const url = new URL(buildDesktopUrl(baseUrl, `/projects/${encodeURIComponent(projectId)}/sources`))
  if (params.include_archived) {
    url.searchParams.set('include_archived', 'true')
  }
  if (params.limit) {
    url.searchParams.set('limit', String(params.limit))
  }
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<RuntimeProjectSource[]>(response, '加载项目源失败')
}

export async function listRuntimeProjectArtifacts(
  baseUrl: string,
  projectId: string,
  params: { include_archived?: boolean; limit?: number } = {},
): Promise<RuntimeArtifact[]> {
  const url = new URL(buildDesktopUrl(baseUrl, `/projects/${encodeURIComponent(projectId)}/artifacts`))
  if (params.include_archived) {
    url.searchParams.set('include_archived', 'true')
  }
  if (params.limit) {
    url.searchParams.set('limit', String(params.limit))
  }
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<RuntimeArtifact[]>(response, '加载项目产物失败')
}

export async function deleteRuntimeThread(
  baseUrl: string,
  threadId: string,
  payload: { force?: boolean } = {},
): Promise<RuntimeThreadDeleteResult> {
  const url = new URL(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}`))
  if (payload.force) {
    url.searchParams.set('force', 'true')
  }
  const response = await fetchWithAuth(url.toString(), {
    method: 'DELETE',
  })
  return readJsonOrThrow<RuntimeThreadDeleteResult>(response, '删除会话线程失败')
}

export async function createRuntimeSession(
  baseUrl: string,
  payload: {
    thread_id: string
    active_workspace_id?: string
    workspace_id?: string
    endpoint_id: string
    endpoint_type?: string
    display_name?: string
  },
): Promise<RuntimeSession> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/sessions'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeSession>(response, '创建端点会话失败')
}

export async function updateRuntimeSessionActiveWorkspace(
  baseUrl: string,
  sessionId: string,
  payload: { active_workspace_id: string; endpoint_id?: string },
): Promise<RuntimeSession> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/sessions/${encodeURIComponent(sessionId)}/active-workspace`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeSession>(response, '切换工作区失败')
}

export async function sendRuntimeMessage(baseUrl: string, payload: RuntimeMessageCreatePayload): Promise<RuntimeMessage> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/messages'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeMessage>(response, '发送消息失败')
}

export async function editRetryRuntimeMessage(
  baseUrl: string,
  messageId: string,
  payload: {
    content: string
    title?: string
  },
): Promise<RuntimeMessageEditRetryResult> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/messages/${encodeURIComponent(messageId)}/edit-retry`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeMessageEditRetryResult>(response, '编辑并重试失败')
}

export async function listRuntimeThreadBranches(baseUrl: string, threadId: string): Promise<RuntimeThreadBranch[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}/branches`))
  return readJsonOrThrow<RuntimeThreadBranch[]>(response, '加载分支列表失败')
}

export async function listRuntimeThreadCheckpoints(baseUrl: string, threadId: string): Promise<RuntimeConversationCheckpoint[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}/checkpoints`))
  return readJsonOrThrow<RuntimeConversationCheckpoint[]>(response, '加载检查点列表失败')
}

export async function createRuntimeThreadCheckpoint(
  baseUrl: string,
  threadId: string,
  payload: {
    title?: string
    checkpoint_type?: string
    metadata?: Record<string, unknown>
  } = {},
): Promise<RuntimeConversationCheckpoint> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}/checkpoints`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeConversationCheckpoint>(response, '创建检查点失败')
}

export async function restoreRuntimeThreadCheckpoint(
  baseUrl: string,
  threadId: string,
  checkpointId: string,
): Promise<RuntimeConversationCheckpoint> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}/checkpoints/${encodeURIComponent(checkpointId)}/restore`), {
    method: 'POST',
  })
  return readJsonOrThrow<RuntimeConversationCheckpoint>(response, '恢复检查点失败')
}

export async function checkoutRuntimeThreadCheckpoint(
  baseUrl: string,
  threadId: string,
  checkpointId: string,
  payload: { title?: string } = {},
): Promise<RuntimeThreadBranch> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}/checkpoints/${encodeURIComponent(checkpointId)}/checkout`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeThreadBranch>(response, '签出检查点失败')
}

export async function listRuntimeResearchTasks(
  baseUrl: string,
  params: { project_id?: string; limit?: number } = {},
): Promise<RuntimeResearchTask[]> {
  const url = new URL(buildDesktopUrl(baseUrl, '/research-tasks'))
  if (params.project_id) {
    url.searchParams.set('project_id', params.project_id)
  }
  if (params.limit) {
    url.searchParams.set('limit', String(params.limit))
  }
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<RuntimeResearchTask[]>(response, '加载研究任务失败')
}

export async function createRuntimeResearchTask(
  baseUrl: string,
  payload: {
    topic: string
    project_id?: string
    thread_id?: string
    source_policy?: Record<string, unknown>
    output_format?: string
    metadata?: Record<string, unknown>
  },
): Promise<RuntimeResearchTask> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/research-tasks'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeResearchTask>(response, '创建研究任务失败')
}

export async function patchRuntimeResearchTask(
  baseUrl: string,
  researchTaskId: string,
  payload: {
    action?: string
    status?: string
    plan?: Record<string, unknown>
    source_policy?: Record<string, unknown>
    evidence_ledger?: Array<Record<string, unknown>>
    summary?: string
    report_markdown?: string
    report_filename?: string
    metadata?: Record<string, unknown>
  },
): Promise<RuntimeResearchTask> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/research-tasks/${encodeURIComponent(researchTaskId)}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeResearchTask>(response, '更新研究任务失败')
}

export async function downloadRuntimeArtifact(
  baseUrl: string,
  artifactId: string,
): Promise<Blob> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/artifacts/${encodeURIComponent(artifactId)}/download`))
  if (response.ok) {
    return await response.blob()
  }
  const failure = await readErrorMessage(response, '下载 Artifact 失败')
  throw new Error(failure.message)
}

export async function listThreadMessages(baseUrl: string, threadId: string): Promise<RuntimeMessage[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}/messages`))
  return readJsonOrThrow<RuntimeMessage[]>(response, '加载消息历史失败')
}

export async function createRuntimeOperation(
  baseUrl: string,
  payload: {
    thread_id: string
    workspace_id: string
    endpoint_id?: string
    session_id?: string
    title: string
    operation_type: string
    execution_target?: string
    target_endpoint_id?: string
    tool_key?: string
    tool_id?: string
    arguments?: Record<string, unknown>
  },
): Promise<RuntimeOperation> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/operations'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeOperation>(response, '创建操作失败')
}

export async function listAvailableEndpoints(baseUrl: string, workspaceId: string): Promise<AvailableEndpoint[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/workspaces/${encodeURIComponent(workspaceId)}/endpoints?include_tools=true`))
  return readJsonOrThrow<AvailableEndpoint[]>(response, '加载可用端点失败')
}

export async function queryContextPool(
  baseUrl: string,
  payload: { q: string; thread_id?: string; session_id?: string; active_workspace_id?: string; limit?: number },
): Promise<ContextPoolQueryResponse> {
  const url = new URL(buildDesktopUrl(baseUrl, '/context-pool/query'))
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<ContextPoolQueryResponse>(response, '查询上下文池失败')
}

export async function decideRuntimeApproval(
  baseUrl: string,
  approvalId: string,
  payload: { decision: 'approve' | 'reject'; reason?: string; endpoint_id?: string },
): Promise<{
  approval_id: string
  operation_id: string
  approval_type: string
  risk_level: string
  status: string
  decision: string
  reason: string
  operation_status: string
}> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/approvals/${encodeURIComponent(approvalId)}/decision`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow(response, '提交审批结果失败')
}

export async function submitRuntimeConfirmResponse(
  baseUrl: string,
  sessionId: string,
  payload: {
    accepted: boolean
    request_id: string
    reason?: string
    endpoint_id?: string
  },
): Promise<{
  request_id: string
  session_id: string
  accepted: boolean
  approval_id: string
  approval_status: string
  operation_id: string
}> {
  const response = await fetchWithAuth(
    buildDesktopUrl(baseUrl, `/sessions/${encodeURIComponent(sessionId)}/confirm-response`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return readJsonOrThrow(response, '提交确认结果失败')
}

export async function submitRuntimeHumanInputResponse(
  baseUrl: string,
  sessionId: string,
  payload: {
    request_id: string
    answer_text: string
    selected_option?: string
    endpoint_id?: string
  },
): Promise<{
  request_id: string
  session_id: string
  answer_text: string
  selected_option?: string
}> {
  const response = await fetchWithAuth(
    buildDesktopUrl(baseUrl, `/sessions/${encodeURIComponent(sessionId)}/human-input-response`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return readJsonOrThrow(response, '提交补充输入结果失败')
}

export async function submitRuntimeReplyControl(
  baseUrl: string,
  sessionId: string,
  payload: {
    action: 'stop' | 'append_guidance' | 'regenerate' | 'rollback'
    guidance?: string
    checkpoint_id?: string
    turn_id?: string
    stream_id?: string
    endpoint_id?: string
    endpoint_type?: string
    endpoint_request_id?: string
    metadata?: Record<string, unknown>
  },
): Promise<{
  request_id: string
  session_id: string
  action: string
  accepted: boolean
  status: string
}> {
  const response = await fetchWithAuth(
    buildDesktopUrl(baseUrl, `/sessions/${encodeURIComponent(sessionId)}/reply-control`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return readJsonOrThrow(response, '提交控制命令失败')
}

export async function fetchRuntimeUsageSnapshot(
  baseUrl: string,
  sessionId: string,
): Promise<RuntimeUsageSnapshot> {
  const response = await fetchWithAuth(
    `${buildDesktopUrl(baseUrl, '/runtime/usage')}?session_id=${encodeURIComponent(sessionId)}`,
  )
  const payload = await readJsonOrThrow<unknown>(response, '加载令牌与上下文快照失败')
  const snapshot = parseRuntimeUsageEnvelope(payload)
  if (!snapshot) {
    throw new Error('解析令牌与上下文快照失败')
  }
  return snapshot
}

export async function clearDesktopMemory(baseUrl: string): Promise<MemoryClearResult> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/memory'), {
    method: 'DELETE',
  })
  return readJsonOrThrow<MemoryClearResult>(response, '清理记忆失败')
}

export async function updateDesktopMemoryRecordStatus(
  baseUrl: string,
  memoryId: string,
  status: 'active' | 'invalidated',
): Promise<MemoryRecordMutationResult> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/memory/records/${encodeURIComponent(memoryId)}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  })
  return readJsonOrThrow<MemoryRecordMutationResult>(response, '更新记忆记录失败')
}

export async function deleteDesktopMemoryRecord(
  baseUrl: string,
  memoryId: string,
): Promise<MemoryRecordMutationResult> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/memory/records/${encodeURIComponent(memoryId)}`), {
    method: 'DELETE',
  })
  return readJsonOrThrow<MemoryRecordMutationResult>(response, '删除记忆记录失败')
}

export async function createEndpointWsUrl(
  baseUrl: string,
  threadId: string,
  identity: {
    endpointId?: string
    sessionId?: string
    workspaceId?: string
    endpointType?: string
    displayName?: string
  } = {},
): Promise<string> {
  const url = new URL(`${toEndpointWsBaseUrl(baseUrl)}/desktop/ws`)
  url.searchParams.set('thread_id', threadId)
  if (identity.endpointId) {
    url.searchParams.set('endpoint_id', identity.endpointId)
  }
  if (identity.sessionId) {
    url.searchParams.set('session_id', identity.sessionId)
  }
  if (identity.workspaceId) {
    url.searchParams.set('workspace_id', identity.workspaceId)
  }
  if (identity.endpointType) {
    url.searchParams.set('endpoint_type', identity.endpointType)
  }
  if (identity.displayName) {
    url.searchParams.set('display_name', identity.displayName)
  }
  const token = await resolveAccessToken()
  if (token) {
    url.searchParams.set('access_token', token)
  }
  return url.toString()
}
