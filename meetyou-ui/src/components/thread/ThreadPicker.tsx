import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, MessageSquare, Plus, Trash2 } from 'lucide-react'
import type { RuntimeThreadPresentation } from '../../threadPresentation'
import ConfirmModal from '../common/ConfirmModal'
import styles from './ThreadPicker.module.css'

interface ThreadPickerProps {
  items: RuntimeThreadPresentation[]
  activeThreadId: string
  onSelectThread: (threadId: string) => void | Promise<void>
  onCreateThread: (title?: string) => unknown | Promise<unknown>
  onDeleteThread: (threadId: string) => unknown | Promise<unknown>
}

export default function ThreadPicker({
  items,
  activeThreadId,
  onSelectThread,
  onCreateThread,
  onDeleteThread,
}: ThreadPickerProps) {
  const [open, setOpen] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')
  const [creating, setCreating] = useState(false)
  const [deletingThreadId, setDeletingThreadId] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<RuntimeThreadPresentation | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const rootRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({})
  const activeItem = useMemo(
    () => items.find((item) => item.thread.thread_id === activeThreadId) ?? items[0] ?? null,
    [activeThreadId, items],
  )

  useEffect(() => {
    if (!open) {
      return
    }
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setOpen(false)
      }
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  useLayoutEffect(() => {
    if (!open) {
      return
    }
    const updateMenuPosition = () => {
      const trigger = triggerRef.current
      if (!trigger) {
        return
      }
      const rect = trigger.getBoundingClientRect()
      const viewportWidth = window.innerWidth
      const viewportHeight = window.innerHeight
      const gutter = 12
      const width = Math.max(0, Math.min(360, viewportWidth - gutter * 2))
      const left = Math.min(
        Math.max(gutter, rect.right - width),
        Math.max(gutter, viewportWidth - width - gutter),
      )
      const top = Math.min(rect.bottom + 10, Math.max(gutter, viewportHeight - 112))
      const maxHeight = Math.max(180, viewportHeight - top - gutter)
      setMenuStyle({
        left,
        top,
        width,
        maxHeight,
      })
    }
    updateMenuPosition()
    window.addEventListener('resize', updateMenuPosition)
    window.addEventListener('scroll', updateMenuPosition, true)
    return () => {
      window.removeEventListener('resize', updateMenuPosition)
      window.removeEventListener('scroll', updateMenuPosition, true)
    }
  }, [open])

  if (!activeItem) {
    return null
  }

  const handleSelect = (threadId: string) => {
    setOpen(false)
    if (threadId !== activeThreadId) {
      void onSelectThread(threadId)
    }
  }

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (creating) {
      return
    }
    setCreating(true)
    try {
      await onCreateThread(draftTitle.trim() || undefined)
      setDraftTitle('')
      setOpen(false)
    } finally {
      setCreating(false)
    }
  }

  const requestDelete = (item: RuntimeThreadPresentation) => {
    const threadId = item.thread.thread_id
    if (!threadId || items.length <= 1 || deletingThreadId) {
      return
    }
    setDeleteError('')
    setOpen(false)
    setDeleteTarget(item)
  }

  const cancelDelete = () => {
    if (deletingThreadId) {
      return
    }
    setDeleteError('')
    setDeleteTarget(null)
  }

  const confirmDelete = async () => {
    if (!deleteTarget || deletingThreadId) {
      return
    }
    const threadId = deleteTarget.thread.thread_id
    setDeletingThreadId(threadId)
    try {
      await onDeleteThread(threadId)
      setDeleteTarget(null)
      setDeleteError('')
      setOpen(false)
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : '删除失败，请稍后重试。')
    } finally {
      setDeletingThreadId('')
    }
  }

  return (
    <div className={styles.threadPicker} ref={rootRef}>
      <button
        type="button"
        ref={triggerRef}
        className={`${styles.trigger} ${open ? styles.open : ''}`}
        onClick={() => setOpen((current) => !current)}
        title={activeItem.tooltip}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <MessageSquare size={14} aria-hidden="true" />
        <span className={styles.triggerTitle}>{activeItem.title}</span>
        <ChevronDown size={14} className={styles.chevron} aria-hidden="true" />
      </button>

      {open && typeof document !== 'undefined' && createPortal(
        <div
          className={styles.menu}
          ref={menuRef}
          style={menuStyle}
          role="listbox"
          aria-label="选择会话线程"
        >
          <form className={styles.createForm} onSubmit={handleCreate}>
            <input
              className={styles.createInput}
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              placeholder="新会话名称"
              maxLength={80}
            />
            <button type="submit" className={styles.createButton} title="新建会话" disabled={creating}>
              <Plus size={14} aria-hidden="true" />
            </button>
          </form>
          {items.map((item) => {
            const active = item.thread.thread_id === activeThreadId
            const detail = item.rawTitle === item.title ? item.thread.thread_id.slice(-8) : item.rawTitle
            const canDelete = items.length > 1
            return (
              <div
                key={item.thread.thread_id}
                className={`${styles.menuItem} ${active ? styles.activeMenuItem : ''}`}
                title={item.tooltip}
                role="option"
                aria-selected={active}
              >
                <button
                  type="button"
                  className={styles.selectButton}
                  onClick={() => handleSelect(item.thread.thread_id)}
                >
                  <span className={styles.itemText}>
                    <span className={styles.itemTitle}>{item.title}</span>
                    <span className={styles.itemDetail}>{detail}</span>
                  </span>
                  {active && <Check size={14} className={styles.checkIcon} aria-hidden="true" />}
                </button>
                {canDelete && (
                  <button
                    type="button"
                    className={styles.deleteButton}
                    onClick={() => requestDelete(item)}
                    title="删除会话"
                    disabled={Boolean(deletingThreadId)}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                )}
              </div>
            )
          })}
        </div>,
        document.body,
      )}
      <ConfirmModal
        isOpen={Boolean(deleteTarget)}
        title="删除会话"
        message={
          deleteError
            ? `删除失败：${deleteError}`
            : `确认删除“${deleteTarget?.title || ''}”？该会话会从列表中移除。`
        }
        confirmText={deletingThreadId ? '删除中...' : '删除'}
        cancelText="取消"
        isDestructive={true}
        busy={Boolean(deletingThreadId)}
        onConfirm={() => void confirmDelete()}
        onCancel={cancelDelete}
      />
    </div>
  )
}
