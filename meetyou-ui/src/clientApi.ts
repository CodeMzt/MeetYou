import { fetchWithAuth, readErrorMessage, resolveAccessToken } from './apiClient'
import { parseRuntimeUsageEnvelope } from './protocolClient'
import type {
  AssistantMode,
  ClientAttachmentRecord,
  ClientAvailableAgent,
  DanxiActionResponse,
  DanxiListResponse,
  DanxiPostResponse,
  DanxiSearchResponse,
  DanxiSessionStatus,
  DanxiSummaryResponse,
  DanxiUserProfileResponse,
  ClientMessage,
  ClientMessageCreatePayload,
  ClientOperation,
  OperatorSourceProfile,
  ClientProcedureDetail,
  ClientThreadProcedureContext,
  ClientSession,
  ClientThread,
  RuntimeUsageSnapshot,
  ClientWorkspace,
  ClientProcedure,
} from './types'

export interface ClientAttachmentDownloadTicket {
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

export interface ClientAttachmentDownloadPlan {
  mode: 'direct' | 'proxy'
  url: string
  fileName: string
}

function isProxyAttachmentDownloadUrl(url: string): boolean {
  const value = String(url || '').trim()
  if (!value) {
    return false
  }
  try {
    const parsed = new URL(value, 'http://127.0.0.1')
    return parsed.pathname.includes('/client/attachments/content/')
  } catch {
    return value.includes('/client/attachments/content/')
  }
}

function toClientWsBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/^http/i, 'ws')
}

