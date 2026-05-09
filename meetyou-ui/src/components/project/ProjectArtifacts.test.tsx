import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import ProjectArtifacts from './ProjectArtifacts'
import type { RuntimeArtifact } from '../../types'

const artifact: RuntimeArtifact = {
  artifact_id: 'art_1',
  project_id: 'prj_1',
  thread_id: 'thr_1',
  artifact_type: 'research_report',
  filename: 'research-report.md',
  content_type: 'text/markdown',
  byte_size: 2048,
  checksum: 'sha256:abc',
  status: 'active',
  download_url: '/runtime/artifacts/art_1/download',
  metadata: { research_task_id: 'res_1' },
  created_at: '2026-05-09T00:00:00Z',
  updated_at: '2026-05-09T00:00:00Z',
}

describe('ProjectArtifacts', () => {
  it('renders artifact trigger and keeps disabled state without a project', () => {
    const markup = renderToStaticMarkup(
      <ProjectArtifacts
        activeProjectId=""
        artifacts={[]}
        busy={false}
        onRefresh={vi.fn()}
        onDownload={vi.fn()}
      />,
    )

    expect(markup).toContain('data-project-artifacts-trigger="true"')
    expect(markup).toContain('disabled=""')
  })

  it('renders an enabled trigger with artifact count for an active project', () => {
    const markup = renderToStaticMarkup(
      <ProjectArtifacts
        activeProjectId="prj_1"
        artifacts={[artifact]}
        busy={false}
        onRefresh={vi.fn()}
        onDownload={vi.fn()}
      />,
    )

    expect(markup).toContain('data-project-artifacts-trigger="true"')
    expect(markup).toContain('1')
    expect(markup).not.toContain('disabled=""')
  })
})
