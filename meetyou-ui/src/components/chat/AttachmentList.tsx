import type { AttachmentObjectView } from '../../types'
import styles from './AttachmentList.module.css'

interface AttachmentListProps {
  attachments: AttachmentObjectView[]
  title?: string
  onDownloadAttachment?: (attachmentId: string) => void
}

export default function AttachmentList({ attachments, title, onDownloadAttachment }: AttachmentListProps) {
  if (!attachments.length) {
    return null
  }

  return (
    <div className={styles.section}>
      {title ? <div className={styles.title}>{title}</div> : null}
      <div className={styles.list}>
        {attachments.map((attachment, index) => (
          <button
            type="button"
            key={`${attachment.attachmentId}-${index}`}
            className={styles.chip}
            onClick={() => onDownloadAttachment?.(attachment.attachmentId)}
          >
            {attachment.fileName}
          </button>
        ))}
      </div>
    </div>
  )
}
