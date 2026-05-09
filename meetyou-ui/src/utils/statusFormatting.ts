import {
  ConnectionState,
  RuntimeStateSnapshot,
  RuntimeHealthSnapshot,
  TurnActivity,
  RuntimeUsageSnapshot,
} from '../types'

export const RUNTIME_LABELS: Record<string, string> = {
  initializing: '初始化中',
  idle: '已就绪',
  thinking: '思考中',
  tool_calling: '使用工具中',
  answering: '生成回答中',
  waiting_confirm: '等待确认',
  waiting_human_input: '等待你补充信息',
  heartbeat: '后台运行中',
  error: '出现错误',
  shutting_down: '关闭中',
}

export const ACTIVITY_PHASE_LABELS: Record<string, string> = {
  routing: '路由',
  loading_context: '加载上下文',
  searching: '搜索',
  searching_web: '网页搜索',
  searching_knowledge: '知识检索',
  reading_sources: '读取来源',
  browsing_page: '浏览页面',
  updating_tasks: '任务更新',
  synthesizing: '整合结果',
  status: '状态',
}

export const ACTIVITY_STATUS_TITLES: Record<string, string> = {
  routing: '规划步骤中',
  loading_context: '加载上下文中',
  searching: '检索信息中',
  searching_web: '网页搜索中',
  searching_knowledge: '知识检索中',
  reading_sources: '阅读资料中',
  browsing_page: '查看页面中',
  updating_tasks: '整理任务中',
  synthesizing: '整合结果中',
  status: '处理中',
}

export const ACTIVITY_STATUS_DETAILS: Record<string, string> = {
  routing: '正在判断最合适的处理路径',
  loading_context: '正在整理历史消息、记忆和上下文',
  searching: '正在检索相关信息',
  searching_web: '正在搜索网页与来源',
  searching_knowledge: '正在检索知识与记忆',
  reading_sources: '正在阅读来源内容',
  browsing_page: '正在查看页面细节',
  updating_tasks: '正在整理任务与状态',
  synthesizing: '正在汇总工具结果并组织最终回答',
  status: '正在推进当前步骤',
}

export const STATUS_TOOL_LIMIT = 2

export type ToolChipSummary = {
  key: string
  label: string
  title: string
}

export type StatusPresentation = {
  title: string
  detail: string
  phaseLabel: string
  toolChips: ToolChipSummary[]
  hiddenToolCount: number
  hiddenToolsTitle: string
  activePhase: string | null
}

