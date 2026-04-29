import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Check, ChevronDown, MessageSquare, Plus, Trash2 } from 'lucide-react'
import type { RuntimeThreadPresentation } from '../../threadPresentation'
import styles from './ThreadPicker.module.css'

interface ThreadPickerProps {
  items: RuntimeThreadPresentation[]
  activeThreadId: string
  defaultThreadId: string
  onSelectThread: (threadId: string) => void | Promise<void>
  onCreateThread: (title?: string) => unknown | Promise<unknown>
  onDeleteThread: (threadId: string) => unknown | Promise<unknown>
}

export default function ThreadPicker({
  items,
  activeThreadId,
  defaultThreadId,
  onSelectThread,
  onCreateThread,
  onDeleteThread,
}: ThreadPickerProps) {
  const [open, setOpen] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')
  const [creating, setCreating] = useState(false)
  const [deletingThreadId, setDeletingThreadId] = useState('')
  const rootRef = useRef<HTMLDivElement | null>(null)
  const activeItem = useMemo(
    () => items.find((item) => item.thread.thread_id === activeThreadId) ?? items[0] ?? null,
    [activeThreadId, items],
  )

  useEffect(() => {
    if (!open) {
      return
    }
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
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

  const handleDelete = async (threadId: string, title: string) => {
    if (!threadId || threadId === defaultThreadId || deletingThreadId) {
      return
    }
    if (!window.confirm(`删除“${title}”？`)) {
      return
    }
    setDeletingThreadId(threadId)
    try {
      await onDeleteThread(threadId)
      setOpen(false)
    } finally {
      setDeletingThreadId('')
    }
  }

  return (
    <div className={styles.threadPicker} ref={rootRef}>
      <button
        type="button"
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

      {open && (
        <div className={styles.menu} role="listbox" aria-label="选择会话线程">
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
            const canDelete = item.thread.thread_id !== defaultThreadId
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
                    onClick={() => void handleDelete(item.thread.thread_id, item.title)}
                    title="删除会话"
                    disabled={Boolean(deletingThreadId)}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
