import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Cpu } from 'lucide-react'
import type { RuntimeStateSnapshot, RuntimeUsageSnapshot, RuntimeHealthSnapshot, StatusFeedback } from '../../types'
import MotionCard from '../common/MotionCard'
import styles from './StatusIsland.module.css'

interface StatusIslandProps {
  runtimeSnapshot: RuntimeStateSnapshot | null
  usageSnapshot: RuntimeUsageSnapshot | null
  healthSnapshot: RuntimeHealthSnapshot | null
  statusFeedback?: StatusFeedback | null
  preferredMode?: string
  danxiStatusText?: string
}

export default function StatusIsland({ runtimeSnapshot, usageSnapshot, healthSnapshot, statusFeedback, preferredMode, danxiStatusText }: StatusIslandProps) {
  const [expanded, setExpanded] = useState(false)
  const islandRef = useRef<HTMLDivElement | null>(null)
  const dropdownRef = useRef<HTMLDivElement | null>(null)

  const isConnected = !!healthSnapshot
  const status = runtimeSnapshot?.status || 'idle'
  const isThinking = status === 'thinking' || status === 'tool_calling'
  const isError = status === 'error'
  const isDanxi = preferredMode === 'danxi'

  let indicatorClass = styles.statusIndicator
  if (isError) indicatorClass += ` ${styles.error}`
  else if (statusFeedback && statusFeedback.tone === 'success') indicatorClass += ` ${styles.online}` // Use online color for success
  else if (isThinking) indicatorClass += ` ${styles.thinking}`
  else if (isConnected || (isDanxi && danxiStatusText?.includes('已连接'))) indicatorClass += ` ${styles.online}`

  let displayText = 'MeetYou'
  if (statusFeedback) {
    displayText = statusFeedback.text
  } else if (isThinking) {
    displayText = runtimeSnapshot?.detail || '思考中...'
  } else if (isDanxi) {
    displayText = `旦夕 · ${danxiStatusText || '未连接'}`
  }

  const variants = {
    idle: { width: isDanxi ? 180 : 120, height: 36 },
    thinking: { width: 200, height: 36 },
    feedback: { width: 200, height: 36 },
    expanded: { width: 200, height: 36 }
  }

  let currentVariant = 'idle'
  if (statusFeedback) {
    currentVariant = 'feedback'
  } else if (isThinking) {
    currentVariant = 'thinking'
  }

  const usageLimitTokens = Math.max(usageSnapshot?.context_limit_tokens || 0, 1)
  const estimatedContextTokens = usageSnapshot?.current_context_tokens_estimated || 0
  const contextBreakdown = usageSnapshot?.context_breakdown
  const usageWidth = (value: number | undefined) => `${Math.min(100, Math.max(0, ((value || 0) / usageLimitTokens) * 100))}%`

  useEffect(() => {
    if (!expanded) {
      return
    }
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node
      if (!islandRef.current?.contains(target) && !dropdownRef.current?.contains(target)) {
        setExpanded(false)
      }
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
    }
  }, [expanded])

  return (
    <div className={styles.islandContainer} ref={islandRef}>
      <motion.div
        className={styles.islandPill}
        variants={variants}
        initial="idle"
        animate={currentVariant}
        layout
        transition={{ type: 'spring', stiffness: 400, damping: 30 }}
        onClick={() => setExpanded(!expanded)}
      >
        <motion.div className={styles.islandContent} layout>
          {isThinking && !statusFeedback ? (
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ repeat: Infinity, duration: 2, ease: "linear" }}
            >
              <Cpu size={14} />
            </motion.div>
          ) : (
            <div className={indicatorClass} />
          )}
          <span>{displayText}</span>
        </motion.div>
      </motion.div>

      {typeof document !== 'undefined' && createPortal(
        <AnimatePresence>
        {expanded && (
          <MotionCard ref={dropdownRef} className={styles.usageDropdown}>
            {usageSnapshot ? (
              <>
                <div className={styles.usageHeader}>
                  <span>上下文占用</span>
                  <span className="text-gradient">
                    {Math.round(estimatedContextTokens / 1000)}k / {Math.round(usageLimitTokens / 1000)}k
                  </span>
                </div>

                <div className={styles.usageBar}>
                  <div className={`${styles.usageChunk} ${styles.system}`} style={{ width: usageWidth(contextBreakdown?.system) }} />
                  <div className={`${styles.usageChunk} ${styles.history}`} style={{ width: usageWidth(contextBreakdown?.history) }} />
                  <div className={`${styles.usageChunk} ${styles.memory}`} style={{ width: usageWidth(contextBreakdown?.memory_context) }} />
                  <div className={`${styles.usageChunk} ${styles.current}`} style={{ width: usageWidth(contextBreakdown?.current_input) }} />
                </div>

                {!usageSnapshot.usage_ready && (
                  <div className={styles.usageNotice}>上下文统计同步中，首轮回复后会显示更准确的用量。</div>
                )}
              </>
            ) : (
              <div className={styles.usageEmpty}>
                <div className={styles.usageEmptyTitle}>上下文与用量</div>
                <div className={styles.usageEmptyText}>正在同步当前会话的上下文数据。</div>
              </div>
            )}

            {usageSnapshot && (
              <div className={styles.usageLegend}>
                <div className={styles.legendItem}><div className={styles.legendDot} style={{ background: '#ff9500' }}/> 系统</div>
                <div className={styles.legendItem}><div className={styles.legendDot} style={{ background: '#34c759' }}/> 历史</div>
                <div className={styles.legendItem}><div className={styles.legendDot} style={{ background: '#af52de' }}/> 记忆</div>
                <div className={styles.legendItem}><div className={styles.legendDot} style={{ background: 'var(--text-accent)' }}/> 当前</div>
              </div>
            )}
            
            {isDanxi && (
              <div className={styles.danxiStatusRow}>
                <span>旦夕状态</span>
                <strong>{danxiStatusText || '未连接'}</strong>
              </div>
            )}
          </MotionCard>
        )}
        </AnimatePresence>,
        document.body,
      )}
    </div>
  )
}
