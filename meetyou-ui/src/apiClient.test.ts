import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchWithAuth, readErrorMessage } from './apiClient'
import { DEFAULT_BASE_URL } from './windowBridge'

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
    globalThis.localStorage = { getItem: vi.fn(), setItem: vi.fn() } as unknown as Storage
    globalThis.window = Object.assign(globalThis.window || {}, {
      ipcRenderer: {
        invoke: vi.fn().mockResolvedValue('token-123'),
      },
    }) as Window & typeof globalThis

    await fetchWithAuth(`${DEFAULT_BASE_URL}/config`)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBe('Bearer token-123')
  })

  it('retries token resolution after an initial empty result', async () => {
    vi.resetModules()
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    globalThis.fetch = fetchMock as typeof fetch
    globalThis.localStorage = {
      getItem: vi.fn().mockReturnValue('token-later'),
      setItem: vi.fn(),
    } as unknown as Storage
    globalThis.window = Object.assign(globalThis.window || {}, {
      ipcRenderer: {
        invoke: vi.fn().mockResolvedValue(''),
      },
    }) as Window & typeof globalThis

    const { fetchWithAuth: freshFetchWithAuth } = await import('./apiClient')

    await freshFetchWithAuth(`${DEFAULT_BASE_URL}/first`)
    await freshFetchWithAuth(`${DEFAULT_BASE_URL}/second`)

    expect(fetchMock).toHaveBeenCalledTimes(2)
    const firstHeaders = new Headers(fetchMock.mock.calls[0]?.[1]?.headers)
    const secondHeaders = new Headers(fetchMock.mock.calls[1]?.[1]?.headers)
    expect(firstHeaders.get('Authorization')).toBeNull()
    expect(secondHeaders.get('Authorization')).toBeNull()
  })

  it('does not fall back to gateway token when desktop bridge token IPC is unavailable', async () => {
    vi.resetModules()
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    const invoke = vi.fn(async (channel: string) => {
      if (channel === 'get-desktop-bridge-access-token') {
        return undefined
      }
      if (channel === 'get-gateway-access-token') {
        return 'gateway-token-should-not-be-used'
      }
      return undefined
    })
    globalThis.fetch = fetchMock as typeof fetch
    globalThis.localStorage = {
      getItem: vi.fn().mockReturnValue(''),
      setItem: vi.fn(),
    } as unknown as Storage
    globalThis.window = Object.assign(globalThis.window || {}, {
      ipcRenderer: {
        invoke,
      },
    }) as Window & typeof globalThis

    const { fetchWithAuth: freshFetchWithAuth } = await import('./apiClient')
    await freshFetchWithAuth(`${DEFAULT_BASE_URL}/desktop/workspaces`)

    expect(invoke).toHaveBeenCalledWith('get-desktop-bridge-access-token')
    expect(invoke).not.toHaveBeenCalledWith('get-gateway-access-token')
    const [, init] = fetchMock.mock.calls[0]
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBeNull()
  })

  it('does not attach local bridge token to external urls', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    globalThis.fetch = fetchMock as typeof fetch
    globalThis.localStorage = { getItem: vi.fn(), setItem: vi.fn() } as unknown as Storage
    globalThis.window = Object.assign(globalThis.window || {}, {
      ipcRenderer: {
        invoke: vi.fn().mockResolvedValue('bridge-token'),
      },
    }) as Window & typeof globalThis

    await fetchWithAuth('https://minio.example.com/object/demo')

    const [, init] = fetchMock.mock.calls[0]
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBeNull()
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
