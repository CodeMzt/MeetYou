import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  Database,
  Gauge,
  Loader2,
  Minus,
  Pin,
  PinOff,
  Send,
  Settings,
  ShieldAlert,
  Sparkles,
  Wrench,
  X,
} from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import GlassSelect from './components/GlassSelect'
import { useMeetYou } from './hooks/useMeetYou'
import type {
  ChatTurn,
  ConnectionState,
  RuntimeStateSnapshot,
  RuntimeUsageSnapshot,
  ThinkingOverride,
  TurnActivity,
} from './types'

const THINKING_OPTIONS: Array<{ label: string; value: ThinkingOverride }> = [
  { label: '跟随默认', value: 'default' },
  { label: '关闭', value: 'off' },
  { label: '低', value: 'low' },
  { label: '中', value: 'medium' },
  { label: '高', value: 'high' },
]

const RUNTIME_LABELS: Record<string, string> = {
  initializing: '初始化中',
  idle: '已就绪',
  thinking: '思考中',
  tool_calling: '使用工具中',
  answering: '生成回答中',
  waiting_confirm: '等待确认',
  heartbeat: '后台运行中',
  error: '出现错误',
  shutting_down: '关闭中',
}

const DETAIL_LABELS: Record<string, string> = {
  'Starting turn': '开始处理本轮请求',
  'Calling model': '正在调用模型',
  'Generating answer': '正在生成回答',
  'Waiting for confirmation': '等待你的确认',
  'Resuming tool call': '继续执行工具调用',
}