async function encryptDanxiCredentials(
  purpose: 'danxi.client.login.v1' | 'danxi.client.webvpn_cookie.v1',
  data: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const encryptor = window?.ipcRenderer?.invoke
  if (typeof encryptor !== 'function') {
    throw new Error('当前环境不支持加密发送 Danxi 凭证，请在 Electron 桌面端中使用。')
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

export async function listClientWorkspaces(baseUrl: string): Promise<ClientWorkspace[]> {
  const response = await fetchWithAuth(`${baseUrl}/client/workspaces`)
  return readJsonOrThrow<ClientWorkspace[]>(response, '加载工作空间失败')
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
  const response = await fetchWithAuth(`${baseUrl}/client/danxi/session/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_key: payload.session_key || 'default',
      encrypted_credentials: encryptedCredentials,
    }),
  })
  return readJsonOrThrow<DanxiSessionStatus>(response, 'Danxi 登录失败')
}

export async function getDanxiSessionStatus(baseUrl: string, sessionKey = 'default'): Promise<DanxiSessionStatus> {
  const response = await fetchWithAuth(
    `${baseUrl}/client/danxi/session?session_key=${encodeURIComponent(sessionKey)}`,
  )
  return readJsonOrThrow<DanxiSessionStatus>(response, '读取 Danxi 会话状态失败')
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
  const response = await fetchWithAuth(`${baseUrl}/client/danxi/session/webvpn-cookie`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_key: payload.session_key || 'default',
      encrypted_credentials: encryptedCredentials,
    }),
  })
  return readJsonOrThrow<DanxiSessionStatus>(response, '更新 Danxi WebVPN 登录态失败')
}

export async function getDanxiProfile(
  baseUrl: string,
  payload: {
    session_key?: string
    refresh?: boolean
  } = {},
): Promise<DanxiUserProfileResponse> {
  const url = new URL(`${baseUrl}/client/danxi/profile`)
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<DanxiUserProfileResponse>(response, '读取 Danxi 用户信息失败')
}

export async function listDanxiDivisions(baseUrl: string, sessionKey = 'default'): Promise<DanxiListResponse> {
  const response = await fetchWithAuth(
    `${baseUrl}/client/danxi/divisions?session_key=${encodeURIComponent(sessionKey)}`,
  )
  return readJsonOrThrow<DanxiListResponse>(response, '加载 Danxi 分区失败')
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
  const url = new URL(`${baseUrl}/client/danxi/posts`)
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<DanxiListResponse>(response, '加载 Danxi 帖子失败')
}

export async function getDanxiPost(
  baseUrl: string,
  holeId: number,
  sessionKey = 'default',
): Promise<DanxiPostResponse> {
  const response = await fetchWithAuth(
    `${baseUrl}/client/danxi/posts/${holeId}?session_key=${encodeURIComponent(sessionKey)}`,
  )
  return readJsonOrThrow<DanxiPostResponse>(response, '加载 Danxi 帖子详情失败')
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
  const url = new URL(`${baseUrl}/client/danxi/posts/${holeId}/floors`)
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<DanxiListResponse>(response, '加载 Danxi 楼层失败')
}

export async function createDanxiReply(
  baseUrl: string,
  holeId: number,
  payload: {
    session_key?: string
    content: string
  },
): Promise<DanxiActionResponse> {
  const response = await fetchWithAuth(`${baseUrl}/client/danxi/posts/${holeId}/replies`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<DanxiActionResponse>(response, '发布 Danxi 回复失败')
}

export async function updateDanxiReply(
  baseUrl: string,
  floorId: number,
  payload: {
    session_key?: string
    content: string
  },
): Promise<DanxiActionResponse> {
  const response = await fetchWithAuth(`${baseUrl}/client/danxi/floors/${floorId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<DanxiActionResponse>(response, '编辑 Danxi 回复失败')
}

export async function deleteDanxiReply(
  baseUrl: string,
  floorId: number,
  payload: {
    session_key?: string
    confirm?: boolean
  } = {},
): Promise<DanxiActionResponse> {
  const url = new URL(`${baseUrl}/client/danxi/floors/${floorId}`)
  url.searchParams.set('confirm', String(payload.confirm ?? true))
  if (payload.session_key) {
    url.searchParams.set('session_key', payload.session_key)
  }
  const response = await fetchWithAuth(url.toString(), {
    method: 'DELETE',
  })
  return readJsonOrThrow<DanxiActionResponse>(response, '删除 Danxi 回复失败')
}

export async function getDanxiPostSummary(
  baseUrl: string,
  holeId: number,
  payload: {
    session_key?: string
    floor_limit?: number
  } = {},
): Promise<DanxiSummaryResponse> {
  const url = new URL(`${baseUrl}/client/danxi/posts/${holeId}/summary`)
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<DanxiSummaryResponse>(response, '生成 Danxi AI 摘要失败')
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
  const url = new URL(`${baseUrl}/client/danxi/search`)
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<DanxiSearchResponse>(response, '搜索 Danxi 帖子失败')
}

export async function listDanxiMessages(
  baseUrl: string,
  payload: {
    session_key?: string
    unread_only?: boolean
    start_time?: string
  } = {},
): Promise<DanxiListResponse> {
  const url = new URL(`${baseUrl}/client/danxi/messages`)
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })
  const response = await fetchWithAuth(url.toString())
  return readJsonOrThrow<DanxiListResponse>(response, '加载 Danxi 消息失败')
}

export async function updateOperatorWorkspaceGovernance(
  baseUrl: string,
  workspaceId: string,
  payload: {
    base_mode?: AssistantMode
    preferred_source_profiles?: string[]
    memory_ranking_policy?: string
  },
): Promise<ClientWorkspace> {
  const response = await fetchWithAuth(`${baseUrl}/operator/workspaces/${encodeURIComponent(workspaceId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientWorkspace>(response, '更新工作区治理失败')
}

export async function listOperatorSourceProfiles(baseUrl: string): Promise<OperatorSourceProfile[]> {
  const response = await fetchWithAuth(`${baseUrl}/operator/source-profiles`)
  return readJsonOrThrow<OperatorSourceProfile[]>(response, '加载 source profile 目录失败')
}

export async function createClientThread(
  baseUrl: string,
  payload: Pick<ClientThread, 'workspace_id' | 'title'> & { mode?: string; pinned_procedure_id?: string | null },
): Promise<ClientThread> {
  const response = await fetchWithAuth(`${baseUrl}/client/threads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientThread>(response, '创建会话线程失败')
}

export async function createClientSession(
  baseUrl: string,
  payload: {
    thread_id: string
    workspace_id: string
    client_id: string
    client_type?: string
    display_name?: string
  },
): Promise<ClientSession> {
  const response = await fetchWithAuth(`${baseUrl}/client/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientSession>(response, '创建客户端会话失败')
}

export async function sendClientMessage(baseUrl: string, payload: ClientMessageCreatePayload): Promise<ClientMessage> {
  const response = await fetchWithAuth(`${baseUrl}/client/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientMessage>(response, '发送消息失败')
}

export async function listThreadMessages(baseUrl: string, threadId: string): Promise<ClientMessage[]> {
  const response = await fetchWithAuth(`${baseUrl}/client/threads/${encodeURIComponent(threadId)}/messages`)
  return readJsonOrThrow<ClientMessage[]>(response, '加载消息历史失败')
}

export async function createClientOperation(
  baseUrl: string,
  payload: {
    thread_id: string
    workspace_id: string
    client_id?: string
    session_id?: string
    title: string
    operation_type: string
    execution_target?: string
    target_agent_id?: string
    capability_id?: string
    arguments?: Record<string, unknown>
  },
): Promise<ClientOperation> {
  const response = await fetchWithAuth(`${baseUrl}/client/operations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientOperation>(response, '创建操作失败')
}

export async function listClientAvailableAgents(baseUrl: string, workspaceId: string): Promise<ClientAvailableAgent[]> {
  const response = await fetchWithAuth(`${baseUrl}/client/workspaces/${encodeURIComponent(workspaceId)}/agents`)
  return readJsonOrThrow<ClientAvailableAgent[]>(response, '加载可用 Agent 失败')
}

export async function listClientProcedures(baseUrl: string): Promise<ClientProcedure[]> {
  const response = await fetchWithAuth(`${baseUrl}/client/procedures`)
  return readJsonOrThrow<ClientProcedure[]>(response, '加载 Procedure 列表失败')
}

export async function getClientProcedureDetail(baseUrl: string, procedureId: string): Promise<ClientProcedureDetail> {
  const response = await fetchWithAuth(`${baseUrl}/client/procedures/${encodeURIComponent(procedureId)}`)
  return readJsonOrThrow<ClientProcedureDetail>(response, '加载 Procedure 详情失败')
}

export async function getClientThreadProcedureContext(
  baseUrl: string,
  threadId: string,
): Promise<ClientThreadProcedureContext> {
  const response = await fetchWithAuth(`${baseUrl}/client/threads/${encodeURIComponent(threadId)}/procedure-context`)
  return readJsonOrThrow<ClientThreadProcedureContext>(response, '加载线程 Procedure 上下文失败')
}

export async function pinClientThreadProcedure(
  baseUrl: string,
  threadId: string,
  procedureId: string,
): Promise<ClientThreadProcedureContext> {
  const response = await fetchWithAuth(`${baseUrl}/client/threads/${encodeURIComponent(threadId)}/pinned-procedure`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ procedure_id: procedureId }),
  })
  return readJsonOrThrow<ClientThreadProcedureContext>(response, '固定线程规程失败')
}

export async function unpinClientThreadProcedure(
  baseUrl: string,
  threadId: string,
): Promise<ClientThreadProcedureContext> {
  const response = await fetchWithAuth(`${baseUrl}/client/threads/${encodeURIComponent(threadId)}/pinned-procedure`, {
    method: 'DELETE',
  })
  return readJsonOrThrow<ClientThreadProcedureContext>(response, '取消固定线程规程失败')
}

export async function decideClientApproval(
  baseUrl: string,
  approvalId: string,
  payload: { decision: 'approve' | 'reject'; reason?: string; client_id?: string },
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
  const response = await fetchWithAuth(`${baseUrl}/client/approvals/${encodeURIComponent(approvalId)}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow(response, '提交审批结果失败')
}

export async function submitClientConfirmResponse(
  baseUrl: string,
  sessionId: string,
  payload: {
    accepted: boolean
    request_id: string
    reason?: string
    client_id?: string
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
    `${baseUrl}/client/sessions/${encodeURIComponent(sessionId)}/confirm-response`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return readJsonOrThrow(response, '提交确认结果失败')
}

export async function submitClientHumanInputResponse(
  baseUrl: string,
  sessionId: string,
  payload: {
    request_id: string
    answer_text: string
    selected_option?: string
    client_id?: string
  },
): Promise<{
  request_id: string
  session_id: string
  answer_text: string
  selected_option?: string
}> {
  const response = await fetchWithAuth(
    `${baseUrl}/client/sessions/${encodeURIComponent(sessionId)}/human-input-response`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return readJsonOrThrow(response, '提交补充输入结果失败')
}

export async function createClientAttachmentUploadTicket(
  baseUrl: string,
  payload: {
    owner_type: string
    owner_id: string
    kind: string
    mime_type: string
    file_name?: string
    size_bytes?: number
    lifecycle_policy?: string
    client_id?: string
  },
): Promise<{
  attachment_id: string
  ticket_id: string
  upload_url: string
  expires_at: string
  object_key: string
  status: string
}> {
  const response = await fetchWithAuth(`${baseUrl}/client/attachments/upload-ticket`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow(response, '创建附件上传票据失败')
}

export async function uploadClientAttachmentContent(
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

export async function completeClientAttachment(
  baseUrl: string,
  attachmentId: string,
  payload: { ticket_id?: string; sha256?: string; size_bytes?: number },
): Promise<ClientAttachmentRecord> {
  const response = await fetchWithAuth(`${baseUrl}/client/attachments/${encodeURIComponent(attachmentId)}/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientAttachmentRecord>(response, '完成附件上传失败')
}

export async function listClientThreadAttachments(
  baseUrl: string,
  threadId: string,
): Promise<ClientAttachmentRecord[]> {
  const response = await fetchWithAuth(`${baseUrl}/client/threads/${encodeURIComponent(threadId)}/attachments`)
  return readJsonOrThrow<ClientAttachmentRecord[]>(response, '加载附件列表失败')
}

export async function deleteClientAttachment(
  baseUrl: string,
  attachmentId: string,
): Promise<ClientAttachmentRecord> {
  const response = await fetchWithAuth(`${baseUrl}/client/attachments/${encodeURIComponent(attachmentId)}`, {
    method: 'DELETE',
  })
  return readJsonOrThrow<ClientAttachmentRecord>(response, '删除附件失败')
}

export async function createClientAttachmentDownloadTicket(
  baseUrl: string,
  attachmentId: string,
  clientId?: string,
): Promise<ClientAttachmentDownloadTicket> {
  const query = clientId ? `?client_id=${encodeURIComponent(clientId)}` : ''
  const response = await fetchWithAuth(`${baseUrl}/client/attachments/${encodeURIComponent(attachmentId)}/download-ticket${query}`)
  return readJsonOrThrow(response, '创建附件下载票据失败')
}

export function resolveClientAttachmentDownloadPlan(ticket: ClientAttachmentDownloadTicket): ClientAttachmentDownloadPlan {
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

export async function downloadClientAttachmentContent(downloadUrl: string): Promise<Blob> {
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
    `${baseUrl}/runtime/usage?session_id=${encodeURIComponent(sessionId)}`,
  )
  const payload = await readJsonOrThrow<unknown>(response, '加载 token / context 快照失败')
  const snapshot = parseRuntimeUsageEnvelope(payload)
  if (!snapshot) {
    throw new Error('解析 token / context 快照失败')
  }
  return snapshot
}

export async function createClientWsUrl(baseUrl: string, threadId: string): Promise<string> {
  const url = new URL(`${toClientWsBaseUrl(baseUrl)}/client/ws`)
  url.searchParams.set('thread_id', threadId)
  const token = await resolveAccessToken()
  if (token) {
    url.searchParams.set('access_token', token)
  }
  return url.toString()
}
