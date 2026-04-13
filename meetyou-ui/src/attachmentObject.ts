import type { AttachmentObjectView } from './types'

function readString(record: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }
  }
  return ''
}

function readNumber(record: Record<string, unknown>, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value
    }
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) {
        return parsed
      }
    }
  }
  return undefined
}

export function normalizeAttachmentObject(value: unknown): AttachmentObjectView | null {
  if (!value || typeof value !== 'object') {
    return null
  }
  const record = value as Record<string, unknown>
  const attachmentId = readString(record, 'attachmentId', 'attachment_id')
  if (!attachmentId) {
    return null
  }
  return {
    attachmentId,
    kind: readString(record, 'kind') || 'file',
    fileName: readString(record, 'fileName', 'file_name') || attachmentId,
    mimeType: readString(record, 'mimeType', 'mime_type') || undefined,
    sizeBytes: readNumber(record, 'sizeBytes', 'size_bytes'),
    status: readString(record, 'status') || undefined,
    lifecyclePolicy: readString(record, 'lifecyclePolicy', 'lifecycle_policy') || undefined,
    expiresAt: readString(record, 'expiresAt', 'expires_at') || undefined,
    downloadUrl: readString(record, 'downloadUrl', 'download_url') || undefined,
    fallbackDownloadUrl: readString(record, 'fallbackDownloadUrl', 'fallback_download_url') || undefined,
    downloadStrategy: readString(record, 'downloadStrategy', 'download_strategy') || undefined,
  }
}

export function normalizeAttachmentObjects(value: unknown): AttachmentObjectView[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map((item) => normalizeAttachmentObject(item))
    .filter((item): item is AttachmentObjectView => Boolean(item))
}
