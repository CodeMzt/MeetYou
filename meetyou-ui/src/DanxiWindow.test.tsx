import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import DanxiWindow from './DanxiWindow'

describe('DanxiWindow', () => {
  it('renders compact danxi workspace sections and operation entrypoints', () => {
    const markup = renderToStaticMarkup(<DanxiWindow />)

    expect(markup).toContain('Danxi / 旦夕')
    expect(markup).toContain('直连登录')
    expect(markup).toContain('WebVPN')
    expect(markup).toContain('搜索 Danxi 帖子')
    expect(markup).toContain('站内消息')
    expect(markup).toContain('帖子流')
  })
})
