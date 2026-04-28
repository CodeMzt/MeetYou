import type { AttachmentObjectView } from '../../types'
import styles from './AttachmentManagerPanel.module.css'

interface AttachmentManagerPanelProps {
  attachments: AttachmentObjectView[]
  loading: boolean
  error: string | null
  workspaceTitle?: string
  onRefresh?: () => void
  onDownload?: (attachmentId: string) => void
  onDelete?: (attachmentId: string) => void
  deletingAttachmentId?: string | null
}

function formatTimestamp(value?: string): string {
  if (!value) {
    return '未记录'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(parsed)
}

function formatSize(value?: number): string {
  const size = Number(value || 0)
  if (!Number.isFinite(size) || size <= 0) {
    return '0 B'
  }
  if (size >= 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} MB`
  }
  if (size >= 1024) {
    return `${(size / 1024).toFixed(1)} KB`
  }
  return `${size} B`
}

export default function AttachmentManagerPanel({
  attachments,
  loading,
  error,
  workspaceTitle,
  onRefresh,
  onDownload,
  onDelete,
  deletingAttachmentId,
}: AttachmentManagerPanelProps) {
  return (
    <div className={styles.page}>
      <div className={styles.heroCard}>
        <div>
          <div className={styles.kicker}>附件中心</div>
          <div className={styles.title}>附件管理</div>
          <div className={styles.subtitle}>
            {workspaceTitle ? `${workspaceTitle} 的当前会话附件列表。` : '查看当前会话附件并执行下载或删除。'}
          </div>
        </div>
        <div className={styles.actions}>
          <button type="button" className={styles.ghostBtn} onClick={onRefresh} disabled={loading}>
            {loading ? '刷新中...' : '刷新列表'}
          </button>
        </div>
      </div>

      {error ? <div className={styles.error}>{error}</div> : null}

      {attachments.length > 0 ? (
        <div className={styles.listCard}>
          <div className={styles.listHeader}>
            <div className={styles.listTitle}>附件列表</div>
            <div className={styles.listMeta}>共 {attachments.length} 个</div>
          </div>
          <div className={styles.rows}>
            {attachments.map((attachment) => (
              <div key={attachment.attachmentId} className={styles.row}>
                <div className={styles.mainInfo}>
                  <div className={styles.fileName}>{attachment.fileName}</div>
                  <div className={styles.metaRow}>
                    <span className={styles.metaChip}>{attachment.kind || '文件'}</span>
                    <span className={styles.metaChip}>{attachment.status || '未知'}</span>
                    <span className={styles.metaChip}>{formatSize(attachment.sizeBytes)}</span>
                  </div>
                  <div className={styles.timeline}>
                    <span>创建: {formatTimestamp(attachment.createdAt)}</span>
                    <span>更新: {formatTimestamp(attachment.updatedAt)}</span>
                    {attachment.expiresAt ? <span>过期: {formatTimestamp(attachment.expiresAt)}</span> : null}
                  </div>
                </div>
                <div className={styles.actionsCol}>
                  <button
                    type="button"
                    className={styles.primaryBtn}
                    onClick={() => onDownload?.(attachment.attachmentId)}
                  >
                    下载
                  </button>
                  <button
                    type="button"
                    className={styles.dangerBtn}
                    onClick={() => onDelete?.(attachment.attachmentId)}
                    disabled={deletingAttachmentId === attachment.attachmentId}
                  >
                    {deletingAttachmentId === attachment.attachmentId ? '删除中...' : '删除'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className={styles.emptyCard}>
          {loading ? '正在加载附件列表...' : '当前会话还没有可管理的附件。上传后会在这里集中展示。'}
        </div>
      )}
    </div>
  )
}
