import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { Database, FileText, Plus, RefreshCw, Save, Trash2, X } from 'lucide-react'
import type { RuntimeProjectSource } from '../../types'
import styles from './ProjectSources.module.css'

export interface ProjectSourceCreatePayload {
  title: string
  content: string
  source_type?: string
  content_type?: string
  metadata?: Record<string, unknown>
}

interface ProjectSourcesProps {
  activeProjectId: string
  sources: RuntimeProjectSource[]
  busy: boolean
  onRefresh: () => Promise<unknown>
  onCreateSource?: (payload: ProjectSourceCreatePayload) => RuntimeProjectSource | Promise<RuntimeProjectSource | null> | null
  onDeleteSource?: (sourceId: string) => RuntimeProjectSource | Promise<RuntimeProjectSource | null> | null
}

function sourceTitle(source: RuntimeProjectSource): string {
  return String(source.title || source.source_id || '项目源').trim()
}

function sourcePreview(source: RuntimeProjectSource): string {
  return String(source.content || '').replace(/\s+/g, ' ').trim()
}

function formatSavedAt(source: RuntimeProjectSource): string {
  const value = source.created_at || source.updated_at
  if (!value) {
    return '未知时间'
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

function sourceTypeLabel(value: string): string {
  const key = String(value || '').trim()
  const labels: Record<string, string> = {
    message_snapshot: '消息快照',
    note: '笔记',
    file: '文件',
    artifact: '产物',
  }
  return labels[key] || key || '项目源'
}

function statusLabel(value: string): string {
  const key = String(value || '').trim()
  const labels: Record<string, string> = {
    active: '可用',
    archived: '已归档',
  }
  return labels[key] || key || '可用'
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

interface ProjectSourceNoteFormProps {
  title: string
  content: string
  creating: boolean
  error: string
  onTitleChange: (value: string) => void
  onContentChange: (value: string) => void
  onCancel: () => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}

export function ProjectSourceNoteForm({
  title,
  content,
  creating,
  error,
  onTitleChange,
  onContentChange,
  onCancel,
  onSubmit,
}: ProjectSourceNoteFormProps) {
  return (
    <form className={styles.sourceForm} onSubmit={onSubmit} data-project-source-create-form="true">
      <label className={styles.formField}>
        <span>标题</span>
        <input
          className={styles.textInput}
          value={title}
          onChange={(event) => onTitleChange(event.target.value)}
          maxLength={120}
          placeholder="项目源标题"
          data-project-source-title-input="true"
        />
      </label>
      <label className={styles.formField}>
        <span>内容</span>
        <textarea
          className={styles.textarea}
          value={content}
          onChange={(event) => onContentChange(event.target.value)}
          rows={4}
          maxLength={8000}
          placeholder="粘贴或记录要在本项目共享的资料"
          data-project-source-content-input="true"
        />
      </label>
      {error ? <div className={styles.error}>{error}</div> : null}
      <div className={styles.formActions}>
        <button type="button" className={styles.secondaryButton} onClick={onCancel} disabled={creating}>
          <X size={13} aria-hidden="true" />
          取消
        </button>
        <button type="submit" className={styles.primaryButton} disabled={creating || !title.trim() || !content.trim()} data-project-source-save="true">
          <Save size={13} aria-hidden="true" />
          {creating ? '保存中' : '保存'}
        </button>
      </div>
    </form>
  )
}

export default function ProjectSources({
  activeProjectId,
  sources,
  busy,
  onRefresh,
  onCreateSource,
  onDeleteSource,
}: ProjectSourcesProps) {
  const [open, setOpen] = useState(false)
  const [selectedSourceId, setSelectedSourceId] = useState('')
  const [error, setError] = useState('')
  const [creatingOpen, setCreatingOpen] = useState(false)
  const [createTitle, setCreateTitle] = useState('')
  const [createContent, setCreateContent] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')
  const [deletingSourceId, setDeletingSourceId] = useState('')
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
      setError(caught instanceof Error ? caught.message : '加载项目源失败')
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

  const handleCreateSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!onCreateSource || creating) {
      return
    }
    const title = createTitle.trim()
    const content = createContent.trim()
    if (!title) {
      setCreateError('标题不能为空')
      return
    }
    if (!content) {
      setCreateError('内容不能为空')
      return
    }
    setCreating(true)
    setCreateError('')
    try {
      const source = await onCreateSource({
        source_type: 'note',
        content_type: 'text',
        title,
        content,
      })
      if (source?.source_id) {
        setSelectedSourceId(source.source_id)
      }
      setCreateTitle('')
      setCreateContent('')
      setCreatingOpen(false)
    } catch (caught) {
      setCreateError(caught instanceof Error ? caught.message : '创建项目源失败')
    } finally {
      setCreating(false)
    }
  }

  const deleteSelectedSource = async () => {
    if (!selectedSource || !onDeleteSource || deletingSourceId || busy) {
      return
    }
    const confirmed = typeof window === 'undefined'
      ? true
      : window.confirm(`删除项目源「${sourceTitle(selectedSource)}」？该操作只会从项目源列表归档，不会删除原始消息或产物。`)
    if (!confirmed) {
      return
    }
    setDeletingSourceId(selectedSource.source_id)
    setError('')
    try {
      await onDeleteSource(selectedSource.source_id)
      const nextSource = sources.find((source) => source.source_id !== selectedSource.source_id)
      setSelectedSourceId(nextSource?.source_id || '')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '删除项目源失败')
    } finally {
      setDeletingSourceId('')
    }
  }

  return (
    <div className={styles.projectSources}>
      <button
        ref={triggerRef}
        type="button"
        className={`${styles.trigger} ${open ? styles.open : ''}`}
        data-project-sources-trigger="true"
        title={disabled ? '选择项目后查看项目源' : `${sources.length} 个项目源`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={toggle}
      >
        <Database size={14} aria-hidden="true" />
        <span className={styles.triggerTitle}>{sources.length}</span>
      </button>

      {open && typeof document !== 'undefined' && createPortal(
        <div className={styles.menu} ref={menuRef} style={menuStyle} role="menu" aria-label="项目源" data-project-sources-menu="true">
          <div className={styles.header}>
            <span>{sources.length} 个项目源</span>
            <div className={styles.headerActions}>
              {onCreateSource ? (
                <button
                  type="button"
                  title="新建笔记源"
                  onClick={() => {
                    setCreateError('')
                    setCreatingOpen((current) => !current)
                  }}
                  disabled={busy}
                  data-project-source-create-toggle="true"
                >
                  <Plus size={14} aria-hidden="true" />
                </button>
              ) : null}
              <button type="button" title="刷新项目源" onClick={() => void refresh()} disabled={busy} data-project-sources-refresh="true">
                <RefreshCw size={14} aria-hidden="true" />
              </button>
            </div>
          </div>

          {error ? <div className={styles.error}>{error}</div> : null}
          {creatingOpen && onCreateSource ? (
            <ProjectSourceNoteForm
              title={createTitle}
              content={createContent}
              creating={creating}
              error={createError}
              onTitleChange={setCreateTitle}
              onContentChange={setCreateContent}
              onCancel={() => {
                setCreatingOpen(false)
                setCreateError('')
              }}
              onSubmit={handleCreateSubmit}
            />
          ) : null}

          {sources.length === 0 ? (
            <div className={styles.empty}>暂无项目源</div>
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
                      <small>{sourceTypeLabel(source.source_type) || source.source_id.slice(-8)}</small>
                    </span>
                  </button>
                ))}
              </div>

              <div className={styles.detail}>
                <div className={styles.detailHeader}>
                  <div className={styles.detailTitle}>{selectedSource ? sourceTitle(selectedSource) : '项目源'}</div>
                  {selectedSource && onDeleteSource ? (
                    <button
                      type="button"
                      className={styles.deleteButton}
                      title="删除项目源"
                      aria-label="删除项目源"
                      disabled={busy || Boolean(deletingSourceId)}
                      onClick={() => void deleteSelectedSource()}
                      data-project-source-delete="true"
                    >
                      <Trash2 size={13} aria-hidden="true" />
                    </button>
                  ) : null}
                </div>
                <div className={styles.detailMeta}>
                  {selectedSource
                    ? `${sourceTypeLabel(selectedSource.source_type)} / ${deletingSourceId === selectedSource.source_id ? '删除中' : statusLabel(selectedSource.status)} / ${formatSavedAt(selectedSource)}`
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
