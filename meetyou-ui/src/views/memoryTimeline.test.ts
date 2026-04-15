import { describe, expect, it } from 'vitest'

import type { MemoryRecord } from '../hooks/useMemory'
import { sortMemoryRecordsByTimeline } from './memoryTimeline'

function createRecord(overrides: Partial<MemoryRecord>): MemoryRecord {
  return {
    id: overrides.id ?? 'record',
    type: overrides.type ?? 'episode',
    content: overrides.content ?? '',
    status: overrides.status ?? 'active',
    strength: overrides.strength ?? 0,
    importance: overrides.importance ?? 0,
    confidence: overrides.confidence ?? 0,
    created_at: overrides.created_at ?? '',
    last_accessed_at: overrides.last_accessed_at,
    last_updated_at: overrides.last_updated_at ?? '',
    access_count: overrides.access_count,
    tags: overrides.tags ?? [],
    entity_keys: overrides.entity_keys,
    source_record_ids: overrides.source_record_ids,
    scope: overrides.scope,
    fact_key: overrides.fact_key,
    fact_value: overrides.fact_value,
    label: overrides.label,
  }
}

describe('sortMemoryRecordsByTimeline', () => {
  it('sorts by the newest available timeline timestamp', () => {
    const records = [
      createRecord({ id: 'created-first', created_at: '2026-04-10T09:00:00Z' }),
      createRecord({ id: 'updated-later', created_at: '', last_updated_at: '2026-04-10T09:05:00Z' }),
      createRecord({ id: 'accessed-latest', created_at: '', last_updated_at: '', last_accessed_at: '2026-04-10T09:10:00Z' }),
    ]

    expect(sortMemoryRecordsByTimeline(records).map(record => record.id)).toEqual([
      'accessed-latest',
      'updated-later',
      'created-first',
    ])
  })

  it('keeps original order when timeline timestamps are tied', () => {
    const records = [
      createRecord({ id: 'first', created_at: '2026-04-10T09:00:00Z' }),
      createRecord({ id: 'second', created_at: '2026-04-10T09:00:00Z' }),
    ]

    expect(sortMemoryRecordsByTimeline(records).map(record => record.id)).toEqual(['first', 'second'])
  })
})
