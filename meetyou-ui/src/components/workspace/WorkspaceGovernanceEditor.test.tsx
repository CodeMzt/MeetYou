import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ClientWorkspace } from '../../types'
import WorkspaceGovernanceEditor from './WorkspaceGovernanceEditor'

const workspace: ClientWorkspace = {
  workspace_id: 'study',
  title: 'Study',
  status: 'active',
  base_mode: 'study',
  description: 'Study workspace for focused learning.',
  prompt_overlay: '',
  default_execution_target: 'core_only',
  tool_policy: 'allow_all',
  allowed_tool_ids: [],
  preferred_target_endpoint_ids: [],
  preferred_endpoint_provider_types: [],
  preferred_source_profiles: ['study_materials', 'workspace_local'],
  tool_target_routing_policy: 'balanced',
  memory_ranking_policy: 'workspace_first',
  tool_routing_overrides: {},
}

describe('WorkspaceGovernanceEditor', () => {
  it('renders editable governance summary for workspace source profiles', () => {
    const markup = renderToStaticMarkup(
      <WorkspaceGovernanceEditor
        baseUrl="http://127.0.0.1:8000"
        workspace={workspace}
        onWorkspaceSaved={() => {}}
      />,
    )

    expect(markup).toContain('Preferred Source Profiles')
    expect(markup).toContain('Base Mode')
    expect(markup).toContain('工作区：Study')
    expect(markup).toContain('Study')
    expect(markup).toContain('Memory Ranking Policy')
  })
})
