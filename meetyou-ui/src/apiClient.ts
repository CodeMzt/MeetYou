import { parseErrorEnvelope } from './protocolClient'
import { DEFAULT_BASE_URL } from './windowBridge'

let cachedAccessToken: string | null = null

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
    const ipcToken = await window.ipcRenderer?.invoke?.('get-gateway-access-token')
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

export async function fetchWithAuth(url: string, init?: RequestInit): Promise<Response> {
  const token = await resolveAccessToken()
  const headers = new Headers(init?.headers)
  if (token && shouldAttachAccessToken(url)) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  return fetch(url, { ...init, headers })
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
