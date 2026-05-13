import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import MessageList from './MessageList'
import type { ComponentProps } from 'react'
import type { ChatTurn, RuntimeConversationCheckpoint, RuntimeResearchTask } from '../../types'

function turn(id: string, role: ChatTurn['role'], content: string, temporary = false): ChatTurn {
  return {
    id,
    streamId: '',
    turnId: id,
    role,
    content,
    reasoning: '',
    activities: [],
    isStreaming: false,
    createdAt: 1760000000000,
    temporary,
  }
}

function checkpoint(messageId: string): RuntimeConversationCheckpoint {
  return {
    checkpoint_id: `chk_${messageId}`,
    thread_id: 'thr_1',
    branch_id: 'br_1',
    message_id: messageId,
    checkpoint_type: 'auto',
    title: 'Auto checkpoint',
    state: {},
    status: 'active',
    metadata: {},
    created_at: '2026-05-09T00:00:00Z',
    updated_at: '2026-05-09T00:00:00Z',
  }
}

function researchTask(status = 'running'): RuntimeResearchTask {
  return {
    research_task_id: 'rst_1',
    project_id: 'prj_1',
    thread_id: 'thr_1',
    run_id: 'run_1',
    artifact_id: '',
    topic: '深度研究测试',
    status,
    plan: {},
    source_policy: {},
    evidence_ledger: [],
    output_format: 'markdown',
    summary: '',
    artifact: null,
    metadata: {
      research_provider: 'gpt_researcher',
      adapter_status: 'running',
      progress: { stage: 'gather', status: 'running', message: '正在搜索和阅读资料' },
    },
    created_at: '2026-05-09T00:00:00Z',
    updated_at: '2026-05-09T00:00:01Z',
  }
}

function renderMessageList(props: Partial<ComponentProps<typeof MessageList>> = {}) {
  return renderToStaticMarkup(
    <MessageList
      connected
      messages={[turn('msg_saved', 'user', 'persisted'), turn('tmp_local', 'assistant', 'temporary', true)]}
      runtimeSnapshot={null}
      healthSnapshot={null}
      lastError={null}
      archivedTurnCount={0}
      approvalDisplay={null}
      pendingHumanInput={null}
      sendConfirmResponse={vi.fn()}
      sendHumanInputResponse={vi.fn()}
      {...props}
    />,
  )
}

describe('MessageList', () => {
  it('shows message actions only for persisted messages with V5 handlers', () => {
    const markup = renderMessageList({
      activeProjectId: 'prj_1',
      onSaveMessageAsProjectSource: vi.fn(),
      onEditRetryMessage: vi.fn(),
    })

    const actionTriggers = markup.match(/aria-label="消息操作"/g) || []
    expect(actionTriggers).toHaveLength(1)
  })

  it('shows message actions for persisted messages with checkpoint handlers', () => {
    const markup = renderMessageList({
      checkpoints: [checkpoint('msg_saved')],
      onRestoreCheckpoint: vi.fn(),
      onCheckoutCheckpoint: vi.fn(),
    })

    const actionTriggers = markup.match(/aria-label="消息操作"/g) || []
    expect(actionTriggers).toHaveLength(1)
  })

  it('does not expose V5 message actions when handlers are absent', () => {
    const markup = renderMessageList()

    expect(markup).not.toContain('aria-label="消息操作"')
  })

  it('renders current-thread research progress as an inline assistant status bubble', () => {
    const markup = renderMessageList({
      researchTasks: [researchTask()],
      researchTaskEvents: {},
    })

    expect(markup).toContain('data-research-status-bubble="true"')
    expect(markup).not.toContain('data-research-panel')
  })
})
