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
  return String(checkpoint.title || checkpoint.checkpoint_id.slice(-8) || 'Checkpoint').trim()
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
  const title = useMemo(() => `${branches.length || 1} branches / ${checkpoints.length} checkpoints`, [branches.length, checkpoints.length])

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
        top: Math.min(rect.bottom + 10, Math.max(gutter, window.innerHeight - 220)),
        width,
        maxHeight: Math.max(220, window.innerHeight - rect.bottom - 22),
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
      setError(caught instanceof Error ? caught.message : '操作失败')
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
        <div className={styles.menu} ref={menuRef} style={menuStyle} role="menu" aria-label="Conversation versions" data-version-control-menu="true">
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
            <span>{branches.length || 1} branches</span>
            <span>{checkpoints.length} checkpoints</span>
          </div>

          {error ? <div className={styles.error}>{error}</div> : null}

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
                  disabled={Boolean(busy)}
                  onClick={() => void runAction(`restore-${checkpoint.checkpoint_id}`, () => onRestoreCheckpoint(checkpoint.checkpoint_id), true)}
                >
                  <RotateCcw size={14} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  title="从检查点签出"
                  data-version-control-checkout="true"
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
