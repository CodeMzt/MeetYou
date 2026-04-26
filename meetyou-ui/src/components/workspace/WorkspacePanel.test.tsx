import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ClientThreadProcedureContext, ClientWorkspace, OperationView } from '../../types'
import WorkspacePanel from './WorkspacePanel'

const workspace: ClientWorkspace = {
  workspace_id: 'personal',
  title: '个人',
  status: 'active',
  base_mode: 'general',
  description: '默认个人工作空间。',
  prompt_overlay: '',
  default_execution_target: 'core_only',
  tool_policy: 'allow_all',
  allowed_tool_ids: [],
  preferred_target_client_ids: [],
  preferred_target_client_types: [],
  preferred_source_profiles: ['workspace_local'],
  tool_target_routing_policy: 'balanced',
  memory_ranking_policy: 'workspace_first',
  tool_routing_overrides: {},
}

const procedureContext: ClientThreadProcedureContext = {
  source: 'inferred',
  pinned_procedure: null,
  latest_inferred_procedure: {
    procedure_id: 'code_review',
    title: '代码审查',
    description: '围绕代码变更、风险与验证给出结构化审查。',
    applicable_modes: ['general'],
    recommended_tools: ['search_memory', 'summarize_text'],
    preferred_tool_key: 'search_memory',
    preferred_target_client_ids: [],
    preferred_target_client_types: [],
    tool_target_routing_policy: 'balanced',
    default_execution_target: 'core_only',
    risk_profile: 'read',
    status: 'active',
    prompt_overlay: '优先关注正确性。',
    recommended_source_profiles: ['workspace_local'],
    infer_keywords: ['review', 'patch'],
  },
  effective_procedure: {
    procedure_id: 'code_review',
    title: '代码审查',
    description: '围绕代码变更、风险与验证给出结构化审查。',
    applicable_modes: ['general'],
    recommended_tools: ['search_memory', 'summarize_text'],
    preferred_tool_key: 'search_memory',
    preferred_target_client_ids: [],
    preferred_target_client_types: [],
    tool_target_routing_policy: 'balanced',
    default_execution_target: 'core_only',
    risk_profile: 'read',
    status: 'active',
    prompt_overlay: '优先关注正确性。',
    recommended_source_profiles: ['workspace_local'],
    infer_keywords: ['review', 'patch'],
  },
  latest_inferred_reason: 'keywords:review,patch',
  latest_inferred_score: 7,
  latest_inferred_at: '2026-04-12T00:00:00Z',
}

describe('WorkspacePanel', () => {
  it('renders current procedure context as read-only workspace metadata', () => {
    const markup = renderToStaticMarkup(
      <WorkspacePanel
        workspace={workspace}
        procedureContext={procedureContext}
        connectionState="connected"
        desktopToolsAvailable={false}
        operations={[] as OperationView[]}
        approvalDisplay={null}
        pendingHumanInput={null}
      />,
    )

    expect(markup).toContain('当前规程')
    expect(markup).toContain('代码审查')
    expect(markup).toContain('自动推断')
    expect(markup).toContain('最近一次推断')
    expect(markup).toContain('search_memory')
    expect(markup).toContain('工作区/本地知识')
    expect(markup).toContain('当前工作区优先')
  })

  it('renders approval actions for pending approval-required operations', () => {
    const markup = renderToStaticMarkup(
      <WorkspacePanel
        workspace={workspace}
        procedureContext={procedureContext}
        connectionState="connected"
        desktopToolsAvailable={false}
        operations={[
          {
            operation_id: 'op_approval_1',
            thread_id: 'thread_1',
            workspace_id: 'personal',
            status: 'running',
            title: '需要审批的操作',
            operation_type: 'tool.call',
            execution_target: 'core_only',
            target_client_id: '',
            tool_key: 'shell.exec',
            tool_id: 'client.desktop-main.shell.exec',
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

    expect(markup).toContain('批准')
    expect(markup).toContain('拒绝')
  })
})
