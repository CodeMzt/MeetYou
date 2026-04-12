import { Activity, AlertTriangle, CheckCircle2, Loader2, PlayCircle, MoreHorizontal } from 'lucide-react'
import type { OperationView } from '../../types'
import { formatOperationStatusLabel } from '../../utils/statusFormatting'
import AttachmentList from './AttachmentList'
import styles from './OperationPanel.module.css'

function formatPhaseLabel(phase: string): string {
  const normalized = String(phase || '').trim().toLowerCase()
  if (normalized === 'routing') return '路由'
  if (normalized === 'dispatching') return '分发'
  if (normalized === 'running') return '执行'
  if (normalized === 'done') return '完成'
  if (normalized === 'waiting_approval') return '等待审批'
  return phase || ''
}

interface OperationPanelProps {
  operations: OperationView[]
  onApprove?: (approvalId: string) => void
  onReject?: (approvalId: string) => void
  onDownloadAttachment?: (attachmentId: string) => void
}

function pickIcon(tone: string) {
  if (tone === 'failed') return <AlertTriangle size={14} />
  if (tone === 'success') return <CheckCircle2 size={14} />
  if (tone === 'running') return <Loader2 size={14} className={styles.spinning} />
  if (tone === 'pending') return <PlayCircle size={14} />
  return <Activity size={14} />
}

export default function OperationPanel({ operations, onApprove, onReject, onDownloadAttachment }: OperationPanelProps) {
  if (!operations.length) {
    return null
  }

  const sorted = [...operations].sort((a, b) => {
    const isRunningA = a.tone === 'running' || a.tone === 'pending'
    const isRunningB = b.tone === 'running' || b.tone === 'pending'
    if (isRunningA && !isRunningB) return -1
    if (!isRunningA && isRunningB) return 1
    return 0
  })

  const visible = sorted.slice(0, 4)
  const hasMore = sorted.length > 4

  return (
    <div className={styles.panel}>
      <div className={styles.panelHeader}>
        <span className={styles.panelTitle}>最近操作</span>
        {hasMore && (
          <span className={styles.moreIndicator}>
            <MoreHorizontal size={14} />
          </span>
        )}
      </div>
      <div className={styles.cardList}>
        {visible.map((operation) => (
          <div key={operation.operation_id} className={`${styles.card} ${styles[operation.tone] || ''}`}>
            <div className={styles.header}>
              <span className={styles.icon}>{pickIcon(operation.tone)}</span>
              <div className={styles.titleWrap}>
                <div className={styles.title}>{operation.title || operation.operation_id}</div>
                <div className={styles.meta}>
                  {operation.target_agent_id || '核心服务'} · {formatOperationStatusLabel(operation.status)}
                  {operation.phase && ` · ${formatPhaseLabel(operation.phase)}`}
                </div>
              </div>
            </div>
            <div className={styles.summary}>{operation.summary}</div>
            {operation.approval_required && operation.approval_status === 'pending' && operation.approval_id && (
              <div className={styles.actions}>
                <button type="button" className={styles.approveBtn} onClick={() => onApprove?.(operation.approval_id || '')}>
                  批准
                </button>
                <button type="button" className={styles.rejectBtn} onClick={() => onReject?.(operation.approval_id || '')}>
                  拒绝
                </button>
              </div>
            )}
            {operation.tone === 'failed' && operation.error && typeof operation.error.details === 'object' && operation.error.details !== null && Object.keys(operation.error.details).length > 0 && (
              <div className={styles.errorDetails}>
                {JSON.stringify(operation.error.details, null, 2)}
              </div>
            )}
            <AttachmentList attachments={operation.attachments} title="附件" onDownloadAttachment={onDownloadAttachment} />
          </div>
        ))}
      </div>
    </div>
  )
}
