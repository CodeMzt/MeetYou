import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { RuntimeWorkspace } from '../../types'
import WorkspaceGovernanceEditor from './WorkspaceGovernanceEditor'

const workspace: RuntimeWorkspace = {
  workspace_id: 'study',
  title: 'Study',
  status: 'active',
  base_mode: 'general',
  description: 'Study workspace for focused learning.',
  prompt_overlay: '',
  default_execution_target: 'core.local',
  tool_policy: 'allow_all',
  allowed_tool_ids: ['utility.echo'],
  preferred_target_endpoint_ids: ['desktop.study.executor'],
  preferred_endpoint_provider_types: ['desktop'],
  preferred_source_profiles: ['study_materials', 'workspace_local'],
  tool_target_routing_policy: 'balanced',
  memory_ranking_policy: 'workspace_first',
  tool_routing_overrides: {
    'utility.echo': {
      preferred_target_endpoint_ids: ['desktop.study.executor'],
      tool_target_routing_policy: 'strict_preferred_endpoint',
    },
  },
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

    expect(markup).toContain('偏好来源')
    expect(markup).toContain('默认模式')
    expect(markup).toContain('工作区：Study')
    expect(markup).toContain('Study')
    expect(markup).toContain('记忆排序')
    expect(markup).toContain('默认执行目标')
    expect(markup).toContain('工具策略')
    expect(markup).toContain('允许工具')
    expect(markup).toContain('偏好端点')
    expect(markup).toContain('Provider 偏好')
    expect(markup).toContain('工具路由覆盖')
    expect(markup).toContain('utility.echo')
  })
})
