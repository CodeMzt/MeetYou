import { parseErrorEnvelope } from './protocolClient'

let cachedAccessToken: string | null = null

export function getAccessToken(): string {
  try {
    return localStorage.getItem('meetyou_access_token') || ''
  } catch {
    return ''
  }
}

export async function resolveAccessToken(): Promise<string> {
  if (cachedAccessToken !== null) {
    return cachedAccessToken
  }

  const localToken = getAccessToken().trim()
  if (localToken) {
    cachedAccessToken = localToken
    return cachedAccessToken
  }

  try {
    const token = String((await window.ipcRenderer?.invoke?.('get-gateway-access-token')) || '').trim()
    if (token) {
      cachedAccessToken = token
      try {
        localStorage.setItem('meetyou_access_token', token)
      } catch {
        // Ignore local storage failures in constrained contexts.
      }
      return cachedAccessToken
    }
  } catch {
    // Ignore IPC resolution failures and fall back to empty token.
  }

  cachedAccessToken = ''
  return cachedAccessToken
}

export async function fetchWithAuth(url: string, init?: RequestInit): Promise<Response> {
  const token = await resolveAccessToken()
  const headers = new Headers(init?.headers)
  if (token) {
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
