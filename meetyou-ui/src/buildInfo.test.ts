import { describe, expect, it } from 'vitest'

import { detectBuildDriftWarning } from './buildInfo'

describe('buildInfo drift detection', () => {
  it('returns warning when UI and desktop backend commits differ', () => {
    const warning = detectBuildDriftWarning(
      {
        git_commit: 'ui-commit-123',
        branch: 'main',
        build_time: '2026-04-24T00:00:00Z',
        component: 'ui',
        package_version: '1.0.0',
      },
      {
        git_commit: 'desktop-commit-456',
        branch: 'main',
        build_time: '2026-04-24T00:00:00Z',
        component: 'desktop_backend',
        package_version: '1.0.0',
      },
    )

    expect(warning).toContain('不一致')
  })

  it('returns null when commits are aligned', () => {
    const warning = detectBuildDriftWarning(
      {
        git_commit: 'same-commit',
        branch: 'main',
        build_time: '2026-04-24T00:00:00Z',
        component: 'ui',
        package_version: '1.0.0',
      },
      {
        git_commit: 'same-commit',
        branch: 'main',
        build_time: '2026-04-24T00:00:00Z',
        component: 'desktop_backend',
        package_version: '1.0.0',
      },
    )

    expect(warning).toBeNull()
  })
})
