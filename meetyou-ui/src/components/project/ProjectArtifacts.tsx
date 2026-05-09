import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { Archive, Download, FileText, RefreshCw } from 'lucide-react'
import type { RuntimeArtifact } from '../../types'
import styles from './ProjectArtifacts.module.css'

interface ProjectArtifactsProps {
  activeProjectId: string
  artifacts: RuntimeArtifact[]
  busy: boolean
  onRefresh: () => Promise<unknown>
  onDownload: (artifact: RuntimeArtifact) => Promise<unknown>
}

function artifactTitle(artifact: RuntimeArtifact): string {
  return String(artifact.filename || artifact.artifact_id || '产物').trim()
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return '0 B'
  }
  const units = ['B', 'KB', 'MB', 'GB']
  let size = value
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`
}

function formatSavedAt(artifact: RuntimeArtifact): string {
  const value = artifact.created_at || artifact.updated_at
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

function artifactTypeLabel(value: string): string {
  const key = String(value || '').trim()
  const labels: Record<string, string> = {
    research_report: '研究报告',
    document: '文档',
    markdown: 'Markdown',
  }
  return labels[key] || key || '产物'
}

function statusLabel(value: string): string {
  const key = String(value || '').trim()
  const labels: Record<string, string> = {
    active: '可用',
    archived: '已归档',
  }
  return labels[key] || key || '可用'
}

function metadataPreview(artifact: RuntimeArtifact): string {
  const entries = Object.entries(artifact.metadata || {})
    .filter(([, value]) => value !== undefined && value !== null && String(value).trim())
    .slice(0, 5)
  if (entries.length === 0) {
    return ''
  }
  return entries.map(([key, value]) => `${key}: ${formatMetadataValue(value)}`).join('\n')
}

function formatMetadataValue(value: unknown): string {
  if (typeof value === 'object' && value !== null) {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

export default function ProjectArtifacts({
  activeProjectId,
  artifacts,
  busy,
  onRefresh,
  onDownload,
}: ProjectArtifactsProps) {
  const [open, setOpen] = useState(false)
  const [selectedArtifactId, setSelectedArtifactId] = useState('')
  const [error, setError] = useState('')
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({})
  const disabled = !activeProjectId
  const selectedArtifact = useMemo(
    () => artifacts.find((artifact) => artifact.artifact_id === selectedArtifactId) || artifacts[0] || null,
    [selectedArtifactId, artifacts],
  )
  const selectedMetadataPreview = selectedArtifact ? metadataPreview(selectedArtifact) : ''

  useEffect(() => {
    if (selectedArtifact) {
      setSelectedArtifactId(selectedArtifact.artifact_id)
    } else {
      setSelectedArtifactId('')
    }
  }, [selectedArtifact?.artifact_id])

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
        top: Math.min(rect.bottom + 10, Math.max(gutter, window.innerHeight - 320)),
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
      setError(caught instanceof Error ? caught.message : '加载项目产物失败')
    }
  }

  const download = async (artifact: RuntimeArtifact) => {
    if (busy) {
      return
    }
    setError('')
    try {
      await onDownload(artifact)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '下载产物失败')
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
    <div className={styles.projectArtifacts}>
      <button
        ref={triggerRef}
        type="button"
        className={`${styles.trigger} ${open ? styles.open : ''}`}
        data-project-artifacts-trigger="true"
        title={disabled ? '选择项目后查看产物' : `${artifacts.length} 个项目产物`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={toggle}
      >
        <Archive size={14} aria-hidden="true" />
        <span className={styles.triggerTitle}>{artifacts.length}</span>
      </button>

      {open && typeof document !== 'undefined' && createPortal(
        <div className={styles.menu} ref={menuRef} style={menuStyle} role="menu" aria-label="项目产物" data-project-artifacts-menu="true">
          <div className={styles.header}>
            <span>{artifacts.length} 个项目产物</span>
            <button type="button" title="刷新项目产物" onClick={() => void refresh()} disabled={busy} data-project-artifacts-refresh="true">
              <RefreshCw size={14} aria-hidden="true" />
            </button>
          </div>

          {error ? <div className={styles.error}>{error}</div> : null}

          {artifacts.length === 0 ? (
            <div className={styles.empty}>暂无项目产物</div>
          ) : (
            <div className={styles.grid}>
              <div className={styles.list}>
                {artifacts.slice(0, 12).map((artifact) => (
                  <button
                    type="button"
                    key={artifact.artifact_id}
                    className={`${styles.artifactItem} ${selectedArtifact?.artifact_id === artifact.artifact_id ? styles.active : ''}`}
                    data-project-artifact-id={artifact.artifact_id}
                    onClick={() => setSelectedArtifactId(artifact.artifact_id)}
                    title={artifactTitle(artifact)}
                  >
                    <FileText size={13} aria-hidden="true" />
                    <span>
                      <strong>{artifactTitle(artifact)}</strong>
                      <small>{artifactTypeLabel(artifact.artifact_type) || artifact.artifact_id.slice(-8)}</small>
                    </span>
                  </button>
                ))}
              </div>

              <div className={styles.detail}>
                <div className={styles.detailTitle}>{selectedArtifact ? artifactTitle(selectedArtifact) : '产物'}</div>
                <div className={styles.detailMeta} data-project-artifact-detail="true">
                  {selectedArtifact
                    ? `${artifactTypeLabel(selectedArtifact.artifact_type)} / ${statusLabel(selectedArtifact.status)} / ${formatBytes(selectedArtifact.byte_size)} / ${formatSavedAt(selectedArtifact)}`
                    : ''}
                </div>
                <div className={styles.checksum}>{selectedArtifact?.checksum || ''}</div>
                {selectedMetadataPreview ? (
                  <pre className={styles.metadata}>{selectedMetadataPreview}</pre>
                ) : null}
                {selectedArtifact ? (
                  <button
                    type="button"
                    className={styles.download}
                    data-project-artifact-download="true"
                    disabled={busy}
                    onClick={() => void download(selectedArtifact)}
                  >
                    <Download size={14} aria-hidden="true" />
                    <span>下载</span>
                  </button>
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
