import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import ProjectPicker from './ProjectPicker'
import type { RuntimeProject } from '../../types'

function project(project_id: string, title: string): RuntimeProject {
  return {
    project_id,
    workspace_id: 'personal',
    title,
    description: '',
    instructions: '',
    status: 'active',
    memory_scope: {},
    metadata: {},
    created_at: '2026-05-09T00:00:00Z',
    updated_at: '2026-05-09T00:00:00Z',
  }
}

describe('ProjectPicker', () => {
  it('renders the active project in the compact trigger', () => {
    const markup = renderToStaticMarkup(
      <ProjectPicker
        projects={[project('prj_research', 'Research Sprint'), project('prj_school', 'Course Work')]}
        activeProjectId="prj_research"
        onSelectProject={vi.fn()}
        onCreateProject={vi.fn()}
      />,
    )

    expect(markup).toContain('Research Sprint')
    expect(markup).toContain('aria-haspopup="listbox"')
    expect(markup).not.toContain('Course Work')
  })

  it('falls back to the all-thread scope when no project is active', () => {
    const markup = renderToStaticMarkup(
      <ProjectPicker
        projects={[project('prj_research', 'Research Sprint')]}
        activeProjectId=""
        onSelectProject={vi.fn()}
        onCreateProject={vi.fn()}
      />,
    )

    expect(markup).toContain('全部会话')
  })
})
