import { describe, expect, it } from 'vitest'
import { hasRunningResearchTasks, isResearchTaskRunning, RESEARCH_TASK_POLL_INTERVAL_MS } from './useMeetYou'

describe('useMeetYou research polling helpers', () => {
  it('detects running research tasks only', () => {
    expect(isResearchTaskRunning({ status: 'running' })).toBe(true)
    expect(isResearchTaskRunning({ status: 'RUNNING' })).toBe(true)
    expect(isResearchTaskRunning({ status: 'completed' })).toBe(false)
    expect(isResearchTaskRunning(null)).toBe(false)
    expect(hasRunningResearchTasks([{ status: 'planned' }, { status: 'running' }])).toBe(true)
    expect(hasRunningResearchTasks([{ status: 'failed' }, { status: 'cancelled' }])).toBe(false)
  })

  it('keeps the polling interval bounded for visible progress tracking', () => {
    expect(RESEARCH_TASK_POLL_INTERVAL_MS).toBeGreaterThanOrEqual(2000)
    expect(RESEARCH_TASK_POLL_INTERVAL_MS).toBeLessThanOrEqual(5000)
  })
})
