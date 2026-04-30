import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { RuntimeWorkspace, OperationView } from '../../types'
import WorkspacePanel from './WorkspacePanel'

const workspace: RuntimeWorkspace = {
  workspace_id: 'personal',
  title: 'Personal',
  status: 'active',
  base_mode: 'general',
  description: 'Personal workspace for everyday use.',
  prompt_overlay: '',
  default_execution_target: 'core.local',
  tool_policy: 'allow_all',
  allowed_tool_ids: [],
  preferred_target_endpoint_ids: ['desktop.personal.executor'],
  preferred_endpoint_provider_types: ['desktop'],
  preferred_source_profiles: ['workspace_local'],
  tool_target_routing_policy: 'balanced',
  memory_ranking_policy: 'workspace_first',
  tool_routing_overrides: {},
}

describe('WorkspacePanel', () => {
  it('renders workspace metadata without legacy workflow context', () => {
    const markup = renderToStaticMarkup(
      <WorkspacePanel
        workspace={workspace}
        connectionState="connected"
        desktopToolsAvailable={false}
        operations={[] as OperationView[]}
        approvalDisplay={null}
        pendingHumanInput={null}
      />,
    )

    expect(markup).toContain('当前工作区')
    expect(markup).toContain('本地工具')
    expect(markup).toContain('运行中操作')
    expect(markup).toContain('工作区/本地知识')
    expect(markup).toContain('偏好端点：1')
    expect(markup).toContain('Provider 偏好：1')
    expect(markup).toContain('路由策略：均衡')
    expect(markup).not.toContain('固定流程')
  })

  it('renders approval actions for pending approval-required operations', () => {
    const markup = renderToStaticMarkup(
      <WorkspacePanel
        workspace={workspace}
        connectionState="connected"
        desktopToolsAvailable={false}
        operations={[
          {
            operation_id: 'op_approval_1',
            thread_id: 'thread_1',
            workspace_id: 'personal',
            status: 'running',
            title: 'Run shell command',
            operation_type: 'tool.call',
            execution_target: 'core.local',
            target_endpoint_id: '',
            tool_key: 'shell.exec',
            tool_id: 'endpoint.desktop.desktop-main.executor.shell.exec',
            call_id: 'call_1',
            phase: 'waiting_approval',
            detail: '',
            result: {},
            error: {},
            summary: '',
            tone: 'pending',
            isBlocking: true,
            approval_required: true,
            approval_status: 'pending',
            approval_id: 'approval_1',
            attachments: [],
          },
        ] as OperationView[]}
        approvalDisplay={null}
        pendingHumanInput={null}
      />,
    )

    expect(markup).toContain('允许')
    expect(markup).toContain('拒绝')
  })
})
