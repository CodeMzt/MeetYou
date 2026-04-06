import { useState } from 'react'
import { BrainCircuit, ChevronDown, ChevronRight } from 'lucide-react'
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
    <div className={styles.turnBlock}>
      <button className={styles.turnBlockHeader} onClick={() => setExpanded(!expanded)}>
        <div className={styles.turnBlockTitle}>
          <BrainCircuit size={14} className={isStreaming ? styles.pulse : ''} />
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
            className={`${styles.turnBlockBody} ${styles.reasoningBody}`}
          >
            <div>{text}</div>
            {isStreaming && <span className={styles.cursorBlink}>▍</span>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
