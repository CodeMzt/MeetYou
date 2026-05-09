import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  clearDesktopMemory,
  createRuntimeResearchTask,
  createRuntimeProject,
  createRuntimeProjectSourceFromMessage,
  createRuntimeThreadCheckpoint,
  createRuntimeThread,
  createDanxiReply,
  checkoutRuntimeThreadCheckpoint,
  deleteRuntimeThread,
  deleteDesktopMemoryRecord,
  deleteDanxiReply,
  downloadRuntimeArtifact,
  ensureDefaultRuntimeThread,
  editRetryRuntimeMessage,
  fetchRuntimeUsageSnapshot,
  getDanxiPostSummary,
  getDanxiProfile,
  resolveDanxiMessageTarget,
  getDanxiSessionStatus,
  addEndpointWorkspace,
  archiveOperatorWorkspace,
  createOperatorWorkspace,
  listDanxiFloors,
  listDanxiPosts,
  listOperatorSourceProfiles,
  listWorkspaceTopology,
  listRuntimeProjects,
  listRuntimeResearchTasks,
  listRuntimeThreadBranches,
  listRuntimeThreadCheckpoints,
  listRuntimeThreads,
  loginDanxiSession,
  removeAddressWorkspace,
  restoreOperatorWorkspace,
  restoreRuntimeThreadCheckpoint,
  patchRuntimeResearchTask,
  setAddressPrimaryWorkspace,
  updateDanxiReply,
  updateDanxiWebvpnCookie,
  updateOperatorWorkspaceGovernance,
  updateDesktopMemoryRecordStatus,
} from './runtimeApi'
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

  it('loads workspace topology and manages workspace lifecycle through desktop operator bridge', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            workspaces: [
              {
                workspace_id: 'personal',
                title: 'Personal',
                status: 'active',
                base_mode: 'general',
                description: '',
                endpoint_count: 1,
                online_endpoint_count: 1,
              },
            ],
            endpoints: [
              {
                endpoint_id: 'desktop.main.executor',
                display_name: 'Desktop',
                endpoint_type: 'desktop_executor',
                provider_type: 'desktop',
                transport_type: 'websocket',
                status: 'online',
                connected: true,
                connection_count: 1,
                workspace_ids: ['personal'],
                primary_workspace_id: 'personal',
                provider_declared_workspace_ids: ['personal'],
                capability_count: 1,
                executable_tools: ['shell.exec'],
                labels: [],
                last_seen_at: '2026-05-05T00:00:00Z',
                core_owned: false,
                memberships: [{ workspace_id: 'personal', primary: true, role: 'member', enabled: true, source: 'core' }],
              },
            ],
            addresses: [],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            workspace_id: 'study',
            title: 'Study',
            status: 'active',
            base_mode: 'general',
            description: '',
            prompt_overlay: '',
            default_execution_target: 'core.local',
            tool_policy: 'allow_all',
            allowed_tool_ids: [],
            preferred_target_endpoint_ids: [],
            preferred_endpoint_provider_types: [],
            preferred_source_profiles: [],
            tool_target_routing_policy: 'balanced',
            memory_ranking_policy: 'workspace_first',
            tool_routing_overrides: {},
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            workspace_id: 'study',
            title: 'Study',
            status: 'archived',
            base_mode: 'general',
            description: '',
            prompt_overlay: '',
            default_execution_target: 'core.local',
            tool_policy: 'allow_all',
            allowed_tool_ids: [],
            preferred_target_endpoint_ids: [],
            preferred_endpoint_provider_types: [],
            preferred_source_profiles: [],
            tool_target_routing_policy: 'balanced',
            memory_ranking_policy: 'workspace_first',
            tool_routing_overrides: {},
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            workspace_id: 'study',
            title: 'Study',
            status: 'active',
            base_mode: 'general',
            description: '',
            prompt_overlay: '',
            default_execution_target: 'core.local',
            tool_policy: 'allow_all',
            allowed_tool_ids: [],
            preferred_target_endpoint_ids: [],
            preferred_endpoint_provider_types: [],
            preferred_source_profiles: [],
            tool_target_routing_policy: 'balanced',
            memory_ranking_policy: 'workspace_first',
            tool_routing_overrides: {},
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ) as typeof fetch

    const topology = await listWorkspaceTopology('http://127.0.0.1:8000', true)
    const created = await createOperatorWorkspace('http://127.0.0.1:8000', {
      workspace_id: 'study',
      title: 'Study',
    })
    const archived = await archiveOperatorWorkspace('http://127.0.0.1:8000', 'study')
    const restored = await restoreOperatorWorkspace('http://127.0.0.1:8000', 'study')

    expect(topology.endpoints[0]?.primary_workspace_id).toBe('personal')
    expect(created.workspace_id).toBe('study')
    expect(archived.status).toBe('archived')
    expect(restored.status).toBe('active')
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/desktop/workspace-topology?include_archived=true',
      expect.anything(),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/desktop/workspaces',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ workspace_id: 'study', title: 'Study' }),
      }),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      3,
      'http://127.0.0.1:8000/desktop/workspaces/study',
      expect.objectContaining({ method: 'DELETE' }),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      4,
      'http://127.0.0.1:8000/desktop/workspaces/study/restore',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('mutates endpoint and address workspace memberships through desktop operator bridge', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: true,
            target_type: 'endpoint',
            target_id: 'desktop.main.executor',
            workspace_ids: ['study', 'personal'],
            primary_workspace_id: 'study',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: true,
            target_type: 'address',
            target_id: 'addr.desktop.direct.self',
            workspace_ids: ['study', 'personal'],
            primary_workspace_id: 'study',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: true,
            target_type: 'address',
            target_id: 'addr.desktop.direct.self',
            workspace_ids: ['study'],
            primary_workspace_id: 'study',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ) as typeof fetch

    const endpoint = await addEndpointWorkspace('http://127.0.0.1:8000', 'desktop.main.executor', {
      workspace_id: 'study',
      make_primary: true,
    })
    const address = await setAddressPrimaryWorkspace('http://127.0.0.1:8000', 'addr.desktop.direct.self', 'study')
    const removed = await removeAddressWorkspace('http://127.0.0.1:8000', 'addr.desktop.direct.self', 'personal')

    expect(endpoint.primary_workspace_id).toBe('study')
    expect(address.target_type).toBe('address')
    expect(removed.workspace_ids).toEqual(['study'])
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/desktop/endpoints/desktop.main.executor/workspaces',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ workspace_id: 'study', make_primary: true }),
      }),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/desktop/addresses/addr.desktop.direct.self/primary-workspace',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ workspace_id: 'study' }),
      }),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      3,
      'http://127.0.0.1:8000/desktop/addresses/addr.desktop.direct.self/workspaces/personal',
      expect.objectContaining({ method: 'DELETE' }),
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

  it('passes project ids through thread and project runtime APIs', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            thread_id: 'thr_project',
            home_workspace_id: 'personal',
            workspace_id: 'personal',
            project_id: 'prj_1',
            title: 'Project Chat',
            status: 'active',
            summary: '',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              project_id: 'prj_1',
              workspace_id: 'personal',
              title: 'Research Project',
              description: '',
              instructions: '',
              status: 'active',
              memory_scope: {},
              metadata: {},
              created_at: '2026-05-09T00:00:00Z',
              updated_at: '2026-05-09T00:00:00Z',
            },
          ]),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            project_id: 'prj_2',
            workspace_id: 'personal',
            title: 'New Project',
            description: '',
            instructions: '',
            status: 'active',
            memory_scope: {},
            metadata: {},
            created_at: '2026-05-09T00:00:00Z',
            updated_at: '2026-05-09T00:00:00Z',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ) as typeof fetch

    const thread = await createRuntimeThread('http://127.0.0.1:8000', {
      workspace_id: 'personal',
      title: 'Project Chat',
      mode: 'research',
      project_id: 'prj_1',
    })
    const projects = await listRuntimeProjects('http://127.0.0.1:8000', {
      workspace_id: 'personal',
      limit: 200,
    })
    const project = await createRuntimeProject('http://127.0.0.1:8000', {
      workspace_id: 'personal',
      title: 'New Project',
    })

    expect(thread.project_id).toBe('prj_1')
    expect(projects[0]?.project_id).toBe('prj_1')
    expect(project.project_id).toBe('prj_2')
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/desktop/threads',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          workspace_id: 'personal',
          title: 'Project Chat',
          mode: 'research',
          project_id: 'prj_1',
        }),
      }),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/desktop/projects?workspace_id=personal&limit=200',
      expect.anything(),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      3,
      'http://127.0.0.1:8000/desktop/projects',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          workspace_id: 'personal',
          title: 'New Project',
        }),
      }),
    )
  })

  it('saves message snapshots and submits edit-retry through desktop runtime APIs', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            source_id: 'src_1',
            project_id: 'prj_1',
            source_type: 'message_snapshot',
            title: 'Saved message',
            content: 'hello',
            content_type: 'text',
            checksum: 'sha256:abc',
            status: 'active',
            metadata: { message_id: 'msg_1' },
            created_at: '2026-05-09T00:00:00Z',
            updated_at: '2026-05-09T00:00:00Z',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            branch: {
              branch_id: 'br_1',
              thread_id: 'thr_1',
              parent_branch_id: 'br_parent',
              title: 'Retry branch',
              status: 'active',
              current_leaf_message_id: 'msg_2',
              metadata: {},
              created_at: '2026-05-09T00:00:00Z',
              updated_at: '2026-05-09T00:00:00Z',
            },
            message: {
              message_id: 'msg_2',
              thread_id: 'thr_1',
              session_id: 'sess_1',
              active_workspace_id: 'personal',
              workspace_id: 'personal',
              endpoint_id: 'desktop-app',
              role: 'user',
              content: 'edited hello',
              status: 'completed',
              channel: 'message',
              created_at: '2026-05-09T00:00:01Z',
            },
            replay_status: 'queued',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ) as typeof fetch

    const source = await createRuntimeProjectSourceFromMessage('http://127.0.0.1:8000', 'prj_1', {
      message_id: 'msg_1',
      title: 'Saved message',
    })
    const retry = await editRetryRuntimeMessage('http://127.0.0.1:8000', 'msg_1', {
      content: 'edited hello',
      title: 'Retry branch',
    })

    expect(source.source_type).toBe('message_snapshot')
    expect(retry.replay_status).toBe('queued')
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/desktop/projects/prj_1/sources/from-message',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ message_id: 'msg_1', title: 'Saved message' }),
      }),
    )
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8000/desktop/messages/msg_1/edit-retry',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ content: 'edited hello', title: 'Retry branch' }),
      }),
    )
  })

  it('manages thread branches and checkpoints through desktop runtime APIs', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([{
            branch_id: 'br_1',
            thread_id: 'thr_1',
            parent_branch_id: '',
            title: 'Default',
            status: 'active',
            current_leaf_message_id: 'msg_1',
            metadata: {},
            created_at: '2026-05-09T00:00:00Z',
            updated_at: '2026-05-09T00:00:00Z',
          }]),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([{
            checkpoint_id: 'chk_1',
            thread_id: 'thr_1',
            branch_id: 'br_1',
            message_id: 'msg_1',
            checkpoint_type: 'manual',
            title: 'Checkpoint',
            state: {},
            status: 'active',
            metadata: {},
            created_at: '2026-05-09T00:00:00Z',
            updated_at: '2026-05-09T00:00:00Z',
          }]),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            checkpoint_id: 'chk_2',
            thread_id: 'thr_1',
            branch_id: 'br_1',
            message_id: 'msg_2',
            checkpoint_type: 'manual',
            title: 'Created',
            state: {},
            status: 'active',
            metadata: {},
            created_at: '2026-05-09T00:00:01Z',
            updated_at: '2026-05-09T00:00:01Z',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            checkpoint_id: 'chk_1',
            thread_id: 'thr_1',
            branch_id: 'br_1',
            message_id: 'msg_1',
            checkpoint_type: 'manual',
            title: 'Checkpoint',
            state: {},
            status: 'active',
            metadata: {},
            created_at: '2026-05-09T00:00:00Z',
            updated_at: '2026-05-09T00:00:02Z',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            branch_id: 'br_checkout',
            thread_id: 'thr_1',
            parent_branch_id: 'br_1',
            title: 'Checkout',
            status: 'active',
            current_leaf_message_id: 'msg_1',
            metadata: {},
            created_at: '2026-05-09T00:00:03Z',
            updated_at: '2026-05-09T00:00:03Z',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ) as typeof fetch

    const branches = await listRuntimeThreadBranches('http://127.0.0.1:8000', 'thr_1')
    const checkpoints = await listRuntimeThreadCheckpoints('http://127.0.0.1:8000', 'thr_1')
    const created = await createRuntimeThreadCheckpoint('http://127.0.0.1:8000', 'thr_1', { title: 'Created' })
    const restored = await restoreRuntimeThreadCheckpoint('http://127.0.0.1:8000', 'thr_1', 'chk_1')
    const checkout = await checkoutRuntimeThreadCheckpoint('http://127.0.0.1:8000', 'thr_1', 'chk_1', { title: 'Checkout' })

    expect(branches[0].branch_id).toBe('br_1')
    expect(checkpoints[0].checkpoint_id).toBe('chk_1')
    expect(created.title).toBe('Created')
    expect(restored.message_id).toBe('msg_1')
    expect(checkout.branch_id).toBe('br_checkout')
    expect(globalThis.fetch).toHaveBeenNthCalledWith(1, 'http://127.0.0.1:8000/desktop/threads/thr_1/branches', expect.any(Object))
    expect(globalThis.fetch).toHaveBeenNthCalledWith(2, 'http://127.0.0.1:8000/desktop/threads/thr_1/checkpoints', expect.any(Object))
    expect(globalThis.fetch).toHaveBeenNthCalledWith(3, 'http://127.0.0.1:8000/desktop/threads/thr_1/checkpoints', expect.objectContaining({ method: 'POST' }))
    expect(globalThis.fetch).toHaveBeenNthCalledWith(4, 'http://127.0.0.1:8000/desktop/threads/thr_1/checkpoints/chk_1/restore', expect.objectContaining({ method: 'POST' }))
    expect(globalThis.fetch).toHaveBeenNthCalledWith(5, 'http://127.0.0.1:8000/desktop/threads/thr_1/checkpoints/chk_1/checkout', expect.objectContaining({ method: 'POST' }))
  })

  it('manages research tasks and artifact downloads through desktop runtime APIs', async () => {
    const task = {
      research_task_id: 'res_1',
      project_id: 'prj_1',
      thread_id: 'thr_1',
      artifact_id: 'art_1',
      topic: 'Deep research',
      status: 'planned',
      plan: { steps: [] },
      source_policy: {},
      evidence_ledger: [],
      output_format: 'markdown',
      summary: '',
      artifact: null,
      metadata: {},
      created_at: '2026-05-09T00:00:00Z',
      updated_at: '2026-05-09T00:00:00Z',
    }
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([task]), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...task, research_task_id: 'res_2' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...task, status: 'running' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response('report body', { status: 200, headers: { 'Content-Type': 'text/markdown' } })) as typeof fetch

    const tasks = await listRuntimeResearchTasks('http://127.0.0.1:8000', { project_id: 'prj_1', limit: 50 })
    const created = await createRuntimeResearchTask('http://127.0.0.1:8000', { topic: 'Deep research', project_id: 'prj_1' })
    const patched = await patchRuntimeResearchTask('http://127.0.0.1:8000', 'res_1', { action: 'start' })
    const artifact = await downloadRuntimeArtifact('http://127.0.0.1:8000', 'art_1')

    expect(tasks[0].research_task_id).toBe('res_1')
    expect(created.research_task_id).toBe('res_2')
    expect(patched.status).toBe('running')
    expect(await artifact.text()).toBe('report body')
    expect(globalThis.fetch).toHaveBeenNthCalledWith(1, 'http://127.0.0.1:8000/desktop/research-tasks?project_id=prj_1&limit=50', expect.any(Object))
    expect(globalThis.fetch).toHaveBeenNthCalledWith(2, 'http://127.0.0.1:8000/desktop/research-tasks', expect.objectContaining({ method: 'POST' }))
    expect(globalThis.fetch).toHaveBeenNthCalledWith(3, 'http://127.0.0.1:8000/desktop/research-tasks/res_1', expect.objectContaining({ method: 'PATCH' }))
    expect(globalThis.fetch).toHaveBeenNthCalledWith(4, 'http://127.0.0.1:8000/desktop/artifacts/art_1/download', expect.any(Object))
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

  it('passes the force flag when deleting protected runtime threads', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          thread_id: 'thr_default_old',
          deleted: true,
          status: 'deleted',
          reason: 'deleted',
          default_thread: true,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as typeof fetch

    const result = await deleteRuntimeThread('http://127.0.0.1:8000', 'thr_default_old', { force: true })

    expect(result.default_thread).toBe(true)
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/desktop/threads/thr_default_old?force=true',
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

  it('passes Danxi floor pagination through runtime API', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          hole_id: 218579,
          offset: 3,
          size: 3,
          next_offset: 6,
          has_more: true,
          count: 3,
          items: [{ floor_id: 2035489 }, { floor_id: 2035491 }, { floor_id: 2035496 }],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as typeof fetch

    const floors = await listDanxiFloors('http://127.0.0.1:8000', 218579, {
      offset: 3,
      size: 3,
    })

    expect(floors.next_offset).toBe(6)
    expect(floors.items[0]?.floor_id).toBe(2035489)
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/desktop/danxi/posts/218579/floors?offset=3&size=3',
      expect.anything(),
    )
  })

  it('passes Danxi post time cursors through runtime API', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          scope: 'homepage',
          order: 'time_updated',
          offset: '2026-05-07T00:10:00Z',
          next_offset: '2026-05-07T00:01:00Z',
          has_more: true,
          count: 1,
          items: [{ hole_id: 642291 }],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as typeof fetch

    const posts = await listDanxiPosts('http://127.0.0.1:8000', {
      offset: '2026-05-07T00:10:00Z',
      length: 10,
      order: 'time_updated',
    })

    expect(posts.next_offset).toBe('2026-05-07T00:01:00Z')
    const calledUrl = vi.mocked(globalThis.fetch).mock.calls[0]?.[0]
    expect(String(calledUrl)).toContain('/desktop/danxi/posts?')
    expect(String(calledUrl)).toContain('offset=2026-05-07T00%3A10%3A00Z')
    expect(String(calledUrl)).toContain('order=time_updated')
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

})
