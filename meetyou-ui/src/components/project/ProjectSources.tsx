import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { Database, FileText, RefreshCw } from 'lucide-react'
import type { RuntimeProjectSource } from '../../types'
import styles from './ProjectSources.module.css'

interface ProjectSourcesProps {
  activeProjectId: string
  sources: RuntimeProjectSource[]
  busy: boolean
  onRefresh: () => Promise<unknown>
}

function sourceTitle(source: RuntimeProjectSource): string {
  return String(source.title || source.source_id || 'Project source').trim()
}

function sourcePreview(source: RuntimeProjectSource): string {
  return String(source.content || '').replace(/\s+/g, ' ').trim()
}

function formatSavedAt(source: RuntimeProjectSource): string {
  const value = source.created_at || source.updated_at
  if (!value) {
    return 'unknown time'
  }
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(value))
  } catch {
    return String(value)
  }
}

function metadataPreview(source: RuntimeProjectSource): string {
  const entries = Object.entries(source.metadata || {})
    .filter(([, value]) => value !== undefined && value !== null && String(value).trim())
    .slice(0, 4)
  if (entries.length === 0) {
    return ''
  }
  return entries.map(([key, value]) => `${key}: ${String(value)}`).join('\n')
}

export default function ProjectSources({
  activeProjectId,
  sources,
  busy,
  onRefresh,
}: ProjectSourcesProps) {
  const [open, setOpen] = useState(false)
  const [selectedSourceId, setSelectedSourceId] = useState('')
  const [error, setError] = useState('')
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({})
  const disabled = !activeProjectId
  const selectedSource = useMemo(
    () => sources.find((source) => source.source_id === selectedSourceId) || sources[0] || null,
    [selectedSourceId, sources],
  )
  const selectedMetadataPreview = selectedSource ? metadataPreview(selectedSource) : ''

  useEffect(() => {
    if (selectedSource) {
      setSelectedSourceId(selectedSource.source_id)
    } else {
      setSelectedSourceId('')
    }
  }, [selectedSource?.source_id])

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

  const refresh = async () => {
    if (busy || disabled) {
      return
    }
    setError('')
    try {
      await onRefresh()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Failed to load project sources')
    }
  }

  const toggle = () => {
    if (disabled) {
      return
    }
    setOpen((current) => !current)
    if (!open) {
      void refresh()
    }
  }

  return (
    <div className={styles.projectSources}>
      <button
        ref={triggerRef}
        type="button"
        className={`${styles.trigger} ${open ? styles.open : ''}`}
        data-project-sources-trigger="true"
        title={disabled ? 'Select a project to view sources' : `${sources.length} project sources`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={toggle}
      >
        <Database size={14} aria-hidden="true" />
        <span className={styles.triggerTitle}>{sources.length}</span>
      </button>

      {open && typeof document !== 'undefined' && createPortal(
        <div className={styles.menu} ref={menuRef} style={menuStyle} role="menu" aria-label="Project sources" data-project-sources-menu="true">
          <div className={styles.header}>
            <span>{sources.length} project sources</span>
            <button type="button" title="Refresh project sources" onClick={() => void refresh()} disabled={busy} data-project-sources-refresh="true">
              <RefreshCw size={14} aria-hidden="true" />
            </button>
          </div>

          {error ? <div className={styles.error}>{error}</div> : null}

          {sources.length === 0 ? (
            <div className={styles.empty}>No project sources</div>
          ) : (
            <div className={styles.grid}>
              <div className={styles.list}>
                {sources.slice(0, 12).map((source) => (
                  <button
                    type="button"
                    key={source.source_id}
                    className={`${styles.sourceItem} ${selectedSource?.source_id === source.source_id ? styles.active : ''}`}
                    data-project-source-id={source.source_id}
                    onClick={() => setSelectedSourceId(source.source_id)}
                    title={sourceTitle(source)}
                  >
                    <FileText size={13} aria-hidden="true" />
                    <span>
                      <strong>{sourceTitle(source)}</strong>
                      <small>{source.source_type || source.source_id.slice(-8)}</small>
                    </span>
                  </button>
                ))}
              </div>

              <div className={styles.detail}>
                <div className={styles.detailTitle}>{selectedSource ? sourceTitle(selectedSource) : 'Project source'}</div>
                <div className={styles.detailMeta}>
                  {selectedSource
                    ? `${selectedSource.source_type || 'source'} / ${selectedSource.status || 'active'} / ${formatSavedAt(selectedSource)}`
                    : ''}
                </div>
                <pre className={styles.content} data-project-source-content="true">{selectedSource ? sourcePreview(selectedSource) : ''}</pre>
                {selectedMetadataPreview ? (
                  <pre className={styles.metadata}>{selectedMetadataPreview}</pre>
                ) : null}
              </div>
            </div>
          )}
        </div>,
        document.body,
      )}
    </div>
  )
}
