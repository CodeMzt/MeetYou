import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import ResearchPanel from './ResearchPanel'
import type { RuntimeResearchTask } from '../../types'

const task: RuntimeResearchTask = {
  research_task_id: 'res_1',
  project_id: 'prj_1',
  thread_id: 'thr_1',
  artifact_id: 'art_1',
  topic: 'Durable conversation history',
  status: 'planned',
  plan: {
    steps: [
      { id: 'scope', title: 'Define scope', status: 'planned' },
      { id: 'gather', title: 'Gather evidence', status: 'planned' },
    ],
  },
  source_policy: {},
  evidence_ledger: [
    {
      evidence_id: 'ev_1',
      title: 'Conversation trees',
      source_type: 'project_source',
      url: 'https://example.test/source',
    },
  ],
  output_format: 'markdown',
  summary: 'Conversation versions should be durable.',
  artifact: {
    artifact_id: 'art_1',
    project_id: 'prj_1',
    thread_id: 'thr_1',
    artifact_type: 'research_report',
    filename: 'report.md',
    content_type: 'text/markdown',
    byte_size: 12,
    checksum: 'sha256:abc',
    status: 'active',
    download_url: '/runtime/artifacts/art_1/download',
    metadata: {},
    created_at: '2026-05-09T00:00:00Z',
    updated_at: '2026-05-09T00:00:00Z',
  },
  metadata: {
    progress: {
      stage: 'gather',
      status: 'running',
      message: '正在收集研究证据。',
      at: '2026-05-09T00:00:00Z',
      gather_error_count: 1,
    },
    gather_errors: [{ adapter: 'web', error_type: 'WebSeedUrlsRequired' }],
  },
  created_at: '2026-05-09T00:00:00Z',
  updated_at: '2026-05-09T00:00:00Z',
}

describe('ResearchPanel', () => {
  it('renders task actions and download affordance', () => {
    const markup = renderToStaticMarkup(
      <ResearchPanel
        tasks={[task]}
        busy={false}
        onCreateTask={vi.fn()}
        onApproveTask={vi.fn()}
        onStartTask={vi.fn()}
        onCancelTask={vi.fn()}
        onSavePlan={vi.fn()}
        onDownloadArtifact={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(markup).toContain('data-research-panel="true"')
    expect(markup).toContain('Durable conversation history')
    expect(markup).toContain('data-research-download="true"')
    expect(markup).toContain('data-research-evidence-list="true"')
    expect(markup).toContain('Conversation versions should be durable.')
    expect(markup).toContain('data-research-progress-stage="true"')
    expect(markup).toContain('正在收集研究证据。')
    expect(markup).toContain('data-research-progress-errors="true"')
  })
})
