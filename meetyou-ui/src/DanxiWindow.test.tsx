import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import DanxiWindow, { getDanxiPostPageCursor, mergeDanxiPostPages, resolveDanxiAuthAction } from './DanxiWindow'

describe('DanxiWindow', () => {
  it('renders compact danxi workspace sections and operation entrypoints', () => {
    const markup = renderToStaticMarkup(<DanxiWindow />)

    expect(markup).toContain('旦夕')
    expect(markup).toContain('直连登录')
    expect(markup).toContain('WebVPN')
    expect(markup).toContain('搜索旦夕帖子')
    expect(markup).toContain('站内消息')
    expect(markup).toContain('帖子流')
  })

  it('prefers fresh login when user has entered credentials even if a session already looks logged in', () => {
    expect(
      resolveDanxiAuthAction({
        sessionLoggedIn: true,
        email: 'user@example.com',
        password: 'correct-password',
      }),
    ).toBe('fresh_login')
  })

  it('only updates cookie when an existing session is logged in and no manual credentials were provided', () => {
    expect(
      resolveDanxiAuthAction({
        sessionLoggedIn: true,
        email: '',
        password: '',
      }),
    ).toBe('update_cookie')
  })

  it('falls back to a fresh core-side login when there is no logged in session to reuse', () => {
    expect(
      resolveDanxiAuthAction({
        sessionLoggedIn: false,
        email: '',
        password: '',
      }),
    ).toBe('fresh_login')
  })

  it('uses the server-provided Danxi post cursor before falling back to the recent-order timestamp', () => {
    expect(
      getDanxiPostPageCursor({
        count: 1,
        next_offset: '2026-05-07T00:10:00Z',
        items: [{ hole_id: 1, time_updated: '2026-05-07T00:09:00Z' }],
      }),
    ).toBe('2026-05-07T00:10:00Z')

    expect(
      getDanxiPostPageCursor({
        count: 1,
        items: [{ hole_id: 2, time_created: '2026-05-07T00:01:00Z', time_updated: '2026-05-07T00:05:00Z' }],
      }),
    ).toBe('2026-05-07T00:05:00Z')
  })

  it('deduplicates Danxi post pages by hole id when appending loaded pages', () => {
    const merged = mergeDanxiPostPages(
      { count: 2, items: [{ hole_id: 101 }, { hole_id: 102 }] },
      { count: 2, next_offset: 'cursor-2', items: [{ hole_id: 102 }, { hole_id: 103 }] },
    )

    expect(merged.count).toBe(3)
    expect(merged.next_offset).toBe('cursor-2')
    expect(merged.items.map((item) => item.hole_id)).toEqual([101, 102, 103])
  })
})