export function formatTokenCount(value: number): string {
  if (!value) {
    return '0'
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)}k`
  }
  return String(value)
}

export function getConnectionText(connectionState: ConnectionState): string {
  if (connectionState === 'connected') return '已连接'
  if (connectionState === 'connecting') return '连接中'
  return '未连接'
}

export function formatAssistantModeLabel(mode: string): string {
  const normalized = String(mode || '').trim().toLowerCase()
  if (normalized === 'general' || normalized === 'normal') return '通用'
  if (normalized === 'automation') return '自动化'
  if (normalized === 'office') return '自动化'
  if (normalized === 'research') return '研究'
  if (normalized === 'danxi') return '旦夕'
  return mode || '未设置'
}

export function formatExecutionTargetLabel(target: string): string {
  const normalized = String(target || '').trim().toLowerCase()
  if (normalized === 'core.local') return '核心本地'
  if (normalized === 'endpoint') return '指定端点'
  if (normalized === 'workspace_any_endpoint') return '工作区任意端点'
  if (normalized === 'prefer_endpoint_fallback_core') return '优先端点，失败回落核心服务'
  return target || '未设置'
}

export function formatResourceStatusLabel(status: string): string {
  const normalized = String(status || '').trim().toLowerCase()
  if (normalized === 'active') return '正常'
  if (normalized === 'archived') return '已归档'
  if (normalized === 'deleted') return '已删除'
  if (normalized === 'pending') return '待处理'
  return status || '未知'
}

export function formatCapabilityPolicyLabel(policy: string): string {
  const normalized = String(policy || '').trim().toLowerCase()
  if (normalized === 'allow_all') return '全部允许'
  if (normalized === 'allowlist') return '白名单'
  return policy || '未设置'
}

export function formatRoutingPolicyLabel(policy: string): string {
  const normalized = String(policy || '').trim().toLowerCase()
  if (normalized === 'balanced') return '均衡'
  if (normalized === 'prefer_origin_endpoint') return '优先来源端点'
  if (normalized === 'strict_preferred_endpoint') return '严格偏好端点'
  return policy || '未设置'
}

export function formatMemoryRankingPolicyLabel(policy: string): string {
  const normalized = String(policy || '').trim().toLowerCase()
  if (normalized === 'workspace_first') return '当前工作区优先'
  return policy || '未设置'
}

export function formatSourceProfileLabel(profile: string): string {
  const normalized = String(profile || '').trim().toLowerCase()
  if (normalized === 'workspace_local') return '工作区/本地知识'
  if (normalized === 'study_materials') return '学习资料'
  if (normalized === 'tech_updates') return '技术更新'
  if (normalized === 'policy_global') return '全球政策'
  if (normalized === 'policy_cn') return '中国政策'
  if (normalized === 'finance_macro') return '金融宏观'
  if (normalized === 'academic_biomed') return '学术/生物医学'
  if (normalized === 'cyber_threat') return '网络威胁'
  return profile || '未设置'
}

export function formatOperationStatusLabel(status: string): string {
  const normalized = String(status || '').trim().toLowerCase()
  if (normalized === 'queued') return '排队中'
  if (normalized === 'dispatching') return '分发中'
  if (normalized === 'running') return '执行中'
  if (normalized === 'waiting_approval') return '等待审批'
  if (normalized === 'succeeded') return '已完成'
  if (normalized === 'failed') return '失败'
  if (normalized === 'rejected') return '已拒绝'
  if (normalized === 'cancelled') return '已取消'
  return status || '未知'
}

export function getLatestActivity(turnActivities: TurnActivity[]): TurnActivity | null {
  if (turnActivities.length === 0) return null
  return turnActivities[turnActivities.length - 1]
}

export function normalizeStatusText(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

export function isToolListText(text: string): boolean {
  const normalized = normalizeStatusText(text)
  if (!normalized) return false

  const parts = normalized
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)

  return parts.length > 1 && parts.every((part) => /^[a-z0-9_./:-]+$/i.test(part))
}

export function getActivityPhaseLabel(phase: string): string {
  return ACTIVITY_PHASE_LABELS[phase] ?? phase
}

export function summarizeToolNames(toolNames: string[]): ToolChipSummary[] {
  const counts = new Map<string, number>()
  const orderedNames: string[] = []

  for (const rawName of toolNames) {
    const name = rawName.trim()
    if (!name) continue

    if (!counts.has(name)) {
      orderedNames.push(name)
    }
    counts.set(name, (counts.get(name) ?? 0) + 1)
  }

  return orderedNames.map((name) => {
    const count = counts.get(name) ?? 1
    const label = count > 1 ? `${name} ×${count}` : name
    return {
      key: name,
      label,
      title: label,
    }
  })
}

export function getActivityDetail(activity: TurnActivity | null): string {
  if (!activity) return ''
  return ACTIVITY_STATUS_DETAILS[activity.phase] ?? activity.content
}

export function getRuntimeTitle(runtimeSnapshot: RuntimeStateSnapshot | null, connectionState: ConnectionState): string {
  return buildStatusPresentation(connectionState, runtimeSnapshot, null, []).title
}

export function buildStatusPresentation(
  connectionState: ConnectionState,
  runtimeSnapshot: RuntimeStateSnapshot | null,
  healthSnapshot: RuntimeHealthSnapshot | null,
  turnActivities: TurnActivity[],
): StatusPresentation {
  const latestActivity = getLatestActivity(turnActivities)
  const activePhase = latestActivity?.phase ?? null
  const summarizedTools = summarizeToolNames(
    runtimeSnapshot?.active_tools?.length
      ? runtimeSnapshot.active_tools
      : latestActivity?.toolNames ?? [],
  )
  const toolChips = summarizedTools.slice(0, STATUS_TOOL_LIMIT)
  const hiddenToolCount = Math.max(0, summarizedTools.length - STATUS_TOOL_LIMIT)
  const hiddenToolsTitle =
    hiddenToolCount > 0 ? summarizedTools.slice(STATUS_TOOL_LIMIT).map((item) => item.title).join(', ') : ''
  const translatedRuntimeDetail = runtimeSnapshot?.detail ?? ''
  const activityTitle = activePhase ? ACTIVITY_STATUS_TITLES[activePhase] ?? getActivityPhaseLabel(activePhase) : ''
  const activityDetail = getActivityDetail(latestActivity)

  if (connectionState !== 'connected') {
    return {
      title: connectionState === 'connecting' ? '正在连接服务' : '等待后端服务',
      detail: connectionState === 'connecting' ? '正在建立桌面端与后端的连接' : '后端恢复后会自动重连',
      phaseLabel: connectionState === 'connecting' ? '连接中' : '未连接',
      toolChips: [],
      hiddenToolCount: 0,
      hiddenToolsTitle: '',
      activePhase: null,
    }
  }

  if (!runtimeSnapshot) {
    if (healthSnapshot && (!healthSnapshot.ready || healthSnapshot.degraded)) {
      return {
        title: healthSnapshot.degraded ? '服务降级运行中' : '服务尚未就绪',
        detail: healthSnapshot.degraded ? '部分能力可能暂时受限' : '后端正在完成启动或恢复',
        phaseLabel: healthSnapshot.degraded ? '降级' : '启动中',
        toolChips: [],
        hiddenToolCount: 0,
        hiddenToolsTitle: '',
        activePhase: null,
      }
    }
    return {
      title: '已就绪',
      detail: '随时可以开始对话',
      phaseLabel: '就绪',
      toolChips: [],
      hiddenToolCount: 0,
      hiddenToolsTitle: '',
      activePhase: null,
    }
  }

  switch (runtimeSnapshot.status) {
    case 'thinking':
      return {
        title: RUNTIME_LABELS.thinking,
        detail: translatedRuntimeDetail || activityDetail || '正在理解问题并规划下一步',
        phaseLabel: '模型推理',
        toolChips: [],
        hiddenToolCount: 0,
        hiddenToolsTitle: '',
        activePhase,
      }
    case 'tool_calling': {
      const detail =
        activityDetail ||
        (!isToolListText(runtimeSnapshot.detail) ? translatedRuntimeDetail : '') ||
        (summarizedTools.length > 0 ? `已调用 ${summarizedTools.map((item) => item.label).join('、')}` : '正在执行工具链')

      return {
        title: activityTitle || RUNTIME_LABELS.tool_calling,
        detail,
        phaseLabel: activePhase ? getActivityPhaseLabel(activePhase) : '工具调用',
        toolChips,
        hiddenToolCount,
        hiddenToolsTitle,
        activePhase,
      }
    }
    case 'answering':
      return {
        title: RUNTIME_LABELS.answering,
        detail: translatedRuntimeDetail || activityDetail || '正在整理并输出最终回答',
        phaseLabel: activePhase === 'synthesizing' ? '整合结果' : '回答生成',
        toolChips: [],
        hiddenToolCount: 0,
        hiddenToolsTitle: '',
        activePhase,
      }
    case 'waiting_confirm':
      return {
        title: RUNTIME_LABELS.waiting_confirm,
        detail: translatedRuntimeDetail || '需要你确认后才能继续执行',
        phaseLabel: '待确认',
        toolChips,
        hiddenToolCount,
        hiddenToolsTitle,
        activePhase,
      }
    case 'waiting_human_input':
      return {
        title: RUNTIME_LABELS.waiting_human_input,
        detail: translatedRuntimeDetail || '需要你补充信息后才能继续执行',
        phaseLabel: '待补充',
        toolChips,
        hiddenToolCount,
        hiddenToolsTitle,
        activePhase,
      }
    case 'initializing':
    case 'heartbeat':
    case 'shutting_down':
    case 'error':
      return {
        title: RUNTIME_LABELS[runtimeSnapshot.status] ?? runtimeSnapshot.status,
        detail: translatedRuntimeDetail || (runtimeSnapshot.status === 'error' ? '请稍后重试' : '服务保持就绪'),
        phaseLabel: RUNTIME_LABELS[runtimeSnapshot.status] ?? runtimeSnapshot.status,
        toolChips: [],
        hiddenToolCount: 0,
        hiddenToolsTitle: '',
        activePhase,
      }
    case 'idle':
    default:
      return {
        title: RUNTIME_LABELS[runtimeSnapshot.status] ?? runtimeSnapshot.status,
        detail: translatedRuntimeDetail || '随时可以继续对话',
        phaseLabel: '就绪',
        toolChips: [],
        hiddenToolCount: 0,
        hiddenToolsTitle: '',
        activePhase,
      }
  }
}

export function getUsagePillText(usageSnapshot: RuntimeUsageSnapshot | null): string {
  if (!usageSnapshot) return '暂无用量'
  return `${formatTokenCount(usageSnapshot.last_turn_usage.total_tokens)} / ${formatTokenCount(usageSnapshot.context_limit_tokens)}`
}
