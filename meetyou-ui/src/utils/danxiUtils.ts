export type DanxiRecord = Record<string, unknown>

export function asRecord(value: unknown): DanxiRecord | null {
  if (typeof value !== 'object' || value === null) {
    return null
  }
  return value as DanxiRecord
}

export function stringifyFallback(value: unknown): string {
  if (typeof value === 'string' && value.trim()) {
    return value.trim()
  }
  if (typeof value === 'number') {
    return String(value)
  }
  return ''
}

export function getDivisionLabel(item: Record<string, unknown>): string {
  return (
    stringifyFallback(item.name) ||
    stringifyFallback(item.label) ||
    `分区 ${stringifyFallback(item.division_id) || stringifyFallback(item.id) || ''}`.trim()
  )
}

export function getPostSummary(item: Record<string, unknown>): string {
  const content =
    asRecord(asRecord(item.floors)?.first_floor)?.content ||
    item.content ||
    item.text ||
    item.title
  return (
    stringifyFallback(content) ||
    (JSON.stringify(item).substring(0, 100) + '...')
  )
}

export function getPostId(item: Record<string, unknown>): number | null {
  const candidate = item.hole_id ?? item.id
  return typeof candidate === 'number' ? candidate : null
}

export function getFloorId(item: DanxiRecord): number | null {
  const candidate = item.floor_id ?? item.id
  return typeof candidate === 'number' ? candidate : null
}

export function getFloorAuthor(item: DanxiRecord): string {
  return (
    stringifyFallback(item.anonyname) ||
    stringifyFallback(item.nickname) ||
    stringifyFallback(item.name) ||
    stringifyFallback(item.user_name) ||
    stringifyFallback(item.author) ||
    '匿名'
  )
}

export function getFloorContent(item: DanxiRecord): string {
  return (
    stringifyFallback(item.content) ||
    stringifyFallback(item.text) ||
    stringifyFallback(item.description) ||
    JSON.stringify(item, null, 2)
  )
}

export function getMessageTitle(item: DanxiRecord): string {
  return (
    stringifyFallback(item.message) ||
    stringifyFallback(item.title) ||
    stringifyFallback(item.subject) ||
    '消息通知'
  )
}

export function getMessageDescription(item: DanxiRecord): string {
  return (
    stringifyFallback(item.description) ||
    stringifyFallback(item.content) ||
    stringifyFallback(item.body) ||
    ''
  )
}

export function getMessageTimestamp(item: DanxiRecord): string {
  return formatTime(item.time_created || item.created_at || item.updated_at)
}

function toPositiveInt(value: unknown): number | null {
  if (typeof value === 'number' && Number.isInteger(value) && value > 0) {
    return value
  }
  if (typeof value === 'string' && /^\d+$/.test(value.trim())) {
    const parsed = Number(value.trim())
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null
  }
  return null
}

export function getMessageRelatedHoleId(item: DanxiRecord): number | null {
  const directKeys = [
    'hole_id',
    'post_id',
    'target_hole_id',
    'related_hole_id',
    'reply_hole_id',
    'thread_hole_id',
  ]
  for (const key of directKeys) {
    const candidate = toPositiveInt(item[key])
    if (candidate !== null) {
      return candidate
    }
  }

  const textCandidates = [
    stringifyFallback(item.message),
    stringifyFallback(item.title),
    stringifyFallback(item.subject),
    stringifyFallback(item.description),
    stringifyFallback(item.content),
    stringifyFallback(item.body),
    stringifyFallback(item.url),
    stringifyFallback(item.link),
  ].filter(Boolean)

  for (const text of textCandidates) {
    const matched =
      text.match(/(?:hole|post|帖子)\s*#?\s*(\d{1,10})/i) ||
      text.match(/#(\d{1,10})/) ||
      text.match(/\/holes\/(\d{1,10})/i)
    if (matched?.[1]) {
      const candidate = toPositiveInt(matched[1])
      if (candidate !== null) {
        return candidate
      }
    }
  }

  return null
}

export function formatTime(value: unknown): string {
  const text = stringifyFallback(value)
  if (!text) {
    return ''
  }
  return new Date(text).toLocaleString()
}

export function pickProfileEntries(profile: DanxiRecord | null): Array<[string, string]> {
  if (!profile) {
    return []
  }
  const preferredKeys: Array<[string, string]> = [
    ['nickname', '昵称'],
    ['name', '姓名'],
    ['user_id', '用户 ID'],
    ['email', '邮箱'],
    ['department', '院系'],
    ['grade', '年级'],
  ]
  const rows: Array<[string, string]> = []
  preferredKeys.forEach(([key, label]) => {
    const value = stringifyFallback(profile[key])
    if (value) {
      rows.push([label, value])
    }
  })
  if (rows.length) {
    return rows.slice(0, 4)
  }
  return Object.entries(profile)
    .map(([key, value]) => [key, stringifyFallback(value)] as [string, string])
    .filter(([, value]) => Boolean(value))
    .slice(0, 4)
}

function collectProfileIdentity(profile: DanxiRecord | null): Set<string> {
  const tokens = new Set<string>()
  if (!profile) {
    return tokens
  }
  ;['user_id', 'id', 'uid', 'email', 'nickname', 'name'].forEach((key) => {
    const value = stringifyFallback(profile[key])
    if (value) {
      tokens.add(value.toLowerCase())
    }
  })
  return tokens
}

export function canManageFloor(floor: DanxiRecord, profile: DanxiRecord | null): boolean {
  if (floor.can_edit === true || floor.can_delete === true || floor.is_owner === true) {
    return true
  }
  const profileIdentity = collectProfileIdentity(profile)
  if (!profileIdentity.size) {
    return false
  }
  const floorIdentityFields = ['user_id', 'uid', 'owner_id', 'author_id', 'email', 'nickname', 'name']
  return floorIdentityFields.some((key) => {
    const value = stringifyFallback(floor[key])
    return Boolean(value) && profileIdentity.has(value.toLowerCase())
  })
}
