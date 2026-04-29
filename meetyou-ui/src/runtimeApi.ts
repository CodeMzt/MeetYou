import { fetchWithAuth, readErrorMessage, resolveAccessToken } from './apiClient'
import { parseRuntimeUsageEnvelope } from './protocolClient'
import type {
  AssistantMode,
  RuntimeAttachmentRecord,
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
  RuntimeOperation,
  OperatorSourceProfile,
  RuntimeSession,
  RuntimeThread,
  RuntimeThreadDeleteResult,
  RuntimeUsageSnapshot,
  RuntimeWorkspace,
} from './types'

export interface RuntimeAttachmentDownloadTicket {
  attachment_id: string
  ticket_id: string
  download_url: string
  fallback_download_url: string
  download_strategy: string
  expires_at: string
  mime_type: string
  file_name: string
  size_bytes: number
}

export interface RuntimeAttachmentDownloadPlan {
  mode: 'direct' | 'proxy'
  url: string
  fileName: string
}

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

function isProxyAttachmentDownloadUrl(url: string): boolean {
  const value = String(url || '').trim()
  if (!value) {
    return false
  }
  try {
    const parsed = new URL(value, 'http://127.0.0.1')
    return parsed.pathname.includes('/desktop/attachments/content/')
  } catch {
    return value.includes('/desktop/attachments/content/')
  }
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
    offset?: number
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
    base_mode?: AssistantMode
    preferred_source_profiles?: string[]
    memory_ranking_policy?: string
  },
): Promise<RuntimeWorkspace> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/workspaces/${encodeURIComponent(workspaceId)}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeWorkspace>(response, '更新工作区治理失败')
}

export async function listOperatorSourceProfiles(baseUrl: string): Promise<OperatorSourceProfile[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/source-profiles'))
  return readJsonOrThrow<OperatorSourceProfile[]>(response, '加载来源档案目录失败')
}

export async function createRuntimeThread(
  baseUrl: string,
  payload: Pick<RuntimeThread, 'title'> & { home_workspace_id?: string; workspace_id?: string; mode?: string },
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
  payload: { workspace_id?: string; limit?: number; cursor?: string } = {},
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

export async function createRuntimeAttachmentUploadTicket(
  baseUrl: string,
  payload: {
    owner_type: string
    owner_id: string
    kind: string
    mime_type: string
    file_name?: string
    size_bytes?: number
    lifecycle_policy?: string
    endpoint_id?: string
  },
): Promise<{
  attachment_id: string
  ticket_id: string
  upload_url: string
  expires_at: string
  object_key: string
  status: string
}> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/attachments/upload-ticket'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow(response, '创建附件上传票据失败')
}

export async function uploadRuntimeAttachmentContent(
  uploadUrl: string,
  file: Blob,
): Promise<{
  attachment_id: string
  ticket_id: string
  status: string
  size_bytes: number
  sha256: string
}> {
  const response = await fetchWithAuth(uploadUrl, {
    method: 'PUT',
    body: file,
  })
  return readJsonOrThrow(response, '上传附件内容失败')
}

export async function completeRuntimeAttachment(
  baseUrl: string,
  attachmentId: string,
  payload: { ticket_id?: string; sha256?: string; size_bytes?: number },
): Promise<RuntimeAttachmentRecord> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/attachments/${encodeURIComponent(attachmentId)}/complete`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<RuntimeAttachmentRecord>(response, '完成附件上传失败')
}

export async function listRuntimeThreadAttachments(
  baseUrl: string,
  threadId: string,
): Promise<RuntimeAttachmentRecord[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}/attachments`))
  return readJsonOrThrow<RuntimeAttachmentRecord[]>(response, '加载附件列表失败')
}

export async function deleteRuntimeAttachment(
  baseUrl: string,
  attachmentId: string,
): Promise<RuntimeAttachmentRecord> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/attachments/${encodeURIComponent(attachmentId)}`), {
    method: 'DELETE',
  })
  return readJsonOrThrow<RuntimeAttachmentRecord>(response, '删除附件失败')
}

export async function createRuntimeAttachmentDownloadTicket(
  baseUrl: string,
  attachmentId: string,
  endpointId?: string,
): Promise<RuntimeAttachmentDownloadTicket> {
  const query = endpointId ? `?endpoint_id=${encodeURIComponent(endpointId)}` : ''
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/attachments/${encodeURIComponent(attachmentId)}/download-ticket${query}`))
  return readJsonOrThrow(response, '创建附件下载票据失败')
}

export function resolveRuntimeAttachmentDownloadPlan(ticket: RuntimeAttachmentDownloadTicket): RuntimeAttachmentDownloadPlan {
  const directUrl = String(ticket.download_url || '').trim()
  const fallbackUrl = String(ticket.fallback_download_url || '').trim()
  const strategy = String(ticket.download_strategy || '').trim().toLowerCase()
  const fileName = String(ticket.file_name || ticket.attachment_id || 'attachment.bin').trim() || 'attachment.bin'
  const hasProxyStyleDirectUrl = isProxyAttachmentDownloadUrl(directUrl)
  const shouldUseDirectUrl =
    Boolean(directUrl) &&
    (
      strategy === 'presigned' ||
      (!hasProxyStyleDirectUrl && (!fallbackUrl || directUrl !== fallbackUrl))
    )
  if (shouldUseDirectUrl) {
    return {
      mode: 'direct',
      url: directUrl,
      fileName,
    }
  }
  return {
    mode: 'proxy',
    url: fallbackUrl || directUrl,
    fileName,
  }
}

export async function downloadRuntimeAttachmentContent(downloadUrl: string): Promise<Blob> {
  const response = await fetchWithAuth(downloadUrl)
  if (!response.ok) {
    const failure = await readErrorMessage(response, '下载附件内容失败')
    throw new Error(failure.message)
  }
  return response.blob()
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
