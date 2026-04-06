import { Gauge } from 'lucide-react'
import { RuntimeDebugSnapshot, RuntimeUsageSnapshot } from '../../types'
import { formatTokenCount } from '../../utils/statusFormatting'
import styles from './UsagePanel.module.css'

interface UsagePanelProps {
  usageSnapshot: RuntimeUsageSnapshot | null
  runtimeDebugSnapshot: RuntimeDebugSnapshot | null
}

export default function UsagePanel({ usageSnapshot, runtimeDebugSnapshot }: UsagePanelProps) {
  if (!usageSnapshot) {
    return (
      <div className={styles.panel}>
        <div className={styles.header}>
          <Gauge size={14} />
          <span>Token / Context</span>
        </div>
        <div className={styles.empty}>暂无本会话的 token 或上下文统计。</div>
      </div>
    )
  }

  const { context_breakdown: contextBreakdown, last_turn_usage: lastTurnUsage, session_totals: sessionTotals } = usageSnapshot
  const requestSnapshot = runtimeDebugSnapshot?.request
  const compression = runtimeDebugSnapshot?.compression
  const lastFailure = runtimeDebugSnapshot?.last_failure
  const usageHint = usageSnapshot.usage_ready
    ? null
    : 'Usage counters will appear after the first model turn. Context limit has already been resolved.'
  const pressurePercent = requestSnapshot ? `${Math.round(requestSnapshot.pressure_ratio * 100)}%` : ''

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <Gauge size={14} />
        <span>Token / Context</span>
      </div>

      <div className={styles.grid}>
        <div className={styles.stat}>
          <span className={styles.label}>本轮总计</span>
          <strong>{formatTokenCount(lastTurnUsage.total_tokens)}</strong>
        </div>
        <div className={styles.stat}>
          <span className={styles.label}>会话总计</span>
          <strong>{formatTokenCount(sessionTotals.total_tokens)}</strong>
        </div>
        <div className={styles.stat}>
          <span className={styles.label}>当前上下文</span>
          <strong>{formatTokenCount(usageSnapshot.current_context_tokens_estimated)}</strong>
        </div>
        <div className={styles.stat}>
          <span className={styles.label}>上下文上限</span>
          <strong>{formatTokenCount(usageSnapshot.context_limit_tokens)}</strong>
        </div>
      </div>

      {usageHint && <div className={styles.empty}>{usageHint}</div>}

      <div className={styles.section}>
        <div className={styles.sectionTitle}>本轮消耗</div>
        <div className={styles.inlineList}>
          <span>Prompt {formatTokenCount(lastTurnUsage.prompt_tokens)}</span>
          <span>Completion {formatTokenCount(lastTurnUsage.completion_tokens)}</span>
          <span>Reasoning {formatTokenCount(lastTurnUsage.reasoning_tokens)}</span>
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionTitle}>会话累计</div>
        <div className={styles.inlineList}>
          <span>Prompt {formatTokenCount(sessionTotals.prompt_tokens)}</span>
          <span>Completion {formatTokenCount(sessionTotals.completion_tokens)}</span>
          <span>Reasoning {formatTokenCount(sessionTotals.reasoning_tokens)}</span>
          <span>{sessionTotals.turn_count} 轮</span>
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionTitle}>上下文构成</div>
        <div className={styles.breakdown}>
          <span>System {formatTokenCount(contextBreakdown.system)}</span>
          <span>History {formatTokenCount(contextBreakdown.history)}</span>
          <span>Tools {formatTokenCount(contextBreakdown.tool_history)}</span>
          <span>Memory {formatTokenCount(contextBreakdown.memory_context)}</span>
          <span>Policy {formatTokenCount(contextBreakdown.policy)}</span>
          <span>Input {formatTokenCount(contextBreakdown.current_input)}</span>
          <span>Proprioception {formatTokenCount(contextBreakdown.proprioception)}</span>
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionTitle}>Context Limit</div>
        <div className={styles.inlineList}>
          <span>Model {usageSnapshot.context_limit_model || 'unknown'}</span>
          <span>Source {usageSnapshot.context_limit_source || 'fallback'}</span>
          <span>Confidence {usageSnapshot.context_limit_confidence || 'low'}</span>
        </div>
      </div>

      {requestSnapshot && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>请求诊断</div>
          <div className={styles.inlineList}>
            <span>Provider {requestSnapshot.provider_name || 'unknown'}</span>
            <span>Mode {requestSnapshot.transport_mode || 'unknown'}</span>
            <span>Host {requestSnapshot.api_target.host || 'unknown'}</span>
            <span>Messages {requestSnapshot.message_count}</span>
            <span>Request {formatTokenCount(requestSnapshot.request_tokens_estimated)}</span>
            <span>Pressure {pressurePercent || '0%'}</span>
          </div>
        </div>
      )}

      {compression && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>压缩状态</div>
          <div className={styles.inlineList}>
            <span>{compression.triggered ? '已触发自动压缩' : '本轮未触发压缩'}</span>
            <span>Level {compression.level || 'none'}</span>
            <span>Trimmed {compression.trimmed_messages}</span>
            <span>Before {formatTokenCount(compression.before_tokens)}</span>
            <span>After {formatTokenCount(compression.after_tokens)}</span>
            <span>Summary {formatTokenCount(compression.summary_tokens)}</span>
          </div>
        </div>
      )}

      {lastFailure && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>最近失败</div>
          <div className={styles.inlineList}>
            <span>Code {lastFailure.code}</span>
            <span>Category {lastFailure.category}</span>
            <span>{lastFailure.retryable ? '可重试' : '不可重试'}</span>
          </div>
          <div className={styles.empty}>{lastFailure.message}</div>
        </div>
      )}

      <div className={styles.footer}>
        来源：{usageSnapshot.usage_source || 'unknown'} | 上限来源：{usageSnapshot.context_limit_source || 'fallback'}
      </div>
    </div>
  )
}
