import { useState } from 'react'
import { BrainCircuit, ChevronDown } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import styles from './ChatBlocks.module.css'

interface ReasoningBlockProps {
  text: string
  isStreaming: boolean
}

export default function ReasoningBlock({ text, isStreaming }: ReasoningBlockProps) {
  const [expanded, setExpanded] = useState(false)

  if (!text) return null

  return (
    <div className={styles.reasoningWrapper}>
      <button 
        className={styles.reasoningHeader} 
        onClick={() => setExpanded(!expanded)}
      >
        <div className={styles.reasoningTitle}>
          <BrainCircuit size={14} className={isStreaming ? styles.pulse : ''} />
          <span>{isStreaming ? '思考中...' : '思考过程'}</span>
        </div>
        <motion.div
          animate={{ rotate: expanded ? 180 : 0 }}
          transition={{ type: 'spring', stiffness: 300, damping: 20 }}
        >
          <ChevronDown size={14} />
        </motion.div>
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0, scaleY: 0.95 }}
            animate={{ height: 'auto', opacity: 1, scaleY: 1 }}
            exit={{ height: 0, opacity: 0, scaleY: 0.95 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className={styles.reasoningBodyContainer}
            style={{ transformOrigin: 'top' }}
          >
            <div className={styles.reasoningBody}>
              {text}
              {isStreaming && <span className={styles.cursorBlink}>▍</span>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
