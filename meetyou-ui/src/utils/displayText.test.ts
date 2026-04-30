import { describe, expect, it } from 'vitest'
import { normalizeAssistantDisplayText } from './displayText'

describe('normalizeAssistantDisplayText', () => {
  it('removes transport-only boundary blank lines without flattening intentional paragraphs', () => {
    expect(normalizeAssistantDisplayText('\n\nFirst paragraph\n\nSecond paragraph\n\n')).toBe(
      'First paragraph\n\nSecond paragraph',
    )
  })

  it('keeps fenced code block spacing intact', () => {
    expect(normalizeAssistantDisplayText('\n```ts\n\nconst value = 1\n```\n')).toBe(
      '```ts\n\nconst value = 1\n```',
    )
  })
})
