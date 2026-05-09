import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import MessageList from './MessageList'
import type { ComponentProps } from 'react'
import type { ChatTurn } from '../../types'

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

  it('does not expose V5 message actions when handlers are absent', () => {
    const markup = renderMessageList()

    expect(markup).not.toContain('aria-label="消息操作"')
  })
})
