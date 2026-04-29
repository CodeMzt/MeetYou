import { describe, expect, it, vi } from 'vitest'
import type { AvailableEndpoint } from '../../types'
import {
  chooseDesktopToolEndpoint,
  DESKTOP_TOOL_ENDPOINT_REFRESH_INTERVAL_MS,
  resolveDesktopToolEndpointId,
} from './useEndpointContext'

describe('useEndpointContext helpers', () => {
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
})
