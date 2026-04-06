import { useEffect, useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ChatTurn, ConfirmRequestPayload, HumanInputRequestPayload, RuntimeHealthSnapshot, RuntimeStateSnapshot, RuntimeErrorPayload, RuntimeDebugSnapshot } from '../../types'
import TurnBody from './TurnBody'
import ActionCard from './ActionCard'
import styles from './MessageList.module.css'

interface MessageListProps {
  connected: boolean
  messages: ChatTurn[]
  runtimeSnapshot: RuntimeStateSnapshot | null
  runtimeDebugSnapshot: RuntimeDebugSnapshot | null
  healthSnapshot: RuntimeHealthSnapshot | null
  lastError: RuntimeErrorPayload | null
  archivedTurnCount: number
  confirmRequest: ConfirmRequestPayload | null
  pendingHumanInput: HumanInputRequestPayload | null
  sendConfirmResponse: (requestId: string, accepted: boolean) => void
  sendHumanInputResponse: (requestId: string, val: string, option?: string) => void
  sendControlCommand?: (action: 'stop' | 'append_guidance' | 'regenerate' | 'rollback', params?: { guidance?: string; checkpoint_id?: string; turn_id?: string; stream_id?: string }) => void
}

export default function MessageList({
  connected,
  messages,
  runtimeSnapshot,
  runtimeDebugSnapshot,
  healthSnapshot,
  lastError,
  archivedTurnCount,
  confirmRequest,
  pendingHumanInput,
  sendConfirmResponse,
  sendHumanInputResponse,
  sendControlCommand
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  
  const compression = runtimeDebugSnapshot?.compression
  const lastAssistantMessageId = [...messages].reverse().find(m => m.role === 'assistant')?.id

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [messages, confirmRequest, pendingHumanInput, runtimeSnapshot?.status])

  return (
    <div className={styles.scrollContainer}>
      <AnimatePresence initial={false}>
        {messages.length === 0 && (
          <motion.div className={styles.emptyState} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className={styles.emptyCopy}>
              {connected ? '随时可以开始对话。' : '等待后端服务启动后即可使用。'}
            </div>
          </motion.div>
        )}

        {archivedTurnCount > 0 && (
          <motion.div className={styles.systemMessage} initial={{ opacity: 0, y: -5 }} animate={{ opacity: 1, y: 0 }}>
            为保持长会话性能，已折叠较早的 {archivedTurnCount} 条消息，仅保留最近上下文。
          </motion.div>
        )}

        {healthSnapshot?.degraded && (
          <motion.div className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            服务当前处于降级状态，部分能力可能受限。
          </motion.div>
        )}

        {compression?.triggered && (
          <motion.div className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            本轮已自动压缩 {compression.trimmed_messages} 条历史消息，预算从 {compression.before_tokens} 降至 {compression.after_tokens}。
          </motion.div>
        )}

        {lastError && (
          <motion.div className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            {lastError.message}
          </motion.div>
        )}

        {messages.map((message) => {
          const isLastAssistantTurn = message.role === 'assistant' && message.id === lastAssistantMessageId
          const checkpointId = runtimeDebugSnapshot?.checkpoints?.find((c: any) => c.turn_id === message.turnId)?.checkpoint_id as string | undefined

          return (
            <motion.div
              key={message.id}
              className={`${styles.message} ${styles[message.role]}`}
              initial={{ opacity: 0, y: 10, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
              layout
            >
              <div className={styles.messageInner}>
                <TurnBody
                  turn={message}
                  runtimeSnapshot={runtimeSnapshot}
                  isLastAssistantTurn={isLastAssistantTurn}
                  checkpointId={checkpointId}
                  onRegenerate={sendControlCommand ? () => sendControlCommand('regenerate', { turn_id: message.turnId }) : undefined}
                  onRollback={sendControlCommand ? (cid) => sendControlCommand('rollback', { checkpoint_id: cid }) : undefined}
                />
              </div>
            </motion.div>
          )
        })}

        <ActionCard
          confirmRequest={confirmRequest}
          pendingHumanInput={pendingHumanInput}
          sendConfirmResponse={sendConfirmResponse}
          sendHumanInputResponse={sendHumanInputResponse}
        />
      </AnimatePresence>
      <div ref={scrollRef} style={{ height: 16 }} />
    </div>
  )
}
