import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Cpu } from 'lucide-react'
import type { RuntimeStateSnapshot, RuntimeUsageSnapshot, RuntimeHealthSnapshot } from '../../types'
import MotionCard from '../common/MotionCard'
import styles from './StatusIsland.module.css'

interface StatusIslandProps {
  runtimeSnapshot: RuntimeStateSnapshot | null
  usageSnapshot: RuntimeUsageSnapshot | null
  healthSnapshot: RuntimeHealthSnapshot | null
}

export default function StatusIsland({ runtimeSnapshot, usageSnapshot, healthSnapshot }: StatusIslandProps) {
  const [expanded, setExpanded] = useState(false)

  const isConnected = !!healthSnapshot
  const status = runtimeSnapshot?.status || 'idle'
  const isThinking = status === 'thinking' || status === 'tool_calling'
  const isError = status === 'error'

  let indicatorClass = styles.statusIndicator
  if (isError) indicatorClass += ` ${styles.error}`
  else if (isThinking) indicatorClass += ` ${styles.thinking}`
  else if (isConnected) indicatorClass += ` ${styles.online}`

  const displayText = isThinking ? runtimeSnapshot?.detail || '思考中...' : 'MeetYou'

  const variants = {
    idle: { width: 120, height: 36 },
    thinking: { width: 200, height: 36 },
    expanded: { width: 200, height: 36 }
  }

  const currentVariant = isThinking ? 'thinking' : 'idle'

  return (
    <div className={styles.islandContainer}>
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
          {isThinking ? (
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

      <AnimatePresence>
        {expanded && usageSnapshot && usageSnapshot.usage_ready && (
          <MotionCard className={styles.usageDropdown}>
            <div className={styles.usageHeader}>
              <span>上下文占用</span>
              <span className="text-gradient">
                {Math.round(usageSnapshot.current_context_tokens_estimated / 1000)}k / {Math.round(usageSnapshot.context_limit_tokens / 1000)}k
              </span>
            </div>
            
            <div className={styles.usageBar}>
              <div className={`${styles.usageChunk} ${styles.system}`} style={{ width: `${(usageSnapshot.context_breakdown.system / usageSnapshot.context_limit_tokens) * 100}%` }} />
              <div className={`${styles.usageChunk} ${styles.history}`} style={{ width: `${(usageSnapshot.context_breakdown.history / usageSnapshot.context_limit_tokens) * 100}%` }} />
              <div className={`${styles.usageChunk} ${styles.memory}`} style={{ width: `${(usageSnapshot.context_breakdown.memory_context / usageSnapshot.context_limit_tokens) * 100}%` }} />
              <div className={`${styles.usageChunk} ${styles.current}`} style={{ width: `${(usageSnapshot.context_breakdown.current_input / usageSnapshot.context_limit_tokens) * 100}%` }} />
            </div>

            <div className={styles.usageLegend}>
              <div className={styles.legendItem}><div className={styles.legendDot} style={{ background: '#ff9500' }}/> 系统</div>
              <div className={styles.legendItem}><div className={styles.legendDot} style={{ background: '#34c759' }}/> 历史</div>
              <div className={styles.legendItem}><div className={styles.legendDot} style={{ background: '#af52de' }}/> 记忆</div>
              <div className={styles.legendItem}><div className={styles.legendDot} style={{ background: 'var(--text-accent)' }}/> 当前</div>
            </div>
          </MotionCard>
        )}
      </AnimatePresence>
    </div>
  )
}
