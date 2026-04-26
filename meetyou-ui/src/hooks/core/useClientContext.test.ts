import { describe, expect, it, vi } from 'vitest'
import type { ClientAvailableClient } from '../../types'
import {
  chooseDesktopToolClient,
  DESKTOP_TOOL_CLIENT_REFRESH_INTERVAL_MS,
  resolveDesktopToolClientId,
} from './useClientContext'

describe('useClientContext helpers', () => {
  it('picks the online desktop tool client for the current workspace', () => {
    const availableClients: ClientAvailableClient[] = [
      {
        client_id: 'desktop-other',
        client_type: 'desktop',
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
        client_id: 'desktop-main-client',
        client_type: 'desktop',
        display_name: 'Desktop Main Client',
        transport_profile: 'desktop_wss',
        status: 'online',
        workspace_ids: ['personal', 'desktop-main'],
        available_tools: [],
        executable_tools: ['file.read', 'shell.exec'],
        membership_role: 'member',
        enabled: true,
      },
    ]

    expect(chooseDesktopToolClient(availableClients, 'desktop-main', 'desktop-app')).toBe('desktop-main-client')
    expect(DESKTOP_TOOL_CLIENT_REFRESH_INTERVAL_MS).toBe(10000)
  })

  it('reloads available clients and returns the newly available desktop tool client', async () => {
    const loadAvailableClients = vi.fn().mockResolvedValue([
      {
        client_id: 'desktop-main-client',
        client_type: 'desktop',
        display_name: 'Desktop Main Client',
        transport_profile: 'desktop_wss',
        status: 'online',
        workspace_ids: ['personal'],
        available_tools: [],
        executable_tools: ['file.read'],
        membership_role: 'member',
        enabled: true,
      },
    ] satisfies ClientAvailableClient[])

    await expect(
      resolveDesktopToolClientId(loadAvailableClients, 'http://127.0.0.1:8000', 'personal', 'desktop-app'),
    ).resolves.toBe('desktop-main-client')
    expect(loadAvailableClients).toHaveBeenCalledWith('http://127.0.0.1:8000', 'personal')
  })
})
