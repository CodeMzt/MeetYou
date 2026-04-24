import { parseErrorEnvelope } from './protocolClient'
import { DEFAULT_BASE_URL } from './windowBridge'

let cachedAccessToken: string | null = null
const TOKEN_IPC_TIMEOUT_MS = 1500
const DEFAULT_FETCH_TIMEOUT_MS = 30000
const IPC_TIMEOUT = Symbol('ipc-timeout')

type FetchWithAuthInit = RequestInit & {
  timeoutMs?: number
}

async function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T | typeof IPC_TIMEOUT> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<typeof IPC_TIMEOUT>((resolve) => {
    timeoutId = setTimeout(() => resolve(IPC_TIMEOUT), timeoutMs)
  })
  return Promise.race([
    promise.finally(() => {
      if (timeoutId) {
        clearTimeout(timeoutId)
      }
    }),
    timeout,
  ])
}

function shouldAttachAccessToken(url: string): boolean {
  try {
    const target = new URL(url, DEFAULT_BASE_URL)
    const desktopBridge = new URL(DEFAULT_BASE_URL)
    return target.origin === desktopBridge.origin
  } catch {
    return false
  }
}

export function getAccessToken(): string {
  try {
    return localStorage.getItem('meetyou_access_token') || ''
  } catch {
    return ''
  }
}

export async function resolveAccessToken(): Promise<string> {
  if (cachedAccessToken) {
    return cachedAccessToken
  }

  try {
    const ipcInvoke = window.ipcRenderer?.invoke
    const ipcToken =
      typeof ipcInvoke === 'function'
        ? await withTimeout(Promise.resolve(ipcInvoke('get-desktop-bridge-access-token')), TOKEN_IPC_TIMEOUT_MS)
        : undefined
    if (typeof ipcToken === 'string') {
      const token = ipcToken.trim()
      cachedAccessToken = token || null
      try {
        localStorage.setItem('meetyou_access_token', token)
      } catch {
        // Ignore local storage failures in constrained contexts.
      }
      return token
    }
  } catch {
    // Ignore IPC resolution failures and fall back to empty token.
  }

  const localToken = getAccessToken().trim()
  if (localToken) {
    cachedAccessToken = localToken
    return cachedAccessToken
  }

  return ''
}

export async function fetchWithAuth(url: string, init?: FetchWithAuthInit): Promise<Response> {
  const { timeoutMs = DEFAULT_FETCH_TIMEOUT_MS, ...requestInit } = init ?? {}
  const token = await resolveAccessToken()
  const headers = new Headers(requestInit.headers)
  if (token && shouldAttachAccessToken(url)) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  if (!timeoutMs || timeoutMs <= 0) {
    return fetch(url, { ...requestInit, headers })
  }

  const controller = new AbortController()
  const upstreamSignal = requestInit.signal
  const abortFromUpstream = () => controller.abort(upstreamSignal?.reason)
  if (upstreamSignal?.aborted) {
    abortFromUpstream()
  } else {
    upstreamSignal?.addEventListener('abort', abortFromUpstream, { once: true })
  }
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...requestInit, headers, signal: controller.signal })
  } catch (error) {
    if (controller.signal.aborted && !upstreamSignal?.aborted) {
      throw new Error(`请求超时（${Math.ceil(timeoutMs / 1000)}s）`)
    }
    throw error
  } finally {
    clearTimeout(timeoutId)
    upstreamSignal?.removeEventListener('abort', abortFromUpstream)
  }
}

export async function readErrorMessage(
  response: Response,
  fallback: string,
): Promise<{ message: string; code: string; status: number }> {
  const payload = await response.json().catch(() => null)
  const parsed = parseErrorEnvelope(payload)
  if (parsed) {
    return {
      message: parsed.message || fallback,
      code: parsed.code,
      status: response.status,
    }
  }
  return {
    message: response.status ? `${fallback}（HTTP ${response.status}）` : fallback,
    code: '',
    status: response.status,
  }
}
