import { describe, expect, it } from 'vitest'
import { normalizeAssistantDisplayText } from './displayText'

describe('normalizeAssistantDisplayText', () => {
  it('trims trailing blank lines and collapses excessive spacing outside code fences', () => {
    expect(normalizeAssistantDisplayText('first\n\n\n\nsecond\n\n')).toBe('first\n\nsecond')
  })

  it('preserves blank lines inside fenced code blocks', () => {
    const input = 'before\n\n\n```ts\nconst a = 1\n\n\nconst b = 2\n```\n\n\nafter\n'
    expect(normalizeAssistantDisplayText(input)).toBe('before\n\n```ts\nconst a = 1\n\n\nconst b = 2\n```\n\nafter')
  })
})
