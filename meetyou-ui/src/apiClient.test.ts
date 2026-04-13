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

  it('retries token resolution after an initial empty result', async () => {
    vi.resetModules()
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    globalThis.fetch = fetchMock as typeof fetch
    const getItem = vi
      .fn()
      .mockReturnValueOnce('')
      .mockReturnValueOnce('token-later')
    globalThis.localStorage = {
      getItem,
      setItem: vi.fn(),
    } as unknown as Storage
    globalThis.window = Object.assign(globalThis.window || {}, {
      ipcRenderer: {
        invoke: vi.fn().mockResolvedValue(''),
      },
    }) as Window & typeof globalThis

    const { fetchWithAuth: freshFetchWithAuth } = await import('./apiClient')

    await freshFetchWithAuth('http://127.0.0.1:8000/first')
    await freshFetchWithAuth('http://127.0.0.1:8000/second')

    expect(fetchMock).toHaveBeenCalledTimes(2)
    const firstHeaders = new Headers(fetchMock.mock.calls[0]?.[1]?.headers)
    const secondHeaders = new Headers(fetchMock.mock.calls[1]?.[1]?.headers)
    expect(firstHeaders.get('Authorization')).toBeNull()
    expect(secondHeaders.get('Authorization')).toBe('Bearer token-later')
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
