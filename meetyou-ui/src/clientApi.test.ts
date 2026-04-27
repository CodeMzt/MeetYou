import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  clearDesktopMemory,
  createDanxiReply,
  deleteDesktopMemoryRecord,
  deleteDanxiReply,
  fetchRuntimeUsageSnapshot,
  getDanxiPostSummary,
  getDanxiProfile,
  resolveDanxiMessageTarget,
  getDanxiSessionStatus,
  getClientProcedureDetail,
  getClientThreadProcedureContext,
  listDanxiPosts,
  listOperatorSourceProfiles,
  loginDanxiSession,
  listClientProcedures,
  resolveClientAttachmentDownloadPlan,
  updateDanxiReply,
  updateDanxiWebvpnCookie,
  updateOperatorWorkspaceGovernance,
  pinClientThreadProcedure,
  unpinClientThreadProcedure,
  updateDesktopMemoryRecordStatus,
} from './clientApi'
import { DEFAULT_BASE_URL } from './windowBridge'

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

  it('clears memory through desktop operator surface', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          cleared_record_count: 4,
          cleared_edge_count: 3,
          cleared_session_summary_count: 2,
          cleared_global_summary: true,
          cleared_session_count: 2,
          active_session_count: 0,
          updated_at: '2026-04-23T00:00:00Z',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as typeof fetch

    const result = await clearDesktopMemory('http://127.0.0.1:8000')

    expect(result.ok).toBe(true)
    expect(result.cleared_record_count).toBe(4)
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/desktop/memory',
      expect.objectContaining({
        method: 'DELETE',
      }),
    )
  })

  it('updates and deletes individual memory records through desktop operator surface', async () => {
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: true,
            memory_id: 'memory/one',
            status: 'invalidated',
            deleted: false,
            updated_at: '2026-04-24T00:00:00Z',
            record: { id: 'memory/one', status: 'invalidated' },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: true,
            memory_id: 'memory/one',
            status: 'deleted',
            deleted: true,
            updated_at: '2026-04-24T00:00:01Z',
            record: null,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ) as typeof fetch

    const updated = await updateDesktopMemoryRecordStatus('http://127.0.0.1:8000', 'memory/one', 'invalidated')
    const deleted = await deleteDesktopMemoryRecord('http://127.0.0.1:8000', 'memory/one')

    expect(updated.status).toBe('invalidated')
    expect(deleted.deleted).toBe(true)
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/desktop/memory/records/memory%2Fone',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ status: 'invalidated' }),
      }),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/desktop/memory/records/memory%2Fone',
      expect.objectContaining({
        method: 'DELETE',
      }),
    )
  })

  it('loads procedures from client API', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            procedure_id: 'proc_focus',
            title: '涓撴敞妯″紡',
            description: '杩涘叆涓撴敞鎵ц娴佺▼',
            applicable_modes: ['general'],
            recommended_tools: ['manage_tasks'],
            preferred_tool_key: 'manage_tasks',
            preferred_target_endpoint_ids: [],
            preferred_endpoint_provider_types: ['desktop'],
            tool_target_routing_policy: 'balanced',
            default_execution_target: 'specific_client',
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
    expect(procedures[0]?.default_execution_target).toBe('specific_client')
    expect(procedures[0]?.preferred_tool_key).toBe('manage_tasks')
  })

  it('loads procedure detail and thread procedure context from client API', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            procedure_id: 'code_review',
            title: 'Code Review',
            description: 'Review code changes before merging.',
            applicable_modes: ['general'],
            recommended_tools: ['search_memory'],
            preferred_tool_key: 'search_memory',
            preferred_target_endpoint_ids: [],
            preferred_endpoint_provider_types: [],
            tool_target_routing_policy: 'balanced',
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
              description: 'Review code changes before merging.',
              applicable_modes: ['general'],
              recommended_tools: ['search_memory'],
              preferred_tool_key: 'search_memory',
              preferred_target_endpoint_ids: [],
              preferred_endpoint_provider_types: [],
              tool_target_routing_policy: 'balanced',
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
              description: 'Review code changes before merging.',
              applicable_modes: ['general'],
              recommended_tools: ['search_memory'],
              preferred_tool_key: 'search_memory',
              preferred_target_endpoint_ids: [],
              preferred_endpoint_provider_types: [],
              tool_target_routing_policy: 'balanced',
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
              description: 'Review code changes before merging.',
              applicable_modes: ['general'],
              recommended_tools: ['search_memory'],
              preferred_tool_key: 'search_memory',
              preferred_target_endpoint_ids: [],
              preferred_endpoint_provider_types: [],
              tool_target_routing_policy: 'balanced',
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
              description: 'Review code changes before merging.',
              applicable_modes: ['general'],
              recommended_tools: ['search_memory'],
              preferred_tool_key: 'search_memory',
              preferred_target_endpoint_ids: [],
              preferred_endpoint_provider_types: [],
              tool_target_routing_policy: 'balanced',
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
          title: 'Study',
          status: 'active',
          base_mode: 'study',
          description: 'Study workspace for focused learning.',
          prompt_overlay: '',
          default_execution_target: 'core_only',
          tool_policy: 'allow_all',
          allowed_tool_ids: [],
          preferred_target_endpoint_ids: [],
          preferred_endpoint_provider_types: [],
          preferred_source_profiles: ['study_materials', 'workspace_local'],
          tool_target_routing_policy: 'balanced',
          memory_ranking_policy: 'workspace_first',
          tool_routing_overrides: {},
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as typeof fetch

    const workspace = await updateOperatorWorkspaceGovernance('http://127.0.0.1:8000', 'study', {
      base_mode: 'danxi',
      preferred_source_profiles: ['study_materials', 'workspace_local'],
      memory_ranking_policy: 'workspace_first',
    })

    expect(workspace.workspace_id).toBe('study')
    expect(workspace.preferred_source_profiles).toEqual(['study_materials', 'workspace_local'])
    expect(workspace.memory_ranking_policy).toBe('workspace_first')
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/desktop/workspaces/study',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          base_mode: 'danxi',
          preferred_source_profiles: ['study_materials', 'workspace_local'],
          memory_ranking_policy: 'workspace_first',
        }),
      }),
    )
  })

  it('logs into Danxi session and patches WebVPN cookie through client API', async () => {
    const invoke = vi.fn(async (channel: string, payload?: { purpose?: string }) => {
      if (channel === 'get-gateway-access-token') {
        return ''
      }
      if (channel === 'encrypt-danxi-credentials' && payload?.purpose === 'danxi.client.login.v1') {
        return {
          version: 'v1',
          alg: 'aes-256-gcm',
          purpose: 'danxi.client.login.v1',
          iv: 'iv-login',
          ciphertext: 'cipher-login',
          tag: 'tag-login',
        }
      }
      if (channel === 'encrypt-danxi-credentials' && payload?.purpose === 'danxi.client.webvpn_cookie.v1') {
        return {
          version: 'v1',
          alg: 'aes-256-gcm',
          purpose: 'danxi.client.webvpn_cookie.v1',
          iv: 'iv-cookie',
          ciphertext: 'cipher-cookie',
          tag: 'tag-cookie',
        }
      }
      return undefined
    })
    ;(globalThis as { window?: Window }).window = {
      ipcRenderer: {
        send: vi.fn(),
        on: vi.fn(() => () => {}),
        off: vi.fn(),
        invoke,
      },
    } as unknown as Window
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            session_key: 'default',
            email: 'user@example.com',
            transport: 'direct',
            webvpn_enabled: false,
            has_webvpn_cookie: false,
            webvpn_required: false,
            direct_connect_available: true,
            logged_in: true,
            user_profile: { user_id: 1 },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            session_key: 'default',
            email: 'user@example.com',
            transport: 'webvpn',
            webvpn_enabled: true,
            has_webvpn_cookie: true,
            webvpn_required: true,
            direct_connect_available: false,
            logged_in: true,
            user_profile: { user_id: 1 },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ) as typeof fetch

    const session = await loginDanxiSession('http://127.0.0.1:8000', {
      email: 'user@example.com',
      password: 'secret',
      use_webvpn: false,
    })
    const patched = await updateDanxiWebvpnCookie('http://127.0.0.1:8000', {
      cookie_header: 'vpn=ok',
      enable_webvpn: true,
    })

    expect(session.transport).toBe('direct')
    expect(patched.transport).toBe('webvpn')
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/desktop/danxi/session/login',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          session_key: 'default',
          encrypted_credentials: {
            version: 'v1',
            alg: 'aes-256-gcm',
            purpose: 'danxi.client.login.v1',
            iv: 'iv-login',
            ciphertext: 'cipher-login',
            tag: 'tag-login',
          },
        }),
      }),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/desktop/danxi/session/webvpn-cookie',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          session_key: 'default',
          encrypted_credentials: {
            version: 'v1',
            alg: 'aes-256-gcm',
            purpose: 'danxi.client.webvpn_cookie.v1',
            iv: 'iv-cookie',
            ciphertext: 'cipher-cookie',
            tag: 'tag-cookie',
          },
        }),
      }),
    )
  })

  it('rejects Danxi credential submission when encrypted transport is unavailable', async () => {
    ;(globalThis as { window?: Window }).window = {} as Window
    globalThis.fetch = vi.fn() as typeof fetch

    await expect(
      loginDanxiSession('http://127.0.0.1:8000', {
        email: 'user@example.com',
        password: 'secret',
      }),
    ).rejects.toThrow('Encrypted Danxi credential transport is only available in the Electron desktop app.')

    await expect(
      updateDanxiWebvpnCookie('http://127.0.0.1:8000', {
        cookie_header: 'vpn=ok',
      }),
    ).rejects.toThrow('Encrypted Danxi credential transport is only available in the Electron desktop app.')

    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('loads Danxi session status and posts via client API', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            session_key: 'default',
            email: 'user@example.com',
            transport: 'webvpn',
            webvpn_enabled: true,
            has_webvpn_cookie: true,
            webvpn_required: true,
            direct_connect_available: false,
            logged_in: true,
            user_profile: { user_id: 1 },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            scope: 'homepage',
            count: 1,
            items: [{ hole_id: 101, content: 'hello danxi' }],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ) as typeof fetch

    const session = await getDanxiSessionStatus('http://127.0.0.1:8000')
    const posts = await listDanxiPosts('http://127.0.0.1:8000', { length: 12 })

    expect(session.logged_in).toBe(true)
    expect(posts.items[0]?.hole_id).toBe(101)
  })

  it('loads Danxi profile and supports reply/edit/delete/summary facades', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            session_key: 'default',
            logged_in: true,
            transport: 'direct',
            webvpn_enabled: false,
            has_webvpn_cookie: false,
            webvpn_required: false,
            direct_connect_available: true,
            profile: { user_id: 7, nickname: 'Student' },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: true,
            status_code: 201,
            message: 'reply created',
            hole_id: 101,
            floor_id: 9001,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: true,
            status_code: 200,
            message: 'reply updated',
            floor_id: 9001,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: true,
            status_code: 200,
            message: 'reply deleted',
            floor_id: 9001,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            hole_id: 101,
            title: 'Post #101',
            summary: 'Summary with two key points and two replies.',
            key_points: ['first point', 'second point'],
            reply_highlights: ['reply highlight'],
            floor_count: 2,
            participant_count: 2,
            generated_at: '2026-04-14T00:00:00Z',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ) as typeof fetch

    const profile = await getDanxiProfile('http://127.0.0.1:8000', { refresh: true })
    const created = await createDanxiReply('http://127.0.0.1:8000', 101, { content: '鎴戜篃閬囧埌杩欎釜闂' })
    const updated = await updateDanxiReply('http://127.0.0.1:8000', 9001, { content: '宸茶В鍐筹紝璋㈣阿' })
    const deleted = await deleteDanxiReply('http://127.0.0.1:8000', 9001, { confirm: true })
    const summary = await getDanxiPostSummary('http://127.0.0.1:8000', 101, { floor_limit: 20 })

    expect(profile.profile?.nickname).toBe('Student')
    expect(created.ok).toBe(true)
    expect(updated.message).toContain('updated')
    expect(deleted.floor_id).toBe(9001)
    expect(summary.hole_id).toBe(101)
    expect(summary.reply_highlights[0]).toContain('reply highlight')
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/desktop/danxi/profile?refresh=true',
      expect.anything(),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/desktop/danxi/posts/101/replies',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      3,
      'http://127.0.0.1:8000/desktop/danxi/floors/9001',
      expect.objectContaining({ method: 'PATCH' }),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      4,
      'http://127.0.0.1:8000/desktop/danxi/floors/9001?confirm=true',
      expect.objectContaining({ method: 'DELETE' }),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      5,
      'http://127.0.0.1:8000/desktop/danxi/posts/101/summary?floor_limit=20',
      expect.anything(),
    )
  })

  it('resolves Danxi message floor target via desktop API', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ floor_id: 5732346, hole_id: 632931 }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as typeof fetch

    const target = await resolveDanxiMessageTarget('http://127.0.0.1:8000', 5732346)

    expect(target.floor_id).toBe(5732346)
    expect(target.hole_id).toBe(632931)
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/desktop/danxi/floors/5732346/target?session_key=default',
      expect.anything(),
    )
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

    const { downloadClientAttachmentContent: downloadAttachment } = await import('./clientApi')
    const blob = await downloadAttachment(`${DEFAULT_BASE_URL}/desktop/attachments/content/att_1?ticket_id=down_1`)

    expect(await blob.text()).toBe('attachment-body')
    expect(globalThis.fetch).toHaveBeenCalledWith(
      `${DEFAULT_BASE_URL}/desktop/attachments/content/att_1?ticket_id=down_1`,
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    )
    const [, init] = vi.mocked(globalThis.fetch).mock.calls[0] || []
    const headers = init?.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer test-token')
  })

  it('downloads direct attachment urls without local bridge auth headers', async () => {
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

    const { downloadClientAttachmentContent: downloadAttachment } = await import('./clientApi')
    await downloadAttachment('https://minio.example.com/presigned/att_1')

    const [, init] = vi.mocked(globalThis.fetch).mock.calls[0] || []
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBeNull()
  })

  it('creates websocket urls against desktop bridge instead of Core client ws', async () => {
    vi.resetModules()
    globalThis.localStorage = {
      getItem: vi.fn().mockReturnValue('local-bridge-token'),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
      key: vi.fn(),
      length: 0,
    } as unknown as Storage
    ;(globalThis as { window?: Window }).window = {} as Window

    const { createClientWsUrl: createWsUrl } = await import('./clientApi')
    const url = await createWsUrl('http://127.0.0.1:38951', 'thr_1', {
      clientId: 'desktop-app',
      sessionId: 'sess_1',
      workspaceId: 'personal',
      clientType: 'electron',
      displayName: 'Desktop App',
    })

    expect(url).toBe(
      'ws://127.0.0.1:38951/desktop/ws?thread_id=thr_1&client_id=desktop-app&session_id=sess_1&workspace_id=personal&client_type=electron&display_name=Desktop+App&access_token=local-bridge-token',
    )
  })

  it('prefers direct browser download for presigned attachment tickets', () => {
    const plan = resolveClientAttachmentDownloadPlan({
      attachment_id: 'att_1',
      ticket_id: 'down_1',
      download_url: 'https://minio.example.com/presigned/att_1',
      fallback_download_url: 'http://127.0.0.1:8000/desktop/attachments/content/att_1?ticket_id=down_1',
      download_strategy: 'presigned',
      expires_at: '2026-04-13T00:00:00Z',
      mime_type: 'image/png',
      file_name: 'capture.png',
      size_bytes: 1024,
    })

    expect(plan).toEqual({
      mode: 'direct',
      url: 'https://minio.example.com/presigned/att_1',
      fileName: 'capture.png',
    })
  })

  it('falls back to proxy download plan for non-presigned tickets', () => {
    const plan = resolveClientAttachmentDownloadPlan({
      attachment_id: 'att_2',
      ticket_id: 'down_2',
      download_url: 'http://127.0.0.1:8000/desktop/attachments/content/att_2?ticket_id=down_2',
      fallback_download_url: 'http://127.0.0.1:8000/desktop/attachments/content/att_2?ticket_id=down_2',
      download_strategy: 'proxy',
      expires_at: '2026-04-13T00:00:00Z',
      mime_type: 'application/pdf',
      file_name: 'report.pdf',
      size_bytes: 2048,
    })

    expect(plan).toEqual({
      mode: 'proxy',
      url: 'http://127.0.0.1:8000/desktop/attachments/content/att_2?ticket_id=down_2',
      fileName: 'report.pdf',
    })
  })

  it('treats non-proxy direct urls as direct download even without strategy', () => {
    const plan = resolveClientAttachmentDownloadPlan({
      attachment_id: 'att_3',
      ticket_id: 'down_3',
      download_url: 'https://minio.example.com/presigned/att_3?X-Amz-Signature=demo',
      fallback_download_url: '',
      download_strategy: '',
      expires_at: '2026-04-13T00:00:00Z',
      mime_type: 'image/jpeg',
      file_name: 'photo.jpg',
      size_bytes: 4096,
    })

    expect(plan).toEqual({
      mode: 'direct',
      url: 'https://minio.example.com/presigned/att_3?X-Amz-Signature=demo',
      fileName: 'photo.jpg',
    })
  })
})
