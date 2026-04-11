import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchRuntimeUsageSnapshot, listClientProcedures } from './clientApi'

const originalFetch = globalThis.fetch
const originalLocalStorage = globalThis.localStorage

describe('clientApi', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  it('hydrates runtime usage snapshot from HTTP envelope', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          schema: 'meetyou.http.v1',
          kind: 'runtime',
          runtime: {
            resource: 'usage',
            session_id: 'sess_1',
            usage: {
              session_id: 'sess_1',
              usage_ready: false,
              context_limit_tokens: 128000,
              context_limit_source: 'config_override',
              context_limit_model: 'gpt-5.4',
              context_limit_confidence: 'high',
              current_context_tokens_estimated: 0,
              context_breakdown: {
                system: 0,
                history: 0,
                tool_history: 0,
                memory_context: 0,
                policy: 0,
                current_input: 0,
                proprioception: 0,
                total: 0,
              },
              last_turn_usage: {
                prompt_tokens: 0,
                completion_tokens: 0,
                reasoning_tokens: 0,
                total_tokens: 0,
              },
              session_totals: {
                prompt_tokens: 0,
                completion_tokens: 0,
                reasoning_tokens: 0,
                total_tokens: 0,
                turn_count: 0,
              },
              usage_source: 'estimated',
              updated_at: '2026-04-09T00:00:01Z',
            },
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as typeof fetch

    const snapshot = await fetchRuntimeUsageSnapshot('http://127.0.0.1:8000', 'sess_1')

    expect(snapshot.session_id).toBe('sess_1')
    expect(snapshot.usage_ready).toBe(false)
    expect(snapshot.context_limit_tokens).toBe(128000)
    expect(snapshot.session_totals.turn_count).toBe(0)
  })

  it('loads procedures from client API', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            procedure_id: 'proc_focus',
            title: '专注模式',
            description: '进入专注执行流程',
            applicable_modes: ['general'],
            recommended_capabilities: ['manage_tasks'],
            preferred_capability_ref: 'manage_tasks',
            preferred_agent_ids: [],
            preferred_agent_types: ['desktop'],
            agent_routing_policy: 'balanced',
            default_execution_target: 'specific_agent',
            risk_profile: 'low',
            status: 'active',
          },
        ]),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as typeof fetch

    const procedures = await listClientProcedures('http://127.0.0.1:8000')

    expect(procedures).toHaveLength(1)
    expect(procedures[0]?.procedure_id).toBe('proc_focus')
    expect(procedures[0]?.default_execution_target).toBe('specific_agent')
    expect(procedures[0]?.preferred_capability_ref).toBe('manage_tasks')
  })

  it('downloads attachment content with auth headers', async () => {
    vi.resetModules()
    globalThis.localStorage = {
      getItem: vi.fn().mockReturnValue('test-token'),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
      key: vi.fn(),
      length: 0,
    } as unknown as Storage

    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response('attachment-body', {
        status: 200,
        headers: { 'Content-Type': 'text/plain' },
      }),
    ) as typeof fetch

    const { downloadClientAttachmentContent } = await import('./clientApi')
    const blob = await downloadClientAttachmentContent('http://127.0.0.1:8000/client/attachments/content/att_1?ticket_id=down_1')

    expect(await blob.text()).toBe('attachment-body')
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/client/attachments/content/att_1?ticket_id=down_1',
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    )
    const [, init] = vi.mocked(globalThis.fetch).mock.calls[0] || []
    const headers = init?.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer test-token')
  })
})
