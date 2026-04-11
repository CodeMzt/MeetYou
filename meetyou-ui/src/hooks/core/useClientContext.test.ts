import { describe, expect, it, vi } from 'vitest'
import type { ClientExecutionTarget } from '../../types'
import {
  chooseDesktopAgent,
  DESKTOP_AGENT_REFRESH_INTERVAL_MS,
  resolveDesktopAgentId,
} from './useClientContext'

describe('useClientContext helpers', () => {
  it('picks the online desktop agent for the current workspace and client', () => {
    const executionTargets: ClientExecutionTarget[] = [
      {
        agent_id: 'desktop-other',
        agent_type: 'desktop',
        display_name: 'Other Desktop',
        transport_profile: 'desktop_wss',
        status: 'online',
        owner_client_id: 'other-client',
        workspace_ids: ['personal'],
      },
      {
        agent_id: 'desktop-main-agent',
        agent_type: 'desktop',
        display_name: 'Desktop Main Agent',
        transport_profile: 'desktop_wss',
        status: 'online',
        owner_client_id: 'desktop-app',
        workspace_ids: ['personal', 'desktop-main'],
      },
    ]

    expect(chooseDesktopAgent(executionTargets, 'desktop-main', 'desktop-app')).toBe('desktop-main-agent')
    expect(DESKTOP_AGENT_REFRESH_INTERVAL_MS).toBe(10000)
  })

  it('reloads execution targets and returns the newly available desktop agent', async () => {
    const loadExecutionTargets = vi.fn().mockResolvedValue([
      {
        agent_id: 'desktop-main-agent',
        agent_type: 'desktop',
        display_name: 'Desktop Main Agent',
        transport_profile: 'desktop_wss',
        status: 'online',
        owner_client_id: 'desktop-app',
        workspace_ids: ['personal'],
      },
    ] satisfies ClientExecutionTarget[])

    await expect(
      resolveDesktopAgentId(loadExecutionTargets, 'http://127.0.0.1:8000', 'personal', 'desktop-app'),
    ).resolves.toBe('desktop-main-agent')
    expect(loadExecutionTargets).toHaveBeenCalledWith('http://127.0.0.1:8000', 'personal')
  })
})
