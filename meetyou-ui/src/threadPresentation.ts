import type { RuntimeThread } from './types'

export type RuntimeThreadKind =
  | 'desktop'
  | 'wechat_provider'
  | 'wechat_chat'
  | 'feishu_provider'
  | 'feishu_chat'
  | 'scheduled'
  | 'other'

export interface RuntimeThreadPresentation {
  thread: RuntimeThread
  kind: RuntimeThreadKind
  title: string
  rawTitle: string
  tooltip: string
}

function normalizeTitle(value: string): string {
  return String(value || '').trim().toLowerCase()
}

export function classifyRuntimeThread(thread: RuntimeThread, defaultThreadId = ''): RuntimeThreadKind {
  const title = normalizeTitle(thread.title)
  if (thread.thread_id === defaultThreadId || title.includes('桌面') || title.includes('desktop') || title.includes('frontend')) {
    return 'desktop'
  }
  if (title.includes('scheduled job') || title.includes('定时') || title.includes('计划任务')) {
    return 'scheduled'
  }
  if ((title.includes('meetwechat') || title.includes('wechat') || title.includes('weixin') || title.includes('微信')) && title.includes('provider')) {
    return 'wechat_provider'
  }
  if ((title.includes('feishu') || title.includes('lark') || title.includes('飞书')) && title.includes('provider')) {
    return 'feishu_provider'
  }
  if (title.includes('meetwechat') || title.includes('wechat') || title.includes('weixin') || title.includes('微信')) {
    return 'wechat_chat'
  }
  if (title.includes('feishu') || title.includes('lark') || title.includes('飞书')) {
    return 'feishu_chat'
  }
  return 'other'
}

function baseTitleForThread(thread: RuntimeThread, kind: RuntimeThreadKind): string {
  const rawTitle = String(thread.title || '').trim()
  const title = normalizeTitle(rawTitle)
  if (kind === 'desktop') {
    return '桌面聊天'
  }
  if (kind === 'wechat_provider') {
    return '微信接入'
  }
  if (kind === 'feishu_provider') {
    return '飞书接入'
  }
  if (kind === 'wechat_chat') {
    if (title.includes('group') || title.includes('群')) {
      return '微信群聊'
    }
    if (title.includes('private') || title.includes('direct') || title.includes('私')) {
      return '微信私聊'
    }
    return '微信聊天'
  }
  if (kind === 'feishu_chat') {
    return '飞书聊天'
  }
  if (kind === 'scheduled') {
    return rawTitle.replace(/^scheduled job:\s*/i, '定时任务：') || '定时任务'
  }
  return rawTitle || `会话 ${thread.thread_id.slice(-6)}`
}

function duplicateIdentityKey(thread: RuntimeThread, kind: RuntimeThreadKind): string {
  const rawTitle = normalizeTitle(thread.title)
  if (kind === 'wechat_provider' || kind === 'feishu_provider') {
    return kind
  }
  if ((kind === 'wechat_chat' || kind === 'feishu_chat') && rawTitle) {
    return `${kind}:${rawTitle}`
  }
  return `thread:${thread.thread_id}`
}

function priorityForThread(
  thread: RuntimeThread,
  kind: RuntimeThreadKind,
  activeThreadId: string,
  defaultThreadId: string,
): number {
  if (thread.thread_id === defaultThreadId) {
    return 0
  }
  if (kind === 'desktop') {
    return 1
  }
  if (thread.thread_id === activeThreadId) {
    return 2
  }
  return 3
}

export function getVisibleRuntimeThreadItems(
  threads: RuntimeThread[],
  activeThreadId = '',
  defaultThreadId = '',
): RuntimeThreadPresentation[] {
  const prepared = threads.map((thread, index) => {
    const kind = classifyRuntimeThread(thread, defaultThreadId)
    return {
      thread,
      kind,
      index,
      priority: priorityForThread(thread, kind, activeThreadId, defaultThreadId),
      baseTitle: baseTitleForThread(thread, kind),
      duplicateKey: duplicateIdentityKey(thread, kind),
    }
  })

  prepared.sort((left, right) => left.priority - right.priority || left.index - right.index)

  const byIdentity = new Map<string, (typeof prepared)[number]>()
  for (const item of prepared) {
    const existing = byIdentity.get(item.duplicateKey)
    if (!existing || item.priority < existing.priority) {
      byIdentity.set(item.duplicateKey, item)
    }
  }

  const items = Array.from(byIdentity.values()).sort(
    (left, right) => left.priority - right.priority || left.index - right.index,
  )
  const counts = new Map<string, number>()
  for (const item of items) {
    counts.set(item.baseTitle, (counts.get(item.baseTitle) || 0) + 1)
  }

  const seen = new Map<string, number>()
  return items.map((item) => {
    const duplicateCount = counts.get(item.baseTitle) || 0
    const nextIndex = (seen.get(item.baseTitle) || 0) + 1
    seen.set(item.baseTitle, nextIndex)
    const title = duplicateCount > 1 ? `${item.baseTitle} ${nextIndex}` : item.baseTitle
    const rawTitle = String(item.thread.title || '').trim() || title
    const shortId = item.thread.thread_id.slice(-8)
    const tooltip = rawTitle === title ? `${title} · ${shortId}` : `${title} · ${rawTitle} · ${shortId}`
    return {
      thread: item.thread,
      kind: item.kind,
      title,
      rawTitle,
      tooltip,
    }
  })
}
