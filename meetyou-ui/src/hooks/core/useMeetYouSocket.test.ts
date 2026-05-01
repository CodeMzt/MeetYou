import { describe, expect, it } from 'vitest'
import { buildEndpointHandshakeFrames, buildUiEndpointId } from './useMeetYouSocket'
import type { EndpointContext } from './useEndpointContext'

function context(): EndpointContext {
  return {
    workspace: {
      workspace_id: 'desktop-main',
      title: 'Desktop',
      status: 'active',
      base_mode: 'general',
      description: '',
      prompt_overlay: '',
      default_execution_target: 'endpoint',
      tool_policy: 'balanced',
      allowed_tool_ids: [],
      preferred_target_endpoint_ids: [],
      preferred_endpoint_provider_types: [],
      preferred_source_profiles: [],
      tool_target_routing_policy: 'balanced',
      memory_ranking_policy: 'workspace_first',
      tool_routing_overrides: {},
    },
    threadId: 'thr_123',
    session: {
      session_id: 'sess_123',
      thread_id: 'thr_123',
      active_workspace_id: 'desktop-main',
      workspace_id: 'desktop-main',
      endpoint_id: 'desktop-app',
      status: 'active',
    },
    endpointId: 'Desktop App',
  }
}

describe('useMeetYouSocket endpoint frames', () => {
  it('builds V4 endpoint hello and thread subscription frames for the UI socket', () => {
    const endpointContext = context()
    const frames = buildEndpointHandshakeFrames(endpointContext)

    expect(buildUiEndpointId(endpointContext)).toBe('desktop.desktop-app.ui')
    expect(frames[0]).toMatchObject({
      schema: 'meetyou.endpoint.ws.v4',
      type: 'endpoint.hello',
      payload: {
        provider: {
          provider_type: 'desktop',
          provider_id: 'desktop-app',
        },
        protocol: {
          schema: 'meetyou.endpoint.ws.v4',
          version: 4,
          supported_schemas: ['meetyou.endpoint.ws.v4'],
          supported_versions: [4],
        },
        endpoints: [
          {
            endpoint_id: 'desktop.desktop-app.ui',
            endpoint_type: 'desktop_ui',
            roles: ['input', 'output'],
            workspace_ids: ['desktop-main'],
          },
        ],
      },
    })
    expect(frames[1]).toMatchObject({
      schema: 'meetyou.endpoint.ws.v4',
      type: 'subscription.start',
      endpoint_id: 'desktop.desktop-app.ui',
      payload: {
        target_type: 'thread',
        target_id: 'thr_123',
        last_seen_event_seq: 0,
      },
    })
  })
})
