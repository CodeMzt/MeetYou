import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchWithAuth, readErrorMessage } from './apiClient'

const originalFetch = globalThis.fetch
const originalLocalStorage = globalThis.localStorage

describe('apiClient', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  it('adds bearer token when available', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    globalThis.fetch = fetchMock as typeof fetch
    globalThis.localStorage = {
      getItem: vi.fn().mockReturnValue('token-123'),
    } as unknown as Storage

    await fetchWithAuth('http://127.0.0.1:8000/config')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBe('Bearer token-123')
  })

  it('reads structured error message from backend envelope', async () => {
    const response = new Response(
      JSON.stringify({
        schema: 'meetyou.http.v1',
        kind: 'error',
        error: {
          code: 'invalid_config_update',
          category: 'validation',
          message: 'mode_router 配置无效',
          retryable: false,
          details: {},
          occurred_at: '',
        },
      }),
      {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      },
    )

    const failure = await readErrorMessage(response, '更新配置失败')

    expect(failure.code).toBe('invalid_config_update')
    expect(failure.message).toBe('mode_router 配置无效')
    expect(failure.status).toBe(400)
  })
})
