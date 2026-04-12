import { describe, expect, it, vi } from 'vitest'
import type { ClientAvailableAgent } from '../../types'
import {
  chooseDesktopAgent,
  DESKTOP_AGENT_REFRESH_INTERVAL_MS,
  resolveDesktopAgentId,
} from './useClientContext'

describe('useClientContext helpers', () => {
  it('picks the online desktop agent for the current workspace and client', () => {
    const availableAgents: ClientAvailableAgent[] = [
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

    expect(chooseDesktopAgent(availableAgents, 'desktop-main', 'desktop-app')).toBe('desktop-main-agent')
    expect(DESKTOP_AGENT_REFRESH_INTERVAL_MS).toBe(10000)
  })

  it('reloads available agents and returns the newly available desktop agent', async () => {
    const loadAvailableAgents = vi.fn().mockResolvedValue([
      {
        agent_id: 'desktop-main-agent',
        agent_type: 'desktop',
        display_name: 'Desktop Main Agent',
        transport_profile: 'desktop_wss',
        status: 'online',
        owner_client_id: 'desktop-app',
        workspace_ids: ['personal'],
      },
    ] satisfies ClientAvailableAgent[])

    await expect(
      resolveDesktopAgentId(loadAvailableAgents, 'http://127.0.0.1:8000', 'personal', 'desktop-app'),
    ).resolves.toBe('desktop-main-agent')
    expect(loadAvailableAgents).toHaveBeenCalledWith('http://127.0.0.1:8000', 'personal')
  })
})
