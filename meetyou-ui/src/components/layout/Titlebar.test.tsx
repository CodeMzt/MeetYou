import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import Titlebar from './Titlebar'

describe('Titlebar', () => {
  it('keeps original top tools available when compact controls are present', () => {
    const markup = renderToStaticMarkup(
      <Titlebar
        connectionState="connected"
        workspace={{
          workspace_id: 'personal',
          title: '个人',
          status: 'active',
          base_mode: 'general',
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
        }}
        desktopToolsAvailable
        isPinned
        onTogglePin={vi.fn()}
      />,
    )

    expect(markup).toContain('data-titlebar-tools-trigger="true"')
    for (const key of ['pin', 'dashboard', 'workspace', 'danxi', 'stats', 'devtools', 'settings']) {
      expect(markup).toContain(`data-titlebar-tool="${key}"`)
    }
  })
})
