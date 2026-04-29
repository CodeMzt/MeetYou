import { describe, expect, it } from 'vitest'
import { getVisibleRuntimeThreadItems } from './threadPresentation'
import type { RuntimeThread } from './types'

function thread(thread_id: string, title: string): RuntimeThread {
  return {
    thread_id,
    title,
    home_workspace_id: 'personal',
    workspace_id: 'personal',
    status: 'active',
    summary: '',
  }
}

describe('threadPresentation', () => {
  it('keeps the default desktop thread first and collapses repeated provider management threads', () => {
    const items = getVisibleRuntimeThreadItems(
      [
        thread('thr_wechat_new', 'MeetWeChat Provider'),
        thread('thr_feishu_new', 'Feishu Provider'),
        thread('thr_desktop', '桌面聊天'),
        thread('thr_wechat_old', 'MeetWeChat Provider'),
        thread('thr_feishu_old', 'Feishu Provider'),
      ],
      'thr_wechat_old',
      'thr_desktop',
    )

    expect(items.map((item) => item.thread.thread_id)).toEqual([
      'thr_desktop',
      'thr_wechat_old',
      'thr_feishu_new',
    ])
    expect(items.map((item) => item.title)).toEqual(['桌面聊天', '微信接入', '飞书接入'])
  })

  it('keeps genuinely different external chat threads and labels them clearly', () => {
    const items = getVisibleRuntimeThreadItems(
      [
        thread('thr_wx_group_a', 'MeetWeChat group chat-a'),
        thread('thr_wx_group_b', 'MeetWeChat group chat-b'),
        thread('thr_feishu_chat', 'Feishu Chat oc_123'),
        thread('thr_desktop', 'Desktop Chat'),
      ],
      '',
      'thr_desktop',
    )

    expect(items.map((item) => item.title)).toEqual(['桌面聊天', '微信群聊 1', '微信群聊 2', '飞书聊天'])
    expect(items[1]?.tooltip).toContain('MeetWeChat group chat-a')
    expect(items[2]?.tooltip).toContain('MeetWeChat group chat-b')
  })
})
