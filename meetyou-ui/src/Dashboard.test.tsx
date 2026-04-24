import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import Dashboard from './Dashboard'

vi.mock('./hooks/useMemory', () => ({
  useMemory: () => ({
    snapshot: {
      working_summaries: { global_summary: '', session_summary: '' },
      records: [],
      edges: [],
      stats: { record_count: 0, edge_count: 0, by_type: {} },
    },
    graph: null,
    refresh: vi.fn(),
    error: null,
    clearFeedback: null,
    clearing: false,
    mutatingRecordIds: new Set(),
    clearMemory: vi.fn(),
    updateRecordStatus: vi.fn(),
    deleteRecord: vi.fn(),
  }),
}))

describe('Dashboard', () => {
  it('makes destructive memory clearing discoverable', () => {
    const markup = renderToStaticMarkup(<Dashboard />)

    expect(markup).toContain('记忆管理')
    expect(markup).toContain('清空全部记忆')
    expect(markup).toContain('记录列表')
  })
})
