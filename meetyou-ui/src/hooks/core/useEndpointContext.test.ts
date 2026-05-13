import { describe, expect, it, vi } from 'vitest'
import type { AvailableEndpoint, RuntimeProject } from '../../types'
import {
  chooseDesktopToolEndpoint,
  DESKTOP_TOOL_ENDPOINT_REFRESH_INTERVAL_MS,
  mergeRuntimeProjectList,
  resolveInitializedEndpointContext,
  runtimeThreadDeleteErrorMessage,
  resolveDesktopToolEndpointId,
} from './useEndpointContext'
import type { EndpointContext } from './useEndpointContext'

function project(project_id: string, title: string): RuntimeProject {
  return {
    project_id,
    workspace_id: 'personal',
    title,
    description: '',
    instructions: '',
    status: 'active',
    memory_scope: {},
    metadata: {},
    created_at: '2026-05-09T00:00:00Z',
    updated_at: '2026-05-09T00:00:00Z',
  }
}

describe('useEndpointContext helpers', () => {
  it('awaits pending initialization before user thread actions choose a workspace', async () => {
    const currentContext = null
    const initializedContext: EndpointContext = {
      workspace: {
        workspace_id: 'personal',
        title: 'Personal',
        base_mode: 'general',
        status: 'active',
        description: '',
        prompt_overlay: '',
        default_execution_target: '',
        tool_policy: '',
        allowed_tool_ids: [],
        preferred_target_endpoint_ids: [],
        preferred_endpoint_provider_types: [],
        preferred_source_profiles: [],
        tool_target_routing_policy: '',
        memory_ranking_policy: '',
        tool_routing_overrides: {},
      },
      threadId: 'thr_default',
      session: {
        session_id: 'sess_default',
        thread_id: 'thr_default',
        active_workspace_id: 'personal',
        workspace_id: 'personal',
        endpoint_id: 'desktop-app',
        status: 'active',
      },
      endpointId: 'desktop-app',
    }

    await expect(resolveInitializedEndpointContext(currentContext, Promise.resolve(initializedContext))).resolves.toBe(initializedContext)
    await expect(resolveInitializedEndpointContext(initializedContext, Promise.resolve(null as never))).resolves.toBe(initializedContext)
  })

  it('picks the online desktop tool endpoint for the current workspace', () => {
    const availableEndpoints: AvailableEndpoint[] = [
      {
        endpoint_id: 'desktop-other',
        endpoint_type: 'desktop_executor',
        provider_type: 'desktop',
        display_name: 'Other Desktop',
        transport_profile: 'desktop_wss',
        status: 'online',
        workspace_ids: ['personal'],
        available_tools: [],
        executable_tools: ['file.read'],
        membership_role: 'member',
        enabled: true,
      },
      {
        endpoint_id: 'desktop-main-endpoint',
        endpoint_type: 'desktop_executor',
        provider_type: 'desktop',
        display_name: 'Desktop Main Endpoint',
        transport_profile: 'desktop_wss',
        status: 'online',
        workspace_ids: ['personal', 'desktop-main'],
        available_tools: [],
        executable_tools: ['file.read', 'shell.exec'],
        membership_role: 'member',
        enabled: true,
      },
    ]

    expect(chooseDesktopToolEndpoint(availableEndpoints, 'desktop-main', 'desktop-app')).toBe('desktop-main-endpoint')
    expect(DESKTOP_TOOL_ENDPOINT_REFRESH_INTERVAL_MS).toBe(10000)
  })

  it('reloads available endpoints and returns the newly available desktop tool endpoint', async () => {
    const loadAvailableEndpoints = vi.fn().mockResolvedValue([
      {
        endpoint_id: 'desktop-main-endpoint',
        endpoint_type: 'desktop_executor',
        provider_type: 'desktop',
        display_name: 'Desktop Main Endpoint',
        transport_profile: 'desktop_wss',
        status: 'online',
        workspace_ids: ['personal'],
        available_tools: [],
        executable_tools: ['file.read'],
        membership_role: 'member',
        enabled: true,
      },
    ] satisfies AvailableEndpoint[])

    await expect(
      resolveDesktopToolEndpointId(loadAvailableEndpoints, 'http://127.0.0.1:8000', 'personal', 'desktop-app'),
    ).resolves.toBe('desktop-main-endpoint')
    expect(loadAvailableEndpoints).toHaveBeenCalledWith('http://127.0.0.1:8000', 'personal')
  })

  it('maps thread delete business reasons to user-facing errors', () => {
    expect(runtimeThreadDeleteErrorMessage('default_thread')).toBe('这是受保护的默认会话，未被删除。')
    expect(runtimeThreadDeleteErrorMessage('already_deleted')).toBe('')
    expect(runtimeThreadDeleteErrorMessage('unknown')).toBe('删除会话线程失败。')
  })

  it('merges updated project settings into the remembered project list', () => {
    const updated = {
      ...project('prj_1', '论文项目'),
      description: '跟踪材料和产物',
      instructions: '优先使用项目源。',
    }

    expect(mergeRuntimeProjectList([project('prj_1', '旧名称'), project('prj_2', '课程')], updated)).toEqual([
      updated,
      project('prj_2', '课程'),
    ])
    expect(mergeRuntimeProjectList([], updated)).toEqual([updated])
  })
})
