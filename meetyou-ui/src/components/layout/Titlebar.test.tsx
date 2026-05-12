import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import Titlebar from './Titlebar'

describe('Titlebar', () => {
  it('keeps the original top tools visible in the titlebar', () => {
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

    expect(markup).not.toContain('data-titlebar-tools-trigger="true"')
    for (const key of ['pin', 'dashboard', 'workspace', 'danxi', 'stats', 'devtools', 'settings']) {
      expect(markup).toContain(`data-titlebar-tool="${key}"`)
    }
    expect(markup).toContain('title="最小化"')
    expect(markup).toContain('title="关闭"')
  })

  it('keeps tools and window controls from shrinking behind the drag region', () => {
    const css = readFileSync(resolve(__dirname, 'Titlebar.module.css'), 'utf8')

    expect(css).toContain('flex: 0 1 0;')
    expect(css).toContain('max-width: 4px;')
    expect(css).toContain('flex: 0 0 auto;')
  })
})
