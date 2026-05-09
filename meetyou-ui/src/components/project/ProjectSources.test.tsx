import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import ProjectSources from './ProjectSources'
import type { RuntimeProjectSource } from '../../types'

const source: RuntimeProjectSource = {
  source_id: 'src_1',
  project_id: 'prj_1',
  source_type: 'message_snapshot',
  title: 'Saved assistant answer',
  content: 'A saved source that should be visible inside the project.',
  content_type: 'text',
  checksum: 'sha256:abc',
  status: 'active',
  metadata: {},
  created_at: '2026-05-09T00:00:00Z',
  updated_at: '2026-05-09T00:00:00Z',
}

describe('ProjectSources', () => {
  it('renders source count trigger and keeps disabled state without a project', () => {
    const markup = renderToStaticMarkup(
      <ProjectSources
        activeProjectId=""
        sources={[]}
        busy={false}
        onRefresh={vi.fn()}
      />,
    )

    expect(markup).toContain('data-project-sources-trigger="true"')
    expect(markup).toContain('disabled=""')
  })

  it('renders an enabled trigger with source count for an active project', () => {
    const markup = renderToStaticMarkup(
      <ProjectSources
        activeProjectId="prj_1"
        sources={[source]}
        busy={false}
        onRefresh={vi.fn()}
      />,
    )

    expect(markup).toContain('data-project-sources-trigger="true"')
    expect(markup).toContain('1')
    expect(markup).not.toContain('disabled=""')
  })
})
