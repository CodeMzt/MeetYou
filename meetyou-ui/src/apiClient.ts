import { parseErrorEnvelope } from './protocolClient'
import { DEFAULT_BASE_URL } from './windowBridge'

let cachedAccessToken: string | null = null

declare global {
  interface Window {
    __meetyouAuthTrace?: {
      baseUrl: string
      entries: Array<{
        ts: string
        method: string
        url: string
        host: string
        attachAuth: boolean
        tokenPresent: boolean
        tokenSource: string
        status?: number
        error?: string
      }>
    }
  }
}

type TokenResolution = {
  token: string
  source: 'ipc' | 'localStorage' | 'none'
}

function traceAuth(entry: {
  method: string
  url: string
  attachAuth: boolean
  tokenPresent: boolean
  tokenSource: string
  status?: number
  error?: string
}) {
  try {
    const target = new URL(entry.url, DEFAULT_BASE_URL)
    const container = (window.__meetyouAuthTrace ||= {
      baseUrl: DEFAULT_BASE_URL,
      entries: [],
    })
    container.baseUrl = DEFAULT_BASE_URL
    container.entries.push({
      ts: new Date().toISOString(),
      method: entry.method,
      url: target.toString(),
      host: target.host,
      attachAuth: entry.attachAuth,
      tokenPresent: entry.tokenPresent,
      tokenSource: entry.tokenSource,
      status: entry.status,
      error: entry.error,
    })
    if (container.entries.length > 80) {
      container.entries.splice(0, container.entries.length - 80)
    }
  } catch {
    // Ignore diagnostics failures.
  }
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

export async function resolveAccessTokenDetailed(): Promise<TokenResolution> {
  if (cachedAccessToken) {
    return { token: cachedAccessToken, source: 'ipc' }
  }

  try {
    const ipcToken = await window.ipcRenderer?.invoke?.('get-gateway-access-token')
    if (typeof ipcToken === 'string') {
      const token = ipcToken.trim()
      cachedAccessToken = token || null
      try {
        localStorage.setItem('meetyou_access_token', token)
      } catch {
        // Ignore local storage failures in constrained contexts.
      }
      return {
        token,
        source: token ? 'ipc' : 'none',
      }
    }
  } catch {
    // Ignore IPC resolution failures and fall back to empty token.
  }

  const localToken = getAccessToken().trim()
  if (localToken) {
    cachedAccessToken = localToken
    return {
      token: cachedAccessToken,
      source: 'localStorage',
    }
  }

  return { token: '', source: 'none' }
}

export async function resolveAccessToken(): Promise<string> {
  const { token } = await resolveAccessTokenDetailed()
  return token
}

export async function fetchWithAuth(url: string, init?: RequestInit): Promise<Response> {
  const tokenResult = await resolveAccessTokenDetailed()
  const token = tokenResult.token
  const headers = new Headers(init?.headers)
  const attachAuth = Boolean(token && shouldAttachAccessToken(url))
  if (attachAuth) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  const method = String(init?.method || 'GET').toUpperCase()
  try {
    const response = await fetch(url, { ...init, headers })
    traceAuth({
      method,
      url,
      attachAuth,
      tokenPresent: Boolean(token),
      tokenSource: tokenResult.source,
      status: response.status,
    })
    return response
  } catch (error) {
    traceAuth({
      method,
      url,
      attachAuth,
      tokenPresent: Boolean(token),
      tokenSource: tokenResult.source,
      error: error instanceof Error ? error.message : String(error),
    })
    throw error
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
