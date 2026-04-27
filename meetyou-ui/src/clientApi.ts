import { fetchWithAuth, readErrorMessage, resolveAccessToken } from './apiClient'
import { parseRuntimeUsageEnvelope } from './protocolClient'
import type {
  AssistantMode,
  ClientAttachmentRecord,
  ClientAvailableClient,
  ContextPoolQueryResponse,
  DanxiActionResponse,
  DanxiListResponse,
  DanxiMessageTargetResponse,
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

function toClientWsBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/^http/i, 'ws')
}

async function encryptDanxiCredentials(
  purpose: 'danxi.client.login.v1' | 'danxi.client.webvpn_cookie.v1',
  data: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const encryptor = window?.ipcRenderer?.invoke
  if (typeof encryptor !== 'function') {
    throw new Error('Encrypted Danxi credential transport is only available in the Electron desktop app.')
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
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/workspaces'))
  return readJsonOrThrow<ClientWorkspace[]>(response, '鍔犺浇宸ヤ綔绌洪棿澶辫触')
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
  return readJsonOrThrow<DanxiSessionStatus>(response, 'Danxi 鐧诲綍澶辫触')
}

export async function getDanxiSessionStatus(baseUrl: string, sessionKey = 'default'): Promise<DanxiSessionStatus> {
  const response = await fetchWithAuth(
    `${buildDesktopUrl(baseUrl, '/danxi/session')}?session_key=${encodeURIComponent(sessionKey)}`,
  )
  return readJsonOrThrow<DanxiSessionStatus>(response, 'Failed to load Danxi session status')
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
  return readJsonOrThrow<DanxiSessionStatus>(response, 'Failed to update Danxi WebVPN login state')
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
  return readJsonOrThrow<DanxiUserProfileResponse>(response, '璇诲彇 Danxi 鐢ㄦ埛淇℃伅澶辫触')
}

export async function listDanxiDivisions(baseUrl: string, sessionKey = 'default'): Promise<DanxiListResponse> {
  const response = await fetchWithAuth(
    `${buildDesktopUrl(baseUrl, '/danxi/divisions')}?session_key=${encodeURIComponent(sessionKey)}`,
  )
  return readJsonOrThrow<DanxiListResponse>(response, '鍔犺浇 Danxi 鍒嗗尯澶辫触')
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
  return readJsonOrThrow<DanxiListResponse>(response, '鍔犺浇 Danxi 甯栧瓙澶辫触')
}

export async function getDanxiPost(
  baseUrl: string,
  holeId: number,
  sessionKey = 'default',
): Promise<DanxiPostResponse> {
  const response = await fetchWithAuth(
    `${buildDesktopUrl(baseUrl, `/danxi/posts/${holeId}`)}?session_key=${encodeURIComponent(sessionKey)}`,
  )
  return readJsonOrThrow<DanxiPostResponse>(response, '鍔犺浇 Danxi 甯栧瓙璇︽儏澶辫触')
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
  return readJsonOrThrow<DanxiListResponse>(response, '鍔犺浇 Danxi 妤煎眰澶辫触')
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
  return readJsonOrThrow<DanxiActionResponse>(response, '鍙戝竷 Danxi 鍥炲澶辫触')
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
  return readJsonOrThrow<DanxiActionResponse>(response, '缂栬緫 Danxi 鍥炲澶辫触')
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
  return readJsonOrThrow<DanxiActionResponse>(response, '鍒犻櫎 Danxi 鍥炲澶辫触')
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
  return readJsonOrThrow<DanxiSummaryResponse>(response, '鐢熸垚 Danxi AI 鎽樿澶辫触')
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
  return readJsonOrThrow<DanxiSearchResponse>(response, '鎼滅储 Danxi 甯栧瓙澶辫触')
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
  return readJsonOrThrow<DanxiListResponse>(response, '鍔犺浇 Danxi 娑堟伅澶辫触')
}

export async function resolveDanxiMessageTarget(
  baseUrl: string,
  floorId: number,
  sessionKey = 'default',
): Promise<DanxiMessageTargetResponse> {
  const response = await fetchWithAuth(
    `${buildDesktopUrl(baseUrl, `/danxi/floors/${floorId}/target`)}?session_key=${encodeURIComponent(sessionKey)}`,
  )
  return readJsonOrThrow<DanxiMessageTargetResponse>(response, '瑙ｆ瀽 Danxi 娑堟伅璺宠浆鐩爣澶辫触')
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
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/workspaces/${encodeURIComponent(workspaceId)}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientWorkspace>(response, 'Failed to update workspace governance')
}

export async function listOperatorSourceProfiles(baseUrl: string): Promise<OperatorSourceProfile[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/source-profiles'))
  return readJsonOrThrow<OperatorSourceProfile[]>(response, '鍔犺浇 source profile 鐩綍澶辫触')
}

export async function createClientThread(
  baseUrl: string,
  payload: Pick<ClientThread, 'title'> & { home_workspace_id?: string; workspace_id?: string; mode?: string; pinned_procedure_id?: string | null },
): Promise<ClientThread> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/threads'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientThread>(response, '鍒涘缓浼氳瘽绾跨▼澶辫触')
}

