import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import DanxiWindow, { resolveDanxiAuthAction } from './DanxiWindow'

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
})
