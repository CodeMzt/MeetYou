import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ClientWorkspace } from '../../types'
import WorkspaceGovernanceEditor from './WorkspaceGovernanceEditor'

const workspace: ClientWorkspace = {
  workspace_id: 'study',
  title: '学习',
  status: 'active',
  base_mode: 'study',
  description: '学习资料、笔记与复盘工作空间。',
  prompt_overlay: '',
  default_execution_target: 'core_only',
  tool_policy: 'allow_all',
  allowed_tool_ids: [],
  preferred_target_client_ids: [],
  preferred_target_client_types: [],
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

    expect(markup).toContain('来源偏好与记忆排序')
    expect(markup).toContain('Base Mode')
    expect(markup).toContain('学习资料')
    expect(markup).toContain('工作区/本地知识')
    expect(markup).toContain('当前工作区优先')
  })
})
