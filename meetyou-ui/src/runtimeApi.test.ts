import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  clearDesktopMemory,
  createDanxiReply,
  deleteRuntimeThread,
  deleteDesktopMemoryRecord,
  deleteDanxiReply,
  ensureDefaultRuntimeThread,
  fetchRuntimeUsageSnapshot,
  getDanxiPostSummary,
  getDanxiProfile,
  resolveDanxiMessageTarget,
  getDanxiSessionStatus,
  listDanxiPosts,
  listOperatorSourceProfiles,
  listRuntimeThreads,
  loginDanxiSession,
  resolveRuntimeAttachmentDownloadPlan,
  updateDanxiReply,
  updateDanxiWebvpnCookie,
  updateOperatorWorkspaceGovernance,
  updateDesktopMemoryRecordStatus,
} from './runtimeApi'
import { DEFAULT_BASE_URL } from './windowBridge'

const originalFetch = globalThis.fetch
const originalLocalStorage = globalThis.localStorage

describe('runtimeApi', () => {
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

  it('updates workspace governance through operator API', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          workspace_id: 'study',
          title: 'Study',
          status: 'active',
          base_mode: 'general',
          description: 'Study workspace for focused learning.',
          prompt_overlay: '',
          default_execution_target: 'workspace_any_endpoint',
          tool_policy: 'allowlist',
          allowed_tool_ids: ['utility.echo'],
          preferred_target_endpoint_ids: ['desktop.study.executor'],
          preferred_endpoint_provider_types: ['desktop'],
          preferred_source_profiles: ['study_materials', 'workspace_local'],
          tool_target_routing_policy: 'strict_preferred_endpoint',
          memory_ranking_policy: 'workspace_first',
          tool_routing_overrides: {
            'utility.echo': {
              preferred_target_endpoint_ids: ['desktop.study.executor'],
              tool_target_routing_policy: 'strict_preferred_endpoint',
            },
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as typeof fetch

    const workspace = await updateOperatorWorkspaceGovernance('http://127.0.0.1:8000', 'study', {
      base_mode: 'danxi',
      default_execution_target: 'workspace_any_endpoint',
      tool_policy: 'allowlist',
      allowed_tool_ids: ['utility.echo'],
      preferred_target_endpoint_ids: ['desktop.study.executor'],
      preferred_endpoint_provider_types: ['desktop'],
      preferred_source_profiles: ['study_materials', 'workspace_local'],
      tool_target_routing_policy: 'strict_preferred_endpoint',
      memory_ranking_policy: 'workspace_first',
      tool_routing_overrides: {
        'utility.echo': {
          preferred_target_endpoint_ids: ['desktop.study.executor'],
          tool_target_routing_policy: 'strict_preferred_endpoint',
        },
      },
    })

    expect(workspace.workspace_id).toBe('study')
    expect(workspace.default_execution_target).toBe('workspace_any_endpoint')
    expect(workspace.tool_policy).toBe('allowlist')
    expect(workspace.allowed_tool_ids).toEqual(['utility.echo'])
    expect(workspace.preferred_target_endpoint_ids).toEqual(['desktop.study.executor'])
    expect(workspace.preferred_endpoint_provider_types).toEqual(['desktop'])
    expect(workspace.tool_target_routing_policy).toBe('strict_preferred_endpoint')
    expect(workspace.preferred_source_profiles).toEqual(['study_materials', 'workspace_local'])
    expect(workspace.memory_ranking_policy).toBe('workspace_first')
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/desktop/workspaces/study',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          base_mode: 'danxi',
          default_execution_target: 'workspace_any_endpoint',
          tool_policy: 'allowlist',
          allowed_tool_ids: ['utility.echo'],
          preferred_target_endpoint_ids: ['desktop.study.executor'],
          preferred_endpoint_provider_types: ['desktop'],
          preferred_source_profiles: ['study_materials', 'workspace_local'],
          tool_target_routing_policy: 'strict_preferred_endpoint',
          memory_ranking_policy: 'workspace_first',
          tool_routing_overrides: {
            'utility.echo': {
              preferred_target_endpoint_ids: ['desktop.study.executor'],
              tool_target_routing_policy: 'strict_preferred_endpoint',
            },
          },
        }),
      }),
    )
  })

  it('uses readable thread bootstrap errors', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response('', { status: 404 }))
      .mockResolvedValueOnce(new Response('', { status: 404 })) as typeof fetch

    await expect(
      ensureDefaultRuntimeThread('http://127.0.0.1:8000', {
        workspace_id: 'personal',
        default_key: 'frontend.default',
      }),
    ).rejects.toThrow('加载默认会话线程失败（HTTP 404）')

    await expect(
      listRuntimeThreads('http://127.0.0.1:8000', { workspace_id: 'personal' }),
    ).rejects.toThrow('加载会话线程列表失败（HTTP 404）')
  })

  it('deletes runtime threads through desktop runtime API', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          thread_id: 'thr_1',
          deleted: true,
          status: 'deleted',
          reason: 'deleted',
          default_thread: false,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as typeof fetch

    const result = await deleteRuntimeThread('http://127.0.0.1:8000', 'thr_1')

    expect(result.deleted).toBe(true)
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/desktop/threads/thr_1',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('logs into Danxi session and patches WebVPN cookie through runtime API', async () => {
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
    ).rejects.toThrow('旦夕加密凭证传输仅在桌面端可用。')

    await expect(
      updateDanxiWebvpnCookie('http://127.0.0.1:8000', {
        cookie_header: 'vpn=ok',
      }),
    ).rejects.toThrow('旦夕加密凭证传输仅在桌面端可用。')

    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('loads Danxi session status and posts via runtime API', async () => {
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
    const created = await createDanxiReply('http://127.0.0.1:8000', 101, { content: '我也遇到这个问题' })
    const updated = await updateDanxiReply('http://127.0.0.1:8000', 9001, { content: '已解决，谢谢' })
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
            label: '工作区与本地知识',
            description: '优先使用本地文件、记忆和私有工作区知识。',
            official_only: false,
            default_freshness: 'workspace',
          },
          {
            profile_name: 'policy_global',
            label: '国际政策',
            description: '中国以外的政府与监管机构资料。',
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

    const { downloadRuntimeAttachmentContent: downloadAttachment } = await import('./runtimeApi')
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

    const { downloadRuntimeAttachmentContent: downloadAttachment } = await import('./runtimeApi')
    await downloadAttachment('https://minio.example.com/presigned/att_1')

    const [, init] = vi.mocked(globalThis.fetch).mock.calls[0] || []
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBeNull()
  })

  it('creates websocket urls against the desktop endpoint bridge', async () => {
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

    const { createEndpointWsUrl: createWsUrl } = await import('./runtimeApi')
    const url = await createWsUrl('http://127.0.0.1:38951', 'thr_1', {
      endpointId: 'desktop-app',
      sessionId: 'sess_1',
      workspaceId: 'personal',
      endpointType: 'electron',
      displayName: 'Desktop App',
    })

    expect(url).toBe(
      'ws://127.0.0.1:38951/desktop/ws?thread_id=thr_1&endpoint_id=desktop-app&session_id=sess_1&workspace_id=personal&endpoint_type=electron&display_name=Desktop+App&access_token=local-bridge-token',
    )
  })

  it('prefers direct browser download for presigned attachment tickets', () => {
    const plan = resolveRuntimeAttachmentDownloadPlan({
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
    const plan = resolveRuntimeAttachmentDownloadPlan({
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
    const plan = resolveRuntimeAttachmentDownloadPlan({
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
