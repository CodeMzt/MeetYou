import type { MemoryRecord } from '../hooks/useMemory'

function parseMemoryTime(value?: string): number {
  if (!value) {
    return Number.NEGATIVE_INFINITY
  }
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? Number.NEGATIVE_INFINITY : timestamp
}

function getTimelineTimestamp(record: MemoryRecord): number {
  return Math.max(
    parseMemoryTime(record.created_at),
    parseMemoryTime(record.last_updated_at),
    parseMemoryTime(record.last_accessed_at),
  )
}

export function sortMemoryRecordsByTimeline(records: MemoryRecord[]): MemoryRecord[] {
  return records
    .map((record, index) => ({ record, index, timestamp: getTimelineTimestamp(record) }))
    .sort((left, right) => {
      if (right.timestamp !== left.timestamp) {
        return right.timestamp - left.timestamp
      }
      return left.index - right.index
    })
    .map(({ record }) => record)
}
