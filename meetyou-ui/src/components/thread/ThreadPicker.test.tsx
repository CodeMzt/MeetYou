import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import ThreadPicker from './ThreadPicker'
import type { RuntimeThreadPresentation } from '../../threadPresentation'

function item(thread_id: string, title: string, rawTitle = title): RuntimeThreadPresentation {
  return {
    thread: {
      thread_id,
      title: rawTitle,
      home_workspace_id: 'personal',
      workspace_id: 'personal',
      status: 'active',
      summary: '',
    },
    kind: 'desktop',
    title,
    rawTitle,
    tooltip: `${title} · ${rawTitle}`,
  }
}

describe('ThreadPicker', () => {
  it('renders the active thread as a compact trigger', () => {
    const markup = renderToStaticMarkup(
      <ThreadPicker
        items={[item('thr_desktop', '桌面聊天'), item('thr_wechat', '微信接入', 'MeetWeChat Provider')]}
        activeThreadId="thr_desktop"
        defaultThreadId="thr_desktop"
        onSelectThread={vi.fn()}
        onCreateThread={vi.fn()}
        onDeleteThread={vi.fn()}
      />,
    )

    expect(markup).toContain('桌面聊天')
    expect(markup).toContain('aria-haspopup="listbox"')
    expect(markup).not.toContain('MeetWeChat Provider')
  })
})