export async function createClientSession(
  baseUrl: string,
  payload: {
    thread_id: string
    active_workspace_id?: string
    workspace_id?: string
    client_id: string
    client_type?: string
    display_name?: string
  },
): Promise<ClientSession> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/sessions'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientSession>(response, 'Failed to create endpoint session')
}

export async function updateClientSessionActiveWorkspace(
  baseUrl: string,
  sessionId: string,
  payload: { active_workspace_id: string; client_id?: string },
): Promise<ClientSession> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/sessions/${encodeURIComponent(sessionId)}/active-workspace`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientSession>(response, 'Failed to switch workspace')
}

export async function sendClientMessage(baseUrl: string, payload: ClientMessageCreatePayload): Promise<ClientMessage> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/messages'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientMessage>(response, 'Failed to send message')
}

export async function listThreadMessages(baseUrl: string, threadId: string): Promise<ClientMessage[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}/messages`))
  return readJsonOrThrow<ClientMessage[]>(response, '鍔犺浇娑堟伅鍘嗗彶澶辫触')
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
    target_endpoint_id?: string
    tool_key?: string
    tool_id?: string
    arguments?: Record<string, unknown>
  },
): Promise<ClientOperation> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/operations'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientOperation>(response, '鍒涘缓鎿嶄綔澶辫触')
}

export async function listClientAvailableClients(baseUrl: string, workspaceId: string): Promise<ClientAvailableClient[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/workspaces/${encodeURIComponent(workspaceId)}/clients?include_tools=true`))
  return readJsonOrThrow<ClientAvailableClient[]>(response, '鍔犺浇鍙敤 Client 澶辫触')
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
  return readJsonOrThrow<ContextPoolQueryResponse>(response, '鏌ヨ涓婁笅鏂囨睜澶辫触')
}

export async function listClientProcedures(baseUrl: string): Promise<ClientProcedure[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/procedures'))
  return readJsonOrThrow<ClientProcedure[]>(response, '鍔犺浇 Procedure 鍒楄〃澶辫触')
}

export async function getClientProcedureDetail(baseUrl: string, procedureId: string): Promise<ClientProcedureDetail> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/procedures/${encodeURIComponent(procedureId)}`))
  return readJsonOrThrow<ClientProcedureDetail>(response, '鍔犺浇 Procedure 璇︽儏澶辫触')
}

export async function getClientThreadProcedureContext(
  baseUrl: string,
  threadId: string,
): Promise<ClientThreadProcedureContext> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}/procedure-context`))
  return readJsonOrThrow<ClientThreadProcedureContext>(response, 'Failed to load thread procedure context')
}

export async function pinClientThreadProcedure(
  baseUrl: string,
  threadId: string,
  procedureId: string,
): Promise<ClientThreadProcedureContext> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}/pinned-procedure`), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ procedure_id: procedureId }),
  })
  return readJsonOrThrow<ClientThreadProcedureContext>(response, '鍥哄畾绾跨▼瑙勭▼澶辫触')
}

