import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import RecordsView from './RecordsView'
import type { MemorySnapshot } from '../hooks/useMemory'

const snapshot: MemorySnapshot = {
  working_summaries: {
    global_summary: '',
    session_summary: '',
  },
  records: [
    {
      id: 'mem_1',
      type: 'fact',
      content: 'user likes black coffee',
      status: 'active',
      strength: 0.8,
      importance: 0.7,
      confidence: 0.9,
      created_at: '2026-04-24T00:00:00Z',
      last_updated_at: '2026-04-24T00:00:00Z',
      tags: [],
      fact_key: 'preference',
      fact_value: 'black coffee',
    },
  ],
  edges: [],
  stats: {
    record_count: 1,
    edge_count: 0,
    by_type: { fact: 1 },
  },
}

describe('RecordsView', () => {
  it('renders per-record invalidate and delete actions', () => {
    const markup = renderToStaticMarkup(
      <RecordsView
        snapshot={snapshot}
        onUpdateStatus={async () => undefined}
        onDeleteRecord={async () => undefined}
      />,
    )

    expect(markup).toContain('失效')
    expect(markup).toContain('删除')
    expect(markup).toContain('user likes black coffee')
  })
})
