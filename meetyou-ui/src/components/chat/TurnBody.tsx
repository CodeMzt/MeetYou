import { RefreshCw } from 'lucide-react'
import { ChatTurn, RuntimeStateSnapshot } from '../../types'
import { getRuntimeTitle } from '../../utils/statusFormatting'
import ActivityBlock from './ActivityBlock'
import ReasoningBlock from './ReasoningBlock'
import MarkdownRenderer from './MarkdownRenderer'
import styles from './TurnBody.module.css'
import { normalizeAssistantDisplayText } from '../../utils/displayText'

interface TurnBodyProps {
  turn: ChatTurn
  runtimeSnapshot: RuntimeStateSnapshot | null
  isLastAssistantTurn?: boolean
  onRegenerate?: () => void
}

export default function TurnBody({ turn, runtimeSnapshot, isLastAssistantTurn, onRegenerate }: TurnBodyProps) {
  const isBusy = ['thinking', 'tool_calling', 'answering'].includes(runtimeSnapshot?.status || '')
  const displayContent = turn.role === 'assistant' ? normalizeAssistantDisplayText(turn.content) : turn.content
  const showActionBar = !turn.isStreaming && turn.role === 'assistant' && !isBusy && isLastAssistantTurn && Boolean(onRegenerate)

  const placeholderText =
    turn.isStreaming && !turn.content && !turn.reasoning && (!turn.activities || turn.activities.length === 0)
      ? getRuntimeTitle(runtimeSnapshot, 'connected')
      : ''

  return (
    <>
      {turn.role === 'assistant' && (
        <>
          <ActivityBlock
            activities={turn.activities || []}
            isStreaming={turn.isStreaming || false}
            trimmedCount={turn.trimmedActivityCount ?? 0}
          />
          <ReasoningBlock text={turn.reasoning || ''} isStreaming={(turn.isStreaming || false) && !turn.content} />
        </>
      )}
      {turn.content ? (
        <div className={styles.content}>
          {turn.temporary ? <span className={styles.temporaryBadge}>临时回复</span> : null}
          {turn.isStreaming ? <span className={styles.streamingText}>{displayContent}</span> : <MarkdownRenderer content={displayContent} />}
        </div>
      ) : placeholderText ? (
        <div className={styles.placeholder}>{placeholderText}</div>
      ) : null}
      {turn.isStreaming && turn.content && <span className={styles.cursorBlink}>▍</span>}
      {turn.error && <div className={styles.error}>{turn.error}</div>}

      {showActionBar && (
        <div className={styles.actionBar}>
          <button className={styles.actionBtn} onClick={onRegenerate} title="重新生成">
            <RefreshCw size={14} />
          </button>
        </div>
      )}
    </>
  )
}
