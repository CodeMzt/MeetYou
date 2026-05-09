import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { BookmarkPlus, ChevronDown, GitBranch, GitFork, RotateCcw } from 'lucide-react'
import type { RuntimeConversationCheckpoint, RuntimeThreadBranch } from '../../types'
import styles from './VersionControl.module.css'

interface VersionControlProps {
  branches: RuntimeThreadBranch[]
  checkpoints: RuntimeConversationCheckpoint[]
  onCreateCheckpoint: () => Promise<unknown>
  onRestoreCheckpoint: (checkpointId: string) => Promise<unknown>
  onCheckoutCheckpoint: (checkpointId: string) => Promise<unknown>
}

function labelCheckpoint(checkpoint: RuntimeConversationCheckpoint): string {
  return String(checkpoint.title || checkpoint.checkpoint_id.slice(-8) || '检查点').trim()
}

function labelBranch(branch: RuntimeThreadBranch): string {
  return String(branch.title || branch.branch_id.slice(-8) || '分支').trim()
}

function shortTime(value: string): string {
  if (!value) {
    return ''
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return ''
  }
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function isActiveBranch(branch: RuntimeThreadBranch): boolean {
  return branch.metadata?.is_active === true || branch.metadata?.active === true
}

export function resolveActiveBranch(branches: RuntimeThreadBranch[]): RuntimeThreadBranch | null {
  return branches.find(isActiveBranch) || branches[branches.length - 1] || null
}

export function buildBranchPath(branches: RuntimeThreadBranch[], activeBranchId: string): RuntimeThreadBranch[] {
  const branchById = new Map(branches.map((branch) => [branch.branch_id, branch]))
  const path: RuntimeThreadBranch[] = []
  const seen = new Set<string>()
  let current = branchById.get(activeBranchId) || null
  while (current && !seen.has(current.branch_id)) {
    path.unshift(current)
    seen.add(current.branch_id)
    current = current.parent_branch_id ? branchById.get(current.parent_branch_id) || null : null
  }
  return path
}

export function siblingBranches(branches: RuntimeThreadBranch[], activeBranchId: string): RuntimeThreadBranch[] {
  const active = branches.find((branch) => branch.branch_id === activeBranchId)
  if (!active) {
    return branches
  }
  return branches.filter((branch) => branch.parent_branch_id === active.parent_branch_id)
}

export default function VersionControl({
  branches,
  checkpoints,
  onCreateCheckpoint,
  onRestoreCheckpoint,
  onCheckoutCheckpoint,
}: VersionControlProps) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({})
  const activeBranch = useMemo(() => resolveActiveBranch(branches), [branches])
  const currentPath = useMemo(
    () => (activeBranch ? buildBranchPath(branches, activeBranch.branch_id) : []),
    [activeBranch, branches],
  )
  const siblings = useMemo(
    () => (activeBranch ? siblingBranches(branches, activeBranch.branch_id) : branches),
    [activeBranch, branches],
  )
  const title = useMemo(() => `${branches.length || 1} 个分支 / ${checkpoints.length} 个检查点`, [branches.length, checkpoints.length])

  useEffect(() => {
    if (!open) {
      return
    }
    const close = (event: MouseEvent) => {
      const target = event.target as Node
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setOpen(false)
      }
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  useLayoutEffect(() => {
    if (!open) {
      return
    }
    const updatePosition = () => {
      const trigger = triggerRef.current
      if (!trigger) {
        return
      }
      const rect = trigger.getBoundingClientRect()
      const gutter = 12
      const width = Math.min(320, window.innerWidth - gutter * 2)
      setMenuStyle({
        left: Math.min(Math.max(gutter, rect.right - width), Math.max(gutter, window.innerWidth - width - gutter)),
        top: Math.min(rect.bottom + 10, Math.max(gutter, window.innerHeight - 300)),
        width,
        maxHeight: Math.max(260, window.innerHeight - rect.bottom - 22),
      })
    }
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [open])

  const runAction = async (key: string, action: () => Promise<unknown>, closeAfter = false) => {
    if (busy) {
      return
    }
    setBusy(key)
    setError('')
    try {
      await action()
      if (closeAfter) {
        setOpen(false)
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '版本操作失败')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className={styles.versionControl}>
      <button
        ref={triggerRef}
        type="button"
        className={`${styles.trigger} ${open ? styles.open : ''}`}
        data-version-control-trigger="true"
        title={title}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <GitBranch size={14} aria-hidden="true" />
        <span className={styles.triggerTitle}>{branches.length || 1}</span>
        <ChevronDown size={14} className={styles.chevron} aria-hidden="true" />
      </button>

      {open && typeof document !== 'undefined' && createPortal(
        <div className={styles.menu} ref={menuRef} style={menuStyle} role="menu" aria-label="对话版本" data-version-control-menu="true">
          <button
            type="button"
            className={styles.primaryAction}
            data-version-control-create="true"
            disabled={Boolean(busy)}
            onClick={() => void runAction('create', onCreateCheckpoint)}
          >
            <BookmarkPlus size={14} aria-hidden="true" />
            <span>创建检查点</span>
          </button>

          <div className={styles.summaryRow}>
            <span>{branches.length || 1} 个分支</span>
            <span>{checkpoints.length} 个检查点</span>
          </div>

          {error ? <div className={styles.error}>{error}</div> : null}

          <div className={styles.sectionTitle}>当前路径</div>
          {currentPath.length === 0 ? (
            <div className={styles.empty}>暂无分支路径</div>
          ) : (
            <div className={styles.branchPath} data-version-current-path="true">
              {currentPath.map((branch, index) => (
                <div className={styles.pathItem} key={branch.branch_id} data-version-path-branch={branch.branch_id}>
                  <span>{index + 1}</span>
                  <strong>{labelBranch(branch)}</strong>
                  {branch.branch_id === activeBranch?.branch_id ? <em>当前</em> : null}
                </div>
              ))}
            </div>
          )}

          <div className={styles.sectionTitle}>同级变体</div>
          {siblings.length === 0 ? (
            <div className={styles.empty}>暂无同级变体</div>
          ) : (
            <div className={styles.variantList} data-version-sibling-variants="true">
              {siblings.slice(0, 8).map((branch) => (
                <div
                  className={`${styles.variantItem} ${branch.branch_id === activeBranch?.branch_id ? styles.activeVariant : ''}`}
                  key={branch.branch_id}
                  data-version-sibling-variant={branch.branch_id}
                >
                  <div>
                    <strong>{labelBranch(branch)}</strong>
                    <span>{shortTime(branch.created_at) || branch.branch_id.slice(-8)}</span>
                  </div>
                  <small>{branch.current_leaf_message_id || branch.branch_id.slice(-8)}</small>
                </div>
              ))}
            </div>
          )}

          <div className={styles.sectionTitle}>检查点</div>
          {checkpoints.length === 0 ? (
            <div className={styles.empty}>暂无检查点</div>
          ) : checkpoints.map((checkpoint) => (
            <div className={styles.checkpointItem} key={checkpoint.checkpoint_id}>
              <div className={styles.checkpointText}>
                <span className={styles.checkpointTitle}>{labelCheckpoint(checkpoint)}</span>
                <span className={styles.checkpointMeta}>{shortTime(checkpoint.created_at) || checkpoint.checkpoint_id.slice(-8)}</span>
              </div>
              <div className={styles.actionGroup}>
                <button
                  type="button"
                  title="恢复到检查点"
                  data-version-control-restore="true"
                  data-version-checkpoint-id={checkpoint.checkpoint_id}
                  disabled={Boolean(busy)}
                  onClick={() => void runAction(`restore-${checkpoint.checkpoint_id}`, () => onRestoreCheckpoint(checkpoint.checkpoint_id), true)}
                >
                  <RotateCcw size={14} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  title="从检查点签出"
                  data-version-control-checkout="true"
                  data-version-checkpoint-id={checkpoint.checkpoint_id}
                  disabled={Boolean(busy)}
                  onClick={() => void runAction(`checkout-${checkpoint.checkpoint_id}`, () => onCheckoutCheckpoint(checkpoint.checkpoint_id), true)}
                >
                  <GitFork size={14} aria-hidden="true" />
                </button>
              </div>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </div>
  )
}