export async function unpinClientThreadProcedure(
  baseUrl: string,
  threadId: string,
): Promise<ClientThreadProcedureContext> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}/pinned-procedure`), {
    method: 'DELETE',
  })
  return readJsonOrThrow<ClientThreadProcedureContext>(response, '鍙栨秷鍥哄畾绾跨▼瑙勭▼澶辫触')
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
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/approvals/${encodeURIComponent(approvalId)}/decision`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow(response, '鎻愪氦瀹℃壒缁撴灉澶辫触')
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
    buildDesktopUrl(baseUrl, `/sessions/${encodeURIComponent(sessionId)}/confirm-response`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return readJsonOrThrow(response, '鎻愪氦纭缁撴灉澶辫触')
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
    buildDesktopUrl(baseUrl, `/sessions/${encodeURIComponent(sessionId)}/human-input-response`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return readJsonOrThrow(response, '鎻愪氦琛ュ厖杈撳叆缁撴灉澶辫触')
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
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/attachments/upload-ticket'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow(response, '鍒涘缓闄勪欢涓婁紶绁ㄦ嵁澶辫触')
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
  return readJsonOrThrow(response, '涓婁紶闄勪欢鍐呭澶辫触')
}

export async function completeClientAttachment(
  baseUrl: string,
  attachmentId: string,
  payload: { ticket_id?: string; sha256?: string; size_bytes?: number },
): Promise<ClientAttachmentRecord> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/attachments/${encodeURIComponent(attachmentId)}/complete`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOrThrow<ClientAttachmentRecord>(response, '瀹屾垚闄勪欢涓婁紶澶辫触')
}

export async function listClientThreadAttachments(
  baseUrl: string,
  threadId: string,
): Promise<ClientAttachmentRecord[]> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/threads/${encodeURIComponent(threadId)}/attachments`))
  return readJsonOrThrow<ClientAttachmentRecord[]>(response, '鍔犺浇闄勪欢鍒楄〃澶辫触')
}

export async function deleteClientAttachment(
  baseUrl: string,
  attachmentId: string,
): Promise<ClientAttachmentRecord> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/attachments/${encodeURIComponent(attachmentId)}`), {
    method: 'DELETE',
  })
  return readJsonOrThrow<ClientAttachmentRecord>(response, '鍒犻櫎闄勪欢澶辫触')
}

export async function createClientAttachmentDownloadTicket(
  baseUrl: string,
  attachmentId: string,
  clientId?: string,
): Promise<ClientAttachmentDownloadTicket> {
  const query = clientId ? `?client_id=${encodeURIComponent(clientId)}` : ''
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/attachments/${encodeURIComponent(attachmentId)}/download-ticket${query}`))
  return readJsonOrThrow(response, '鍒涘缓闄勪欢涓嬭浇绁ㄦ嵁澶辫触')
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
    const failure = await readErrorMessage(response, '涓嬭浇闄勪欢鍐呭澶辫触')
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
  const payload = await readJsonOrThrow<unknown>(response, '鍔犺浇 token / context 蹇収澶辫触')
  const snapshot = parseRuntimeUsageEnvelope(payload)
  if (!snapshot) {
    throw new Error('瑙ｆ瀽 token / context 蹇収澶辫触')
  }
  return snapshot
}

export async function clearDesktopMemory(baseUrl: string): Promise<MemoryClearResult> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, '/memory'), {
    method: 'DELETE',
  })
  return readJsonOrThrow<MemoryClearResult>(response, 'Failed to clear memory')
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
  return readJsonOrThrow<MemoryRecordMutationResult>(response, 'Failed to update memory record')
}

export async function deleteDesktopMemoryRecord(
  baseUrl: string,
  memoryId: string,
): Promise<MemoryRecordMutationResult> {
  const response = await fetchWithAuth(buildDesktopUrl(baseUrl, `/memory/records/${encodeURIComponent(memoryId)}`), {
    method: 'DELETE',
  })
  return readJsonOrThrow<MemoryRecordMutationResult>(response, 'Failed to delete memory record')
}

export async function createClientWsUrl(
  baseUrl: string,
  threadId: string,
  identity: {
    clientId?: string
    sessionId?: string
    workspaceId?: string
    clientType?: string
    displayName?: string
  } = {},
): Promise<string> {
  const url = new URL(`${toClientWsBaseUrl(baseUrl)}/desktop/ws`)
  url.searchParams.set('thread_id', threadId)
  if (identity.clientId) {
    url.searchParams.set('client_id', identity.clientId)
  }
  if (identity.sessionId) {
    url.searchParams.set('session_id', identity.sessionId)
  }
  if (identity.workspaceId) {
    url.searchParams.set('workspace_id', identity.workspaceId)
  }
  if (identity.clientType) {
    url.searchParams.set('client_type', identity.clientType)
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
