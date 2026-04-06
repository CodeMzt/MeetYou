import { useState } from 'react'
import { ChevronDown, ChevronRight, Wrench } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import { TurnActivity } from '../../types'
import { getActivityPhaseLabel } from '../../utils/statusFormatting'
import styles from './ChatBlocks.module.css'

interface ActivityBlockProps {
  activities: TurnActivity[]
  isStreaming: boolean
  trimmedCount: number
}

export default function ActivityBlock({ activities, isStreaming, trimmedCount }: ActivityBlockProps) {
  const [expanded, setExpanded] = useState(false)

  if (activities.length === 0) return null

  const headerText = isStreaming ? '正在使用工具' : '工具活动'

  return (
    <div className={styles.turnBlock}>
      <button className={styles.turnBlockHeader} onClick={() => setExpanded(!expanded)}>
        <div className={styles.turnBlockTitle}>
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
            className={styles.turnBlockBody}
          >
            <div className={styles.activityList}>
              {trimmedCount > 0 && (
                <div className={styles.activityItem}>
                  <div className={styles.activityText}>已折叠更早的 {trimmedCount} 条活动记录以保持长会话流畅。</div>
                </div>
              )}
              {activities.map((activity) => (
                <div key={activity.id} className={styles.activityItem}>
                  <div className={styles.activityLine}>
                    <span className={styles.activityPhase}>{getActivityPhaseLabel(activity.phase)}</span>
                    {activity.toolNames.length > 0 && (
                      <span className={styles.activityToolTag} title={activity.toolNames.join(', ')}>
                        {activity.toolNames.join(', ')}
                      </span>
                    )}
                  </div>
                  <div className={styles.activityText}>{activity.content}</div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
