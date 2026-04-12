import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fetchRuntimeUsageSnapshot,
  getClientProcedureDetail,
  getClientThreadProcedureContext,
  listOperatorSourceProfiles,
  listClientProcedures,
  updateOperatorWorkspaceGovernance,
  pinClientThreadProcedure,
  unpinClientThreadProcedure,
} from './clientApi'

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

  it('loads procedure detail and thread procedure context from client API', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            procedure_id: 'code_review',
            title: 'Code Review',
            description: '围绕代码变更、风险与验证给出结构化审查。',
            applicable_modes: ['general'],
            recommended_capabilities: ['search_memory'],
            preferred_capability_ref: 'search_memory',
            preferred_agent_ids: [],
            preferred_agent_types: [],
            agent_routing_policy: 'balanced',
            default_execution_target: 'core_only',
            risk_profile: 'read',
            status: 'active',
            prompt_overlay: 'Focus on correctness first.',
            recommended_source_profiles: ['workspace_local'],
            infer_keywords: ['review', 'patch'],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            source: 'inferred',
            pinned_procedure: null,
            latest_inferred_procedure: {
              procedure_id: 'code_review',
              title: 'Code Review',
              description: '围绕代码变更、风险与验证给出结构化审查。',
              applicable_modes: ['general'],
              recommended_capabilities: ['search_memory'],
              preferred_capability_ref: 'search_memory',
              preferred_agent_ids: [],
              preferred_agent_types: [],
              agent_routing_policy: 'balanced',
              default_execution_target: 'core_only',
              risk_profile: 'read',
              status: 'active',
              prompt_overlay: 'Focus on correctness first.',
              recommended_source_profiles: ['workspace_local'],
              infer_keywords: ['review', 'patch'],
            },
            effective_procedure: {
              procedure_id: 'code_review',
              title: 'Code Review',
              description: '围绕代码变更、风险与验证给出结构化审查。',
              applicable_modes: ['general'],
              recommended_capabilities: ['search_memory'],
              preferred_capability_ref: 'search_memory',
              preferred_agent_ids: [],
              preferred_agent_types: [],
              agent_routing_policy: 'balanced',
              default_execution_target: 'core_only',
              risk_profile: 'read',
              status: 'active',
              prompt_overlay: 'Focus on correctness first.',
              recommended_source_profiles: ['workspace_local'],
              infer_keywords: ['review', 'patch'],
            },
            latest_inferred_reason: 'keywords:review,patch',
            latest_inferred_score: 7,
            latest_inferred_at: '2026-04-12T00:00:00Z',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ) as typeof fetch

    const detail = await getClientProcedureDetail('http://127.0.0.1:8000', 'code_review')
    const context = await getClientThreadProcedureContext('http://127.0.0.1:8000', 'thr_1')

    expect(detail.prompt_overlay).toContain('Focus on correctness')
    expect(detail.infer_keywords).toContain('review')
    expect(context.source).toBe('inferred')
    expect(context.effective_procedure?.procedure_id).toBe('code_review')
    expect(context.latest_inferred_score).toBe(7)
  })

  it('pins and unpins thread procedure via client API', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            source: 'pinned',
            pinned_procedure: {
              procedure_id: 'code_review',
              title: 'Code Review',
              description: '围绕代码变更、风险与验证给出结构化审查。',
              applicable_modes: ['general'],
              recommended_capabilities: ['search_memory'],
              preferred_capability_ref: 'search_memory',
              preferred_agent_ids: [],
              preferred_agent_types: [],
              agent_routing_policy: 'balanced',
              default_execution_target: 'core_only',
              risk_profile: 'read',
              status: 'active',
              prompt_overlay: 'Focus on correctness first.',
              recommended_source_profiles: ['workspace_local'],
              infer_keywords: ['review', 'patch'],
            },
            latest_inferred_procedure: null,
            effective_procedure: {
              procedure_id: 'code_review',
              title: 'Code Review',
              description: '围绕代码变更、风险与验证给出结构化审查。',
              applicable_modes: ['general'],
              recommended_capabilities: ['search_memory'],
              preferred_capability_ref: 'search_memory',
              preferred_agent_ids: [],
              preferred_agent_types: [],
              agent_routing_policy: 'balanced',
              default_execution_target: 'core_only',
              risk_profile: 'read',
              status: 'active',
              prompt_overlay: 'Focus on correctness first.',
              recommended_source_profiles: ['workspace_local'],
              infer_keywords: ['review', 'patch'],
            },
            latest_inferred_reason: '',
            latest_inferred_score: 0,
            latest_inferred_at: '',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            source: 'none',
            pinned_procedure: null,
            latest_inferred_procedure: null,
            effective_procedure: null,
            latest_inferred_reason: '',
            latest_inferred_score: 0,
            latest_inferred_at: '',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ) as typeof fetch

    const pinned = await pinClientThreadProcedure('http://127.0.0.1:8000', 'thr_1', 'code_review')
    const unpinned = await unpinClientThreadProcedure('http://127.0.0.1:8000', 'thr_1')

    expect(pinned.source).toBe('pinned')
    expect(pinned.pinned_procedure?.procedure_id).toBe('code_review')
    expect(unpinned.source).toBe('none')
  })

  it('updates workspace governance through operator API', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          workspace_id: 'study',
          title: '学习',
          status: 'active',
          base_mode: 'study',
          description: '学习资料、笔记与复盘工作空间。',
          prompt_overlay: '',
          default_execution_target: 'core_only',
          capability_policy: 'allow_all',
          allowed_capability_ids: [],
          preferred_agent_ids: [],
          preferred_agent_types: [],
          preferred_source_profiles: ['study_materials', 'workspace_local'],
          agent_routing_policy: 'balanced',
          memory_ranking_policy: 'workspace_first',
          capability_routing_overrides: {},
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as typeof fetch

    const workspace = await updateOperatorWorkspaceGovernance('http://127.0.0.1:8000', 'study', {
      preferred_source_profiles: ['study_materials', 'workspace_local'],
      memory_ranking_policy: 'workspace_first',
    })

    expect(workspace.workspace_id).toBe('study')
    expect(workspace.preferred_source_profiles).toEqual(['study_materials', 'workspace_local'])
    expect(workspace.memory_ranking_policy).toBe('workspace_first')
  })

  it('loads source profile catalog from operator API', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            profile_name: 'workspace_local',
            label: 'Workspace / Local Knowledge',
            description: 'Prefer local files, memory, and private workspace knowledge.',
            official_only: false,
            default_freshness: 'workspace',
          },
          {
            profile_name: 'policy_global',
            label: 'Policy Global',
            description: 'Government and regulator sources outside China.',
            official_only: true,
            default_freshness: 'high',
          },
        ]),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as typeof fetch

    const profiles = await listOperatorSourceProfiles('http://127.0.0.1:8000')

    expect(profiles).toHaveLength(2)
    expect(profiles[0]?.profile_name).toBe('workspace_local')
    expect(profiles[1]?.official_only).toBe(true)
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