const ACTIVITY_PHASE_LABELS: Record<string, string> = {
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

const ACTIVITY_STATUS_TITLES: Record<string, string> = {
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

const ACTIVITY_STATUS_DETAILS: Record<string, string> = {
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

const STATUS_TOOL_LIMIT = 2

type ToolChipSummary = {
  key: string
  label: string
  title: string
}

type StatusPresentation = {
  title: string
  detail: string
  phaseLabel: string
  toolChips: ToolChipSummary[]
  hiddenToolCount: number
  hiddenToolsTitle: string
  activePhase: string | null
}

function formatTokenCount(value: number): string {
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

function getConnectionText(connectionState: ConnectionState): string {
  if (connectionState === 'connected') {
    return '已连接'
  }
  if (connectionState === 'connecting') {
    return '连接中'
  }
  return '未连接'
}

function getLatestActivity(turnActivities: TurnActivity[]): TurnActivity | null {
  if (turnActivities.length === 0) {
    return null
  }
  return turnActivities[turnActivities.length - 1]
}

function normalizeStatusText(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

function compactStatusText(text: string, maxLength = 92): string {
  const normalized = normalizeStatusText(text)
  if (!normalized) {
    return ''
  }

  if (normalized.length <= maxLength) {
    return normalized
  }

  return `${normalized.slice(0, maxLength - 1)}…`
}

function isToolListText(text: string): boolean {
  const normalized = normalizeStatusText(text)
  if (!normalized) {
    return false
  }

  const parts = normalized
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)

  return parts.length > 1 && parts.every((part) => /^[a-z0-9_./:-]+$/i.test(part))
}

function translateDetailText(detail: string): string {
  if (!detail) {
    return ''
  }

  if (DETAIL_LABELS[detail]) {
    return DETAIL_LABELS[detail]
  }

  if (detail === 'Synthesizing final answer') {
    return '正在汇总工具结果并组织最终回答'
  }

  return compactStatusText(detail)
}

function getActivityPhaseLabel(phase: string): string {
  return ACTIVITY_PHASE_LABELS[phase] ?? phase
}

function summarizeToolNames(toolNames: string[]): ToolChipSummary[] {
  const counts = new Map<string, number>()
  const orderedNames: string[] = []

  for (const rawName of toolNames) {
    const name = rawName.trim()
    if (!name) {
      continue
    }

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

function getActivityDetail(activity: TurnActivity | null): string {
  if (!activity) {
    return ''
  }

  const translatedContent = translateDetailText(activity.content)
  if (translatedContent && !isToolListText(translatedContent)) {
    return translatedContent
  }

  return ACTIVITY_STATUS_DETAILS[activity.phase] ?? ''
}

function getRuntimeTitle(runtimeSnapshot: RuntimeStateSnapshot | null, connectionState: ConnectionState): string {
  return buildStatusPresentation(connectionState, runtimeSnapshot, []).title
}

function buildStatusPresentation(
  connectionState: ConnectionState,
  runtimeSnapshot: RuntimeStateSnapshot | null,
  turnActivities: TurnActivity[],
): StatusPresentation {
  const latestActivity = getLatestActivity(turnActivities)
  const activePhase = latestActivity?.phase ?? null
  const summarizedTools = summarizeToolNames(
    runtimeSnapshot?.active_tools.length
      ? runtimeSnapshot.active_tools
      : latestActivity?.toolNames ?? [],
  )
  const toolChips = summarizedTools.slice(0, STATUS_TOOL_LIMIT)
  const hiddenToolCount = Math.max(0, summarizedTools.length - STATUS_TOOL_LIMIT)
  const hiddenToolsTitle =
    hiddenToolCount > 0 ? summarizedTools.slice(STATUS_TOOL_LIMIT).map((item) => item.title).join(', ') : ''
  const translatedRuntimeDetail = translateDetailText(runtimeSnapshot?.detail ?? '')
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
    return {
      title: '已连接，等待下一条消息',
      detail: '随时可以继续对话',
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
        title: translatedRuntimeDetail === '正在调用模型' ? '分析问题中' : RUNTIME_LABELS.thinking,
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
    case 'initializing':
    case 'heartbeat':
    case 'shutting_down':
    case 'error':
      return {
        title: RUNTIME_LABELS[runtimeSnapshot.status] ?? runtimeSnapshot.status,
        detail:
          translatedRuntimeDetail ||
          (runtimeSnapshot.status === 'heartbeat'
            ? '服务保持就绪'
            : runtimeSnapshot.status === 'error'
              ? '请稍后重试'
              : ''),
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

function getUsagePillText(usageSnapshot: RuntimeUsageSnapshot | null): string {
  if (!usageSnapshot) {
    return '暂无用量'
  }
  return `${formatTokenCount(usageSnapshot.last_turn_usage.total_tokens)} / ${formatTokenCount(usageSnapshot.context_limit_tokens)}`
}

function StatusIcon({
  runtimeSnapshot,
  connectionState,
  activePhase,
}: {
  runtimeSnapshot: RuntimeStateSnapshot | null
  connectionState: ConnectionState
  activePhase: string | null
}) {
  if (connectionState !== 'connected') {
    return <Loader2 size={14} className={connectionState === 'connecting' ? 'spin' : ''} />
  }

  if (!runtimeSnapshot || runtimeSnapshot.status === 'idle') {
    return <Sparkles size={14} />
  }

  if (runtimeSnapshot.status === 'thinking') {
    return <BrainCircuit size={14} className="pulse" />
  }

  if (runtimeSnapshot.status === 'waiting_confirm') {
    return <ShieldAlert size={14} />
  }

  if (runtimeSnapshot.status === 'tool_calling') {
    if (activePhase === 'loading_context') {
      return <Database size={14} />
    }
    if (activePhase === 'synthesizing') {
      return <BrainCircuit size={14} className="pulse" />
    }
    return <Wrench size={14} />
  }

  if (runtimeSnapshot.status === 'answering') {
    return <Send size={14} />
  }

  return <Sparkles size={14} />
}

function ReasoningBlock({ text, isStreaming }: { text: string; isStreaming: boolean }) {
  const [expanded, setExpanded] = useState(false)

  if (!text) {
    return null
  }

  return (
    <div className="turn-block">
      <button className="turn-block-header" onClick={() => setExpanded((current) => !current)}>
        <div className="turn-block-title">
          <BrainCircuit size={14} className={isStreaming ? 'pulse' : ''} />
          <span>{isStreaming ? '正在推理' : '推理摘要'}</span>
        </div>
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="turn-block-body reasoning-body"
          >
            <div>{text}</div>
            {isStreaming && <span className="cursor-blink">▍</span>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function ActivityBlock({ activities, isStreaming }: { activities: TurnActivity[]; isStreaming: boolean }) {
  const [expanded, setExpanded] = useState(false)

  if (activities.length === 0) {
    return null
  }

  const headerText = isStreaming ? '正在使用工具' : '工具活动'

  return (
    <div className="turn-block">
      <button className="turn-block-header" onClick={() => setExpanded((current) => !current)}>
        <div className="turn-block-title">
          <Wrench size={14} />
          <span>{headerText}</span>
        </div>
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="turn-block-body"
          >
            <div className="activity-list">
              {activities.map((activity) => (
                <div key={activity.id} className="activity-item">
                  <div className="activity-line">
                    <span className="activity-phase">{getActivityPhaseLabel(activity.phase)}</span>
                    {activity.toolNames.length > 0 && (
                      <span className="activity-tool-tag" title={activity.toolNames.join(', ')}>
                        {activity.toolNames.join(', ')}
                      </span>
                    )}
                  </div>
                  <div className="activity-text">{activity.content}</div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function UsagePanel({ usageSnapshot }: { usageSnapshot: RuntimeUsageSnapshot | null }) {
  if (!usageSnapshot) {
    return (
      <div className="usage-panel">
        <div className="usage-panel-header">
          <Gauge size={14} />
          <span>Token / Context</span>
        </div>
        <div className="usage-empty">暂无本会话的 token 或上下文统计。</div>
      </div>
    )
  }

  const { context_breakdown: contextBreakdown, last_turn_usage: lastTurnUsage, session_totals: sessionTotals } =
    usageSnapshot

  return (
    <div className="usage-panel">
      <div className="usage-panel-header">
        <Gauge size={14} />
        <span>Token / Context</span>
      </div>

      <div className="usage-grid">
        <div className="usage-stat">
          <span className="usage-label">本轮总计</span>
          <strong>{formatTokenCount(lastTurnUsage.total_tokens)}</strong>
        </div>
        <div className="usage-stat">
          <span className="usage-label">会话总计</span>
          <strong>{formatTokenCount(sessionTotals.total_tokens)}</strong>
        </div>
        <div className="usage-stat">
          <span className="usage-label">当前上下文</span>
          <strong>{formatTokenCount(usageSnapshot.current_context_tokens_estimated)}</strong>
        </div>
        <div className="usage-stat">
          <span className="usage-label">上下文上限</span>
          <strong>{formatTokenCount(usageSnapshot.context_limit_tokens)}</strong>
        </div>
      </div>

      <div className="usage-section">
        <div className="usage-section-title">本轮消耗</div>
        <div className="usage-inline-list">
          <span>Prompt {formatTokenCount(lastTurnUsage.prompt_tokens)}</span>
          <span>Completion {formatTokenCount(lastTurnUsage.completion_tokens)}</span>
          <span>Reasoning {formatTokenCount(lastTurnUsage.reasoning_tokens)}</span>
        </div>
      </div>

      <div className="usage-section">
        <div className="usage-section-title">会话累计</div>
        <div className="usage-inline-list">
          <span>Prompt {formatTokenCount(sessionTotals.prompt_tokens)}</span>
          <span>Completion {formatTokenCount(sessionTotals.completion_tokens)}</span>
          <span>Reasoning {formatTokenCount(sessionTotals.reasoning_tokens)}</span>
          <span>{sessionTotals.turn_count} 轮</span>
        </div>
      </div>

      <div className="usage-section">
        <div className="usage-section-title">上下文构成</div>
        <div className="usage-breakdown">
          <span>System {formatTokenCount(contextBreakdown.system)}</span>
          <span>History {formatTokenCount(contextBreakdown.history)}</span>
          <span>Tools {formatTokenCount(contextBreakdown.tool_history)}</span>
          <span>Memory {formatTokenCount(contextBreakdown.memory_context)}</span>
          <span>Policy {formatTokenCount(contextBreakdown.policy)}</span>
          <span>Input {formatTokenCount(contextBreakdown.current_input)}</span>
          <span>Proprioception {formatTokenCount(contextBreakdown.proprioception)}</span>
        </div>
      </div>

      <div className="usage-footer">来源：{usageSnapshot.usage_source || 'unknown'}</div>
    </div>
  )
}

function StatusStrip({
  connectionState,
  runtimeSnapshot,
  turnActivities,
}: {
  connectionState: ConnectionState
  runtimeSnapshot: RuntimeStateSnapshot | null
  turnActivities: TurnActivity[]
}) {
  const presentation = buildStatusPresentation(connectionState, runtimeSnapshot, turnActivities)

  return (
    <div className="status-strip">
      <div className="status-strip-top">
        <div className="status-strip-main">
          <div className="status-icon">
            <StatusIcon
              runtimeSnapshot={runtimeSnapshot}
              connectionState={connectionState}
              activePhase={presentation.activePhase}
            />
          </div>
          <div className="status-copy">
            <div className="status-title">{presentation.title}</div>
            <div className="status-detail">{presentation.detail || '随时可以继续对话'}</div>
          </div>
        </div>
        <div className="status-phase-chip">{presentation.phaseLabel}</div>
      </div>
      {(presentation.toolChips.length > 0 || presentation.hiddenToolCount > 0) && (
        <div className="status-strip-tools">
          {presentation.toolChips.map((tool) => (
            <span key={tool.key} className="tool-chip" title={tool.title}>
              {tool.label}
            </span>
          ))}
          {presentation.hiddenToolCount > 0 && (
            <span className="tool-chip tool-chip-more" title={presentation.hiddenToolsTitle}>
              +{presentation.hiddenToolCount}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

function TurnBody({ turn, runtimeSnapshot }: { turn: ChatTurn; runtimeSnapshot: RuntimeStateSnapshot | null }) {
  const placeholderText =
    turn.isStreaming && !turn.content && !turn.reasoning && turn.activities.length === 0
      ? getRuntimeTitle(runtimeSnapshot, 'connected')
      : ''

  return (
    <>
      {turn.role === 'assistant' && (
        <>
          <ActivityBlock activities={turn.activities} isStreaming={turn.isStreaming} />
          <ReasoningBlock text={turn.reasoning} isStreaming={turn.isStreaming && !turn.content} />
        </>
      )}
      {turn.content ? <div>{turn.content}</div> : placeholderText ? <div className="message-placeholder">{placeholderText}</div> : null}
      {turn.isStreaming && turn.content && <span className="cursor-blink">▍</span>}
      {turn.error && <div className="message-error">{turn.error}</div>}
    </>
  )
}

export default function App() {
  const {
    messages,
    sendMessage,
    connectionState,
    connected,
    runtimeSnapshot,
    usageSnapshot,
    turnActivities,
    confirmRequest,
    sendConfirmResponse,
  } = useMeetYou('http://127.0.0.1:8000')

  const [inputVal, setInputVal] = useState('')
  const [isPinned, setIsPinned] = useState(true)
  const [usagePanelOpen, setUsagePanelOpen] = useState(false)
  const [thinkingOverride, setThinkingOverride] = useState<ThinkingOverride>('default')

  const messagesEndRef = useRef<HTMLDivElement>(null)

  const connectionText = getConnectionText(connectionState)
  const usagePillText = getUsagePillText(usageSnapshot)

  const inputPlaceholder = useMemo(() => {
    if (!connected) {
      return connectionState === 'connecting' ? '正在连接后端服务…' : '等待后端服务启动…'
    }
    if (confirmRequest) {
      return '请先处理确认请求'
    }
    if (runtimeSnapshot?.status === 'tool_calling') {
      return '工具执行中，请稍候…'
    }
    return '输入消息，按 Enter 发送'
  }, [confirmRequest, connected, connectionState, runtimeSnapshot])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [confirmRequest, messages, runtimeSnapshot?.status])

  const handleClose = () => window.ipcRenderer?.send('window-close')
  const handleMinimize = () => window.ipcRenderer?.send('window-minimize')

  const togglePin = () => {
    const nextPinned = !isPinned
    setIsPinned(nextPinned)
    window.ipcRenderer?.send('window-toggle-top', nextPinned)
  }

  const handleSend = () => {
    if (!inputVal.trim() || !connected || confirmRequest) {
      return
    }
    void sendMessage(inputVal, thinkingOverride)
    setInputVal('')
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="app-container" style={{ opacity: 0.95 }}>
      <div className="titlebar">
        <div className="titlebar-title">
          MeetYou
          <span
            className={`status-dot ${connectionState}`}
            title={connectionText}
          />
        </div>
        <div className="titlebar-spacer" />
        <div className="actions">
          <button
            className={`usage-pill ${usagePanelOpen ? 'active' : ''}`}
            onClick={() => setUsagePanelOpen((current) => !current)}
            title="查看 token / context 统计"
          >
            <Gauge size={13} />
            <span>{usagePillText}</span>
          </button>
          <button
            className={`icon-btn ${isPinned ? 'active' : ''}`}
            onClick={togglePin}
            title={isPinned ? '取消置顶' : '置顶窗口'}
          >
            {isPinned ? <Pin size={16} /> : <PinOff size={16} />}
          </button>
          <button className="icon-btn" onClick={() => window.ipcRenderer?.send('open-dashboard')} title="记忆图谱">
            <Database size={16} />
          </button>
          <button className="icon-btn" onClick={() => window.ipcRenderer?.send('open-settings')} title="设置">
            <Settings size={16} />
          </button>
        </div>
        <div className="window-controls" style={{ marginLeft: 8 }}>
          <button className="win-btn minimize" onClick={handleMinimize} title="最小化">
            <Minus size={14} />
          </button>
          <button className="win-btn close" onClick={handleClose} title="关闭">
            <X size={14} />
          </button>
        </div>
      </div>

      <div className="content-area">
        {usagePanelOpen && <UsagePanel usageSnapshot={usageSnapshot} />}

        <StatusStrip
          connectionState={connectionState}
          runtimeSnapshot={runtimeSnapshot}
          turnActivities={turnActivities}
        />

        <AnimatePresence initial={false}>
          {messages.length === 0 && (
            <motion.div className="empty-state" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <div className="empty-copy">
                {connected ? '随时可以开始对话。' : '等待后端服务启动后即可使用。'}
              </div>
            </motion.div>
          )}

          {messages.map((message) => (
            <motion.div
              key={message.id}
              className={`message ${message.role}`}
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: 'spring', stiffness: 380, damping: 28 }}
            >
              <div className="message-inner">
                <TurnBody turn={message} runtimeSnapshot={runtimeSnapshot} />
              </div>
            </motion.div>
          ))}

          {confirmRequest && (
            <motion.div
              className="confirm-modal"
              initial={{ opacity: 0, y: 10, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
            >
              <div className="confirm-header">
                <ShieldAlert size={16} color="#ff3b30" />
                <span>危险操作确认</span>
              </div>
              <div className="confirm-body">{confirmRequest.content}</div>
              <div className="confirm-actions">
                <button className="btn-reject" onClick={() => sendConfirmResponse(confirmRequest.requestId, false)}>
                  拒绝
                </button>
                <button className="btn-accept" onClick={() => sendConfirmResponse(confirmRequest.requestId, true)}>
                  允许
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <div ref={messagesEndRef} />
      </div>

      <div className="input-container">
        <div className="composer-row">
        <div className="input-toolbar">
          <label className="thinking-label" htmlFor="thinking-override">
            本次推理
          </label>
          <GlassSelect
            id="thinking-override"
            wrapperClassName="thinking-select-wrap"
            value={thinkingOverride}
            onChange={(event) => setThinkingOverride(event.target.value as ThinkingOverride)}
            disabled={!connected || Boolean(confirmRequest)}
          >
            {THINKING_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </GlassSelect>
        </div>
        <div className="input-row">
          <input
            className="chat-input"
            placeholder={inputPlaceholder}
            value={inputVal}
            onChange={(event) => setInputVal(event.target.value)}
            onKeyDown={onKeyDown}
            disabled={!connected || Boolean(confirmRequest)}
            autoFocus
          />
          <button
            className="send-btn"
            onClick={handleSend}
            disabled={!inputVal.trim() || !connected || Boolean(confirmRequest)}
          >
            <Send size={16} />
          </button>
        </div>
        </div>
      </div>

      <style>{`
        .titlebar-spacer {
          flex: 1;
        }
        .cursor-blink {
          display: inline-block;
          width: 8px;
          animation: blink 1s step-end infinite;
          margin-left: 2px;
          color: var(--accent-color);
        }
        .spin {
          animation: spin 1s linear infinite;
        }
        .status-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          display: inline-block;
          background: #8e8e93;
        }
        .status-dot.connected {
          background: #34c759;
        }
        .status-dot.connecting {
          background: #ff9f0a;
        }
        .status-dot.disconnected {
          background: #ff3b30;
        }
        .usage-pill {
          border: 1px solid var(--glass-border);
          background: rgba(128, 128, 128, 0.06);
          color: var(--text-secondary);
          border-radius: 999px;
          padding: 0 10px;
          height: 28px;
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .usage-pill:hover,
        .usage-pill.active {
          color: var(--text-primary);
          border-color: rgba(0, 102, 204, 0.25);
          background: rgba(0, 102, 204, 0.08);
        }
        .status-strip {
          display: flex;
          flex-direction: column;
          gap: 8px;
          padding: 11px 13px 12px;
          border-radius: var(--radius-md);
          border: 1px solid var(--glass-border);
          background: rgba(128, 128, 128, 0.05);
        }
        .status-strip-top {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 10px;
        }
        .status-strip-main {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;
          flex: 1;
        }
        .status-icon {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          background: rgba(0, 102, 204, 0.1);
          color: var(--accent-color);
          flex-shrink: 0;
        }
        .status-copy {
          min-width: 0;
          flex: 1;
        }
        .status-title {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .status-detail {
          font-size: 12px;
          color: var(--text-secondary);
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
          margin-top: 2px;
          line-height: 1.45;
        }
        .status-phase-chip {
          flex-shrink: 0;
          min-height: 24px;
          padding: 0 9px;
          border-radius: 999px;
          border: 1px solid rgba(0, 102, 204, 0.16);
          background: rgba(0, 102, 204, 0.08);
          color: var(--accent-color);
          font-size: 11px;
          font-weight: 600;
          display: inline-flex;
          align-items: center;
        }
        .status-strip-tools {
          display: flex;
          flex-wrap: wrap;
          justify-content: flex-start;
          gap: 6px;
        }
        .tool-chip {
          max-width: 130px;
          padding: 3px 8px;
          border-radius: 999px;
          font-size: 11px;
          color: var(--accent-color);
          background: rgba(0, 102, 204, 0.1);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .tool-chip-more {
          max-width: none;
          color: var(--text-secondary);
          background: rgba(128, 128, 128, 0.08);
        }
        .usage-panel {
          border: 1px solid var(--glass-border);
          background: var(--bubble-assistant);
          border-radius: var(--radius-md);
          padding: 13px;
          display: flex;
          flex-direction: column;
          gap: 12px;
          box-shadow: 0 8px 24px var(--shadow-color);
        }
        .usage-panel-header {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .usage-empty {
          font-size: 13px;
          color: var(--text-secondary);
          line-height: 1.6;
        }
        .usage-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 10px;
        }
        .usage-stat {
          border-radius: 12px;
          background: rgba(128, 128, 128, 0.06);
          padding: 10px 12px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .usage-label,
        .usage-footer {
          font-size: 11px;
          color: var(--text-secondary);
        }
        .usage-section {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .usage-section-title {
          font-size: 12px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .usage-inline-list,
        .usage-breakdown {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          font-size: 12px;
          color: var(--text-secondary);
        }
        .message.system {
          align-self: stretch;
          max-width: 100%;
        }
        .message.system .message-inner {
          background: rgba(255, 59, 48, 0.06);
          border: 1px solid rgba(255, 59, 48, 0.2);
          color: var(--text-primary);
        }
        .turn-block {
          background: rgba(128, 128, 128, 0.05);
          border-radius: 10px;
          overflow: hidden;
          margin-bottom: 6px;
          border: 1px solid rgba(128, 128, 128, 0.08);
        }
        .turn-block-header {
          width: 100%;
          border: none;
          background: transparent;
          color: var(--text-secondary);
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 10px;
          cursor: pointer;
        }
        .turn-block-header:hover {
          background: rgba(128, 128, 128, 0.06);
        }
        .turn-block-title {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          font-weight: 500;
        }
        .turn-block-body {
          padding: 0 10px 10px;
          font-size: 12px;
          color: var(--text-secondary);
          line-height: 1.6;
        }
        .reasoning-body {
          white-space: pre-wrap;
        }
        .activity-list {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .activity-item {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .activity-line {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
        }
        .activity-phase {
          font-size: 11px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .activity-tool-tag {
          font-size: 10px;
          border-radius: 999px;
          padding: 2px 6px;
          background: rgba(0, 102, 204, 0.08);
          color: var(--accent-color);
        }
        .activity-text,
        .message-placeholder {
          font-size: 12px;
          color: var(--text-secondary);
          line-height: 1.6;
        }
        .message-error {
          margin-top: 8px;
          font-size: 12px;
          color: #ff3b30;
        }
        .input-toolbar {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-shrink: 0;
        }
        .composer-row {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
        }
        .thinking-label {
          font-size: 11px;
          color: var(--text-secondary);
          white-space: nowrap;
        }
        .thinking-select-wrap {
          min-width: 126px;
        }
        .input-row {
          display: flex;
          align-items: center;
          gap: 10px;
          flex: 1 1 220px;
          min-width: 0;
        }
        .confirm-modal {
          margin-top: 10px;
          background: rgba(255, 59, 48, 0.08);
          border: 1px solid rgba(255, 59, 48, 0.25);
          backdrop-filter: blur(10px);
          -webkit-backdrop-filter: blur(10px);
          border-radius: var(--radius-md);
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .confirm-header {
          display: flex;
          align-items: center;
          gap: 8px;
          color: #ff3b30;
          font-weight: 600;
          font-size: 14px;
        }
        .confirm-body {
          font-size: 13px;
          line-height: 1.6;
          color: var(--text-primary);
          word-break: break-word;
        }
        .confirm-actions {
          display: flex;
          gap: 10px;
          justify-content: flex-end;
          margin-top: 4px;
        }
        .btn-reject, .btn-accept {
          border: none;
          padding: 6px 14px;
          border-radius: 12px;
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          transition: transform 0.1s;
        }
        .btn-reject:active, .btn-accept:active {
          transform: scale(0.95);
        }
        .btn-reject {
          background: rgba(128,128,128,0.2);
          color: var(--text-primary);
        }
        .btn-reject:hover {
          background: rgba(128,128,128,0.3);
        }
        .btn-accept {
          background: #ff3b30;
          color: white;
        }
        .btn-accept:hover {
          background: #d70015;
        }
        .empty-copy {
          color: var(--text-secondary);
          font-size: 13px;
          text-align: center;
          margin-top: 28px;
        }
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
        @keyframes pulse {
          0% { opacity: 0.6; transform: scale(0.95); }
          50% { opacity: 1; transform: scale(1.05); }
          100% { opacity: 0.6; transform: scale(0.95); }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
