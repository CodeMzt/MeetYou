import { describe, expect, it } from 'vitest'
import { getMessageRelatedHoleId } from './danxiUtils'

describe('getMessageRelatedHoleId', () => {
  it('prefers explicit hole id fields', () => {
    expect(getMessageRelatedHoleId({ hole_id: 12345 })).toBe(12345)
    expect(getMessageRelatedHoleId({ target_hole_id: '67890' })).toBe(67890)
  })

  it('extracts hole id from message text and links', () => {
    expect(getMessageRelatedHoleId({ message: '你收到了一条来自帖子 #54321 的回复' })).toBe(54321)
    expect(getMessageRelatedHoleId({ url: 'https://example.com/holes/98765' })).toBe(98765)
  })

  it('returns null when no related hole id is available', () => {
    expect(getMessageRelatedHoleId({ message: '系统通知', id: 12 })).toBeNull()
  })
})
