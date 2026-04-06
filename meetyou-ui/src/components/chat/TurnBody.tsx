import { ChatTurn, RuntimeStateSnapshot } from '../../types'
import { getRuntimeTitle } from '../../utils/statusFormatting'
import ActivityBlock from './ActivityBlock'
import ReasoningBlock from './ReasoningBlock'
import styles from './TurnBody.module.css'

interface TurnBodyProps {
  turn: ChatTurn
  runtimeSnapshot: RuntimeStateSnapshot | null
}

export default function TurnBody({ turn, runtimeSnapshot }: TurnBodyProps) {
  const placeholderText =
    turn.isStreaming && !turn.content && !turn.reasoning && turn.activities.length === 0
      ? getRuntimeTitle(runtimeSnapshot, 'connected')
      : ''

  return (
    <>
      {turn.role === 'assistant' && (
        <>
          <ActivityBlock
            activities={turn.activities}
            isStreaming={turn.isStreaming}
            trimmedCount={turn.trimmedActivityCount ?? 0}
          />
          <ReasoningBlock text={turn.reasoning} isStreaming={turn.isStreaming && !turn.content} />
        </>
      )}
      {turn.content ? (
        <div className={styles.content}>{turn.content}</div>
      ) : placeholderText ? (
        <div className={styles.placeholder}>{placeholderText}</div>
      ) : null}
      
      {turn.isStreaming && turn.content && <span className={styles.cursorBlink}>▍</span>}
      {turn.error && <div className={styles.error}>{turn.error}</div>}
    </>
  )
}
