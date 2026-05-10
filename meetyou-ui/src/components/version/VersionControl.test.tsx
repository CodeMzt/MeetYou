import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import VersionControl, { buildBranchPath, buildBranchTree, resolveActiveBranch, siblingBranches } from './VersionControl'
import type { RuntimeConversationCheckpoint, RuntimeThreadBranch } from '../../types'

const branch: RuntimeThreadBranch = {
  branch_id: 'br_1',
  thread_id: 'thr_1',
  parent_branch_id: '',
  title: '默认分支',
  status: 'active',
  current_leaf_message_id: 'msg_1',
  metadata: { is_active: true },
  created_at: '2026-05-09T00:00:00Z',
  updated_at: '2026-05-09T00:00:00Z',
}

const checkpoint: RuntimeConversationCheckpoint = {
  checkpoint_id: 'chk_1',
  thread_id: 'thr_1',
  branch_id: 'br_1',
  message_id: 'msg_1',
  checkpoint_type: 'manual',
  title: '编辑前',
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
        onActivateBranch={vi.fn()}
      />,
    )

    expect(markup).toContain('1 个分支 / 1 个检查点')
    expect(markup).toContain('aria-haspopup="menu"')
    expect(markup).toContain('data-version-control-trigger="true"')
  })

  it('derives active branch path and sibling variants from branch metadata', () => {
    const checkoutBranch: RuntimeThreadBranch = {
      ...branch,
      branch_id: 'br_2',
      parent_branch_id: 'br_1',
      title: '重试分支',
      current_leaf_message_id: 'msg_2',
      metadata: { is_active: true },
    }
    const siblingBranch: RuntimeThreadBranch = {
      ...branch,
      branch_id: 'br_3',
      parent_branch_id: 'br_1',
      title: '再次重试',
      current_leaf_message_id: 'msg_3',
      metadata: {},
    }
    const rootBranch = { ...branch, metadata: {} }
    const branches = [rootBranch, checkoutBranch, siblingBranch]

    expect(resolveActiveBranch(branches)?.branch_id).toBe('br_2')
    expect(buildBranchPath(branches, 'br_2').map((item) => item.branch_id)).toEqual(['br_1', 'br_2'])
    expect(siblingBranches(branches, 'br_2').map((item) => item.branch_id)).toEqual(['br_2', 'br_3'])
  })

  it('builds a compact branch tree from public parent branch ids', () => {
    const rootBranch: RuntimeThreadBranch = { ...branch, metadata: {} }
    const checkoutBranch: RuntimeThreadBranch = {
      ...branch,
      branch_id: 'br_2',
      parent_branch_id: 'br_1',
      current_leaf_message_id: 'msg_2',
      metadata: {},
      created_at: '2026-05-09T00:01:00Z',
    }
    const retryBranch: RuntimeThreadBranch = {
      ...branch,
      branch_id: 'br_3',
      parent_branch_id: 'br_2',
      current_leaf_message_id: 'msg_3',
      metadata: { is_active: true },
      created_at: '2026-05-09T00:02:00Z',
    }
    const siblingBranch: RuntimeThreadBranch = {
      ...branch,
      branch_id: 'br_4',
      parent_branch_id: 'br_1',
      current_leaf_message_id: 'msg_4',
      metadata: {},
      created_at: '2026-05-09T00:03:00Z',
    }

    const tree = buildBranchTree([retryBranch, siblingBranch, rootBranch, checkoutBranch], 'br_3')

    expect(tree.map((item) => [item.branch.branch_id, item.depth, item.active])).toEqual([
      ['br_1', 0, false],
      ['br_2', 1, false],
      ['br_3', 2, true],
      ['br_4', 1, false],
    ])
  })
})
