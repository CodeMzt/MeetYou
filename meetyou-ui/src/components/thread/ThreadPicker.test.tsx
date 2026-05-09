import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import ThreadPicker, { getThreadDeleteTargetIds } from './ThreadPicker'
import type { RuntimeThreadPresentation } from '../../threadPresentation'

function item(thread_id: string, title: string, rawTitle = title): RuntimeThreadPresentation {
  return {
    thread: {
      thread_id,
      title: rawTitle,
      home_workspace_id: 'personal',
      workspace_id: 'personal',
      project_id: '',
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
        onSelectThread={vi.fn()}
        onCreateThread={vi.fn()}
        onDeleteThread={vi.fn()}
      />,
    )

    expect(markup).toContain('桌面聊天')
    expect(markup).toContain('aria-haspopup="listbox"')
    expect(markup).not.toContain('MeetWeChat Provider')
  })

  it('keeps a create entry visible for an empty project thread list', () => {
    const markup = renderToStaticMarkup(
      <ThreadPicker
        items={[]}
        activeThreadId=""
        onSelectThread={vi.fn()}
        onCreateThread={vi.fn()}
        onDeleteThread={vi.fn()}
      />,
    )

    expect(markup).toContain('新会话')
    expect(markup).toContain('aria-haspopup="listbox"')
  })

  it('groups legacy Desktop Chat cleanup targets and deletes the active one last', () => {
    const items = [
      item('thr_active', 'Desktop Chat 1', 'Desktop Chat'),
      item('thr_old_a', 'Desktop Chat 2', 'Desktop Chat'),
      item('thr_named', '新会话', '新会话'),
      item('thr_old_b', 'Desktop Chat 3', 'Desktop Chat'),
    ]

    expect(getThreadDeleteTargetIds(items, items[1], 'thr_active')).toEqual([
      'thr_old_a',
      'thr_old_b',
      'thr_active',
    ])
    expect(getThreadDeleteTargetIds(items, items[2], 'thr_active')).toEqual(['thr_named'])
  })
})
