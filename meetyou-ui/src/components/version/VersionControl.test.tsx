import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import VersionControl from './VersionControl'
import type { RuntimeConversationCheckpoint, RuntimeThreadBranch } from '../../types'

const branch: RuntimeThreadBranch = {
  branch_id: 'br_1',
  thread_id: 'thr_1',
  parent_branch_id: '',
  title: 'Default',
  status: 'active',
  current_leaf_message_id: 'msg_1',
  metadata: {},
  created_at: '2026-05-09T00:00:00Z',
  updated_at: '2026-05-09T00:00:00Z',
}

const checkpoint: RuntimeConversationCheckpoint = {
  checkpoint_id: 'chk_1',
  thread_id: 'thr_1',
  branch_id: 'br_1',
  message_id: 'msg_1',
  checkpoint_type: 'manual',
  title: 'Before edit',
  state: {},
  status: 'active',
  metadata: {},
  created_at: '2026-05-09T00:00:00Z',
  updated_at: '2026-05-09T00:00:00Z',
}

describe('VersionControl', () => {
  it('renders a compact version trigger with branch/checkpoint counts', () => {
    const markup = renderToStaticMarkup(
      <VersionControl
        branches={[branch]}
        checkpoints={[checkpoint]}
        onCreateCheckpoint={vi.fn()}
        onRestoreCheckpoint={vi.fn()}
        onCheckoutCheckpoint={vi.fn()}
      />,
    )

    expect(markup).toContain('1 branches / 1 checkpoints')
    expect(markup).toContain('aria-haspopup="menu"')
    expect(markup).toContain('data-version-control-trigger="true"')
  })
})
