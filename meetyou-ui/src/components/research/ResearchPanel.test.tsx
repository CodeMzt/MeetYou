import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import ResearchPanel from './ResearchPanel'
import type { RuntimeResearchTask } from '../../types'

const task: RuntimeResearchTask = {
  research_task_id: 'res_1',
  project_id: 'prj_1',
  thread_id: 'thr_1',
  run_id: 'run_1234567890abcdef',
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
  derived_artifacts: [
    {
      artifact_id: 'art_pdf',
      project_id: 'prj_1',
      thread_id: 'thr_1',
      artifact_type: 'research_report_derivative',
      filename: 'report.pdf',
      content_type: 'application/pdf',
      byte_size: 34,
      checksum: 'sha256:pdf',
      status: 'active',
      download_url: '/runtime/artifacts/art_pdf/download',
      metadata: { derived_format: 'pdf' },
      created_at: '2026-05-09T00:00:00Z',
      updated_at: '2026-05-09T00:00:00Z',
    },
  ],
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

const taskEvents = {
  res_1: [
    {
      event_id: 'evt_1',
      research_task_id: 'res_1',
      run_id: 'run_1234567890abcdef',
      thread_id: 'thr_1',
      seq: 1,
      type: 'research.started',
      payload: { status: 'running' },
      durable: true,
      created_at: '2026-05-09T00:00:00Z',
    },
    {
      event_id: 'evt_2',
      research_task_id: 'res_1',
      run_id: 'run_1234567890abcdef',
      thread_id: 'thr_1',
      seq: 2,
      type: 'research.progress',
      payload: { stage: 'gather', status: 'running', message: '正在收集研究证据。' },
      durable: true,
      created_at: '2026-05-09T00:00:01Z',
    },
  ],
}

describe('ResearchPanel', () => {
  it('renders task actions and download affordance', () => {
    const markup = renderToStaticMarkup(
      <ResearchPanel
        tasks={[task]}
        taskEvents={taskEvents}
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
    expect(markup).toContain('data-research-web-search-toggle="true"')
    expect(markup).toContain('data-research-web-query-input="true"')
    expect(markup).toContain('data-research-web-url-input="true"')
    expect(markup).toContain('联网搜索')
    expect(markup).toContain('搜索查询，留空使用主题')
    expect(markup).toContain('网页 URL，可逗号分隔')
    expect(markup).toContain('data-research-source-scope="true"')
    expect(markup).toContain('data-research-academic-adapter="arxiv"')
    expect(markup).toContain('data-research-academic-adapter="openalex"')
    expect(markup).toContain('data-research-academic-adapter="crossref"')
    expect(markup).toContain('data-research-academic-adapter="semantic_scholar"')
    expect(markup).toContain('data-research-source-limit="true"')
    expect(markup).toContain('学术源')
    expect(markup).toContain('data-research-export-scope="true"')
    expect(markup).toContain('data-research-derived-format="pdf"')
    expect(markup).toContain('data-research-derived-format="docx"')
    expect(markup).toContain('导出 1')
    expect(markup).toContain('report.pdf')
    expect(markup).toContain('data-research-event-stream="true"')
    expect(markup).toContain('data-research-event-count="true"')
    expect(markup).toContain('data-research-run-id="true"')
    expect(markup).toContain('90abcdef')
  })

  it('marks running tasks as auto-refreshed', () => {
    const markup = renderToStaticMarkup(
      <ResearchPanel
        tasks={[{ ...task, status: 'running' }]}
        taskEvents={taskEvents}
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

    expect(markup).toContain('data-research-auto-refresh="true"')
    expect(markup).toContain('自动刷新')
    expect(markup).toContain('data-research-cancel="true"')
  })
})
