import { parseErrorEnvelope } from './protocolClient'

export function getAccessToken(): string {
  try {
    return localStorage.getItem('meetyou_access_token') || ''
  } catch {
    return ''
  }
}

export async function fetchWithAuth(url: string, init?: RequestInit): Promise<Response> {
  const token = getAccessToken()
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
