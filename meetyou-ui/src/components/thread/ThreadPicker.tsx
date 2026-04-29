import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, MessageSquare } from 'lucide-react'
import type { RuntimeThreadPresentation } from '../../threadPresentation'
import styles from './ThreadPicker.module.css'

interface ThreadPickerProps {
  items: RuntimeThreadPresentation[]
  activeThreadId: string
  onSelectThread: (threadId: string) => void
}

export default function ThreadPicker({ items, activeThreadId, onSelectThread }: ThreadPickerProps) {
  const [open, setOpen] = useState(false)
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
      onSelectThread(threadId)
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
          {items.map((item) => {
            const active = item.thread.thread_id === activeThreadId
            const detail = item.rawTitle === item.title ? item.thread.thread_id.slice(-8) : item.rawTitle
            return (
              <button
                key={item.thread.thread_id}
                type="button"
                className={`${styles.menuItem} ${active ? styles.activeMenuItem : ''}`}
                onClick={() => handleSelect(item.thread.thread_id)}
                title={item.tooltip}
                role="option"
                aria-selected={active}
              >
                <span className={styles.itemText}>
                  <span className={styles.itemTitle}>{item.title}</span>
                  <span className={styles.itemDetail}>{detail}</span>
                </span>
                {active && <Check size={14} className={styles.checkIcon} aria-hidden="true" />}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
