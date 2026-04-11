import { Gauge } from 'lucide-react'
import { RuntimeDebugSnapshot, RuntimeUsageSnapshot } from '../../types'
import { formatTokenCount } from '../../utils/statusFormatting'
import styles from './UsagePanel.module.css'

interface UsagePanelProps {
  usageSnapshot: RuntimeUsageSnapshot | null
  runtimeDebugSnapshot: RuntimeDebugSnapshot | null
  variant?: 'full' | 'compact'
}

export default function UsagePanel({
  usageSnapshot,
  runtimeDebugSnapshot,
  variant = 'full',
}: UsagePanelProps) {
  const isCompact = variant === 'compact'

  if (!usageSnapshot) {
    return (
      <div className={`${styles.panel} ${isCompact ? styles.compactPanel : ''}`.trim()}>
        <div className={styles.header}>
          <Gauge size={14} />
          <span>Token / Context</span>
        </div>
        <div className={styles.empty}>
          {isCompact ? '正在同步本会话 token / context 快照。' : '暂无本会话的 token 或上下文统计。'}
        </div>
      </div>
    )
  }

  const { context_breakdown: contextBreakdown, last_turn_usage: lastTurnUsage, session_totals: sessionTotals } = usageSnapshot
  const requestSnapshot = runtimeDebugSnapshot?.request
  const compression = runtimeDebugSnapshot?.compression
  const lastFailure = runtimeDebugSnapshot?.last_failure
  const usageHint = usageSnapshot.usage_ready
    ? null
    : 'Token 统计将在首轮模型交互后显示，上下文上限已初始化。'
  const pressurePercent = requestSnapshot ? `${Math.round(requestSnapshot.pressure_ratio * 100)}%` : ''
  const pressureRatio = usageSnapshot.context_limit_tokens > 0
    ? Math.min(100, Math.round((usageSnapshot.current_context_tokens_estimated / usageSnapshot.context_limit_tokens) * 100))
    : 0

  if (isCompact) {
    return (
      <div className={`${styles.panel} ${styles.compactPanel}`}>
        <div className={styles.header}>
          <Gauge size={14} />
          <span>主窗口 Token / Context</span>
        </div>

        <div className={`${styles.grid} ${styles.compactGrid}`}>
          <div className={styles.stat}>
            <span className={styles.label}>当前上下文</span>
            <strong>{formatTokenCount(usageSnapshot.current_context_tokens_estimated)}</strong>
          </div>
          <div className={styles.stat}>
            <span className={styles.label}>上下文上限</span>
            <strong>{formatTokenCount(usageSnapshot.context_limit_tokens)}</strong>
          </div>
          <div className={styles.stat}>
            <span className={styles.label}>本轮总计</span>
            <strong>{formatTokenCount(lastTurnUsage.total_tokens)}</strong>
          </div>
          <div className={styles.stat}>
            <span className={styles.label}>会话轮次</span>
            <strong>{sessionTotals.turn_count}</strong>
          </div>
        </div>

        <div className={styles.progressMeta}>
          <span>{pressureRatio}% 已占用</span>
          <span>{usageSnapshot.context_limit_model || '未知模型'}</span>
        </div>
        <div className={styles.progressBar} aria-label="context usage progress">
          <div className={styles.progressFill} style={{ width: `${pressureRatio}%` }} />
        </div>

        {usageHint && <div className={styles.empty}>{usageHint}</div>}

        <div className={styles.inlineList}>
          <span>系统 {formatTokenCount(contextBreakdown.system)}</span>
          <span>历史 {formatTokenCount(contextBreakdown.history)}</span>
          <span>工具 {formatTokenCount(contextBreakdown.tool_history)}</span>
          <span>记忆 {formatTokenCount(contextBreakdown.memory_context)}</span>
          <span>输入 {formatTokenCount(contextBreakdown.current_input)}</span>
          <span>来源 {usageSnapshot.context_limit_source || '后备'}</span>
        </div>
      </div>
    )
  }

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
          <span>提示词 {formatTokenCount(lastTurnUsage.prompt_tokens)}</span>
          <span>生成 {formatTokenCount(lastTurnUsage.completion_tokens)}</span>
          <span>推理 {formatTokenCount(lastTurnUsage.reasoning_tokens)}</span>
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionTitle}>会话累计</div>
        <div className={styles.inlineList}>
          <span>提示词 {formatTokenCount(sessionTotals.prompt_tokens)}</span>
          <span>生成 {formatTokenCount(sessionTotals.completion_tokens)}</span>
          <span>推理 {formatTokenCount(sessionTotals.reasoning_tokens)}</span>
          <span>{sessionTotals.turn_count} 轮</span>
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionTitle}>上下文构成</div>
        <div className={styles.breakdown}>
          <span>系统 {formatTokenCount(contextBreakdown.system)}</span>
          <span>历史 {formatTokenCount(contextBreakdown.history)}</span>
          <span>工具 {formatTokenCount(contextBreakdown.tool_history)}</span>
          <span>记忆 {formatTokenCount(contextBreakdown.memory_context)}</span>
          <span>策略 {formatTokenCount(contextBreakdown.policy)}</span>
          <span>输入 {formatTokenCount(contextBreakdown.current_input)}</span>
          <span>本体感知 {formatTokenCount(contextBreakdown.proprioception)}</span>
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionTitle}>上下文上限</div>
        <div className={styles.inlineList}>
          <span>模型 {usageSnapshot.context_limit_model || '未知'}</span>
          <span>来源 {usageSnapshot.context_limit_source || '后备'}</span>
          <span>置信度 {usageSnapshot.context_limit_confidence || '低'}</span>
        </div>
      </div>

      {requestSnapshot && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>请求诊断</div>
          <div className={styles.inlineList}>
            <span>供应商 {requestSnapshot.provider_name || '未知'}</span>
            <span>模式 {requestSnapshot.transport_mode || '未知'}</span>
            <span>主机 {requestSnapshot.api_target.host || '未知'}</span>
            <span>消息数 {requestSnapshot.message_count}</span>
            <span>请求量 {formatTokenCount(requestSnapshot.request_tokens_estimated)}</span>
            <span>压力 {pressurePercent || '0%'}</span>
          </div>
        </div>
      )}

      {compression && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>压缩状态</div>
          <div className={styles.inlineList}>
            <span>{compression.triggered ? '已触发自动压缩' : '本轮未触发压缩'}</span>
            <span>级别 {compression.level || '无'}</span>
            <span>修剪消息 {compression.trimmed_messages}</span>
            <span>压缩前 {formatTokenCount(compression.before_tokens)}</span>
            <span>压缩后 {formatTokenCount(compression.after_tokens)}</span>
            <span>摘要量 {formatTokenCount(compression.summary_tokens)}</span>
          </div>
        </div>
      )}

      {lastFailure && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>最近失败</div>
          <div className={styles.inlineList}>
            <span>代码 {lastFailure.code}</span>
            <span>分类 {lastFailure.category}</span>
            <span>{lastFailure.retryable ? '可重试' : '不可重试'}</span>
          </div>
          <div className={styles.empty}>{lastFailure.message}</div>
        </div>
      )}

      <div className={styles.footer}>
        来源：{usageSnapshot.usage_source || '未知'} | 上限来源：{usageSnapshot.context_limit_source || '后备'}
      </div>
    </div>
  )
}
