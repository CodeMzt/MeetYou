import { useCallback, useEffect, useMemo, useState } from 'react'
import { Paperclip } from 'lucide-react'
import { normalizeAttachmentObject } from './attachmentObject'
import { triggerAttachmentDownload } from './attachmentTransfers'
import { deleteClientAttachment, listClientThreadAttachments } from './clientApi'
import type { AttachmentObjectView } from './types'
import SubWindow from './components/layout/SubWindow'
import AttachmentManagerPanel from './components/attachments/AttachmentManagerPanel'
import ConfirmModal from './components/common/ConfirmModal'
import { DEFAULT_BASE_URL, WINDOW_SYNC_CHANNEL } from './windowBridge'
import styles from './AttachmentsWindow.module.css'

type AttachmentWindowPayload = {
  baseUrl: string
  threadId: string
  clientId: string
  workspaceTitle: string
  attachmentInventoryVersion: number
}

const EMPTY_PAYLOAD: AttachmentWindowPayload = {
  baseUrl: DEFAULT_BASE_URL,
  threadId: '',
  clientId: '',
  workspaceTitle: '',
  attachmentInventoryVersion: 0,
}

export default function AttachmentsWindow() {
  const [payload, setPayload] = useState<AttachmentWindowPayload>(EMPTY_PAYLOAD)
  const [attachments, setAttachments] = useState<AttachmentObjectView[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deletingAttachmentId, setDeletingAttachmentId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const loadAttachments = useCallback(async () => {
    if (!payload.threadId) {
      setAttachments([])
      setError(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const records = await listClientThreadAttachments(payload.baseUrl, payload.threadId)
      const normalized = records
        .map((item) => normalizeAttachmentObject(item))
        .filter((item): item is AttachmentObjectView => Boolean(item))
      setAttachments(normalized)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '附件列表加载失败')
    } finally {
      setLoading(false)
    }
  }, [payload.baseUrl, payload.threadId])

  useEffect(() => {
    const handleAttachmentPanelUpdated = (_event: unknown, data: AttachmentWindowPayload | null) => {
      if (!data) {
        return
      }
      setPayload({
        ...EMPTY_PAYLOAD,
        ...data,
      })
    }

    window.ipcRenderer?.on(WINDOW_SYNC_CHANNEL.attachments.update, handleAttachmentPanelUpdated)
    window.ipcRenderer?.send(WINDOW_SYNC_CHANNEL.attachments.request)

    return () => {
      window.ipcRenderer?.off(WINDOW_SYNC_CHANNEL.attachments.update, handleAttachmentPanelUpdated)
    }
  }, [])

  useEffect(() => {
    void loadAttachments()
  }, [loadAttachments, payload.attachmentInventoryVersion])

  const sortedAttachments = useMemo(() => {
    return [...attachments].sort((left, right) => {
      const rightTime = Date.parse(right.updatedAt || right.createdAt || '') || 0
      const leftTime = Date.parse(left.updatedAt || left.createdAt || '') || 0
      return rightTime - leftTime
    })
  }, [attachments])

  const handleDownload = useCallback(async (attachmentId: string) => {
    try {
      await triggerAttachmentDownload(payload.baseUrl, attachmentId, payload.clientId)
      setError(null)
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : '附件下载失败')
    }
  }, [payload.baseUrl, payload.clientId])

  const handleDelete = useCallback((attachmentId: string) => {
    setConfirmDeleteId(attachmentId)
  }, [])

  const performDelete = useCallback(async () => {
    if (!confirmDeleteId) return
    const attachmentId = confirmDeleteId
    setConfirmDeleteId(null)
    setDeletingAttachmentId(attachmentId)
    try {
      await deleteClientAttachment(payload.baseUrl, attachmentId)
      setAttachments((current) => current.filter((item) => item.attachmentId !== attachmentId))
      setError(null)
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : '附件删除失败')
    } finally {
      setDeletingAttachmentId(null)
    }
  }, [confirmDeleteId, payload.baseUrl])

  const targetAttachment = attachments.find((item) => item.attachmentId === confirmDeleteId)
  const targetLabel = targetAttachment?.fileName || '该附件'

  return (
    <SubWindow title="附件管理" icon={<Paperclip size={16} />} className={styles.windowOverride}>
      <div className={`dashboard-content ${styles.content}`}>
        <AttachmentManagerPanel
          attachments={sortedAttachments}
          loading={loading}
          error={error}
          workspaceTitle={payload.workspaceTitle}
          deletingAttachmentId={deletingAttachmentId}
          onRefresh={() => void loadAttachments()}
          onDownload={(attachmentId) => void handleDownload(attachmentId)}
          onDelete={(attachmentId) => void handleDelete(attachmentId)}
        />
      </div>
      <ConfirmModal
        isOpen={!!confirmDeleteId}
        title="确认删除"
        message={`确认删除附件“${targetLabel}”吗？此操作不可撤销。`}
        confirmText="删除"
        cancelText="取消"
        isDestructive={true}
        onConfirm={() => void performDelete()}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </SubWindow>
  )
}
