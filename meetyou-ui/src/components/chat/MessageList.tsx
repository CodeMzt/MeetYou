import { useEffect, useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { User, Bot } from 'lucide-react'
import { ChatTurn, HumanInputRequestPayload, OperationView, RuntimeHealthSnapshot, RuntimeStateSnapshot, RuntimeErrorPayload, ApprovalDisplayModel } from '../../types'
import TurnBody from './TurnBody'
import ActionCard from './ActionCard'
import OperationPanel from './OperationPanel'
import styles from './MessageList.module.css'

interface MessageListProps {
  connected: boolean
  messages: ChatTurn[]
  operations: OperationView[]
  runtimeSnapshot: RuntimeStateSnapshot | null
  healthSnapshot: RuntimeHealthSnapshot | null
  lastError: RuntimeErrorPayload | null
  archivedTurnCount: number
  approvalDisplay: ApprovalDisplayModel | null
  pendingHumanInput: HumanInputRequestPayload | null
  sendConfirmResponse: (requestId: string, accepted: boolean, approvalId?: string) => void
  sendHumanInputResponse: (requestId: string, val: string, option?: string) => void
  decideOperationApproval?: (approvalId: string, decision: 'approve' | 'reject') => void
  onDownloadAttachment?: (attachmentId: string) => void
  sendControlCommand?: (action: 'stop' | 'append_guidance' | 'regenerate' | 'rollback', params?: { guidance?: string; checkpoint_id?: string; turn_id?: string; stream_id?: string }) => void
}

export default function MessageList({
  connected,
  messages,
  operations,
  runtimeSnapshot,
  healthSnapshot,
  lastError,
  archivedTurnCount,
  approvalDisplay,
  pendingHumanInput,
  sendConfirmResponse,
  sendHumanInputResponse,
  decideOperationApproval,
  onDownloadAttachment,
  sendControlCommand
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const lastAssistantMessageId = [...messages].reverse().find(m => m.role === 'assistant')?.id

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [messages, approvalDisplay, pendingHumanInput, runtimeSnapshot?.status])

  return (
    <div className={styles.scrollContainer}>
      <AnimatePresence initial={false}>
        {messages.length === 0 && (
          <motion.div key="empty-state" className={styles.emptyState} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className={styles.emptyCopy}>
              {connected ? '随时可以开始对话。' : '等待后端服务启动后即可使用。'}
            </div>
          </motion.div>
        )}

        {archivedTurnCount > 0 && (
          <motion.div key="archived-turns" className={styles.systemMessage} initial={{ opacity: 0, y: -5 }} animate={{ opacity: 1, y: 0 }}>
            为保持长会话性能，已折叠较早的 {archivedTurnCount} 条消息，仅保留最近上下文。
          </motion.div>
        )}

        {healthSnapshot?.degraded && (
          <motion.div key="degraded-health" className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            服务当前处于降级状态，部分能力可能受限。
          </motion.div>
        )}

        {lastError && (
          <motion.div key={`runtime-error-${lastError.code}-${lastError.occurred_at || lastError.message}`} className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            {lastError.message}
          </motion.div>
        )}

        {messages.map((message) => {
          const isLastAssistantTurn = message.role === 'assistant' && message.id === lastAssistantMessageId

          return (
            <motion.div
              key={`${message.role}-${message.id || message.turnId || message.createdAt}`}
              className={`${styles.messageWrapper} ${styles[message.role]}`}
              initial={{ opacity: 0, y: 15, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ type: 'spring', stiffness: 400, damping: 30 }}
              layout
            >
              {message.role === 'assistant' && (
                <div className={styles.avatar}>
                  <Bot size={16} />
                </div>
              )}
              <div className={styles.message}>
                <div className={styles.messageInner}>
                  <TurnBody
                    turn={message}
                    runtimeSnapshot={runtimeSnapshot}
                    isLastAssistantTurn={isLastAssistantTurn}
                    onDownloadAttachment={onDownloadAttachment}
                    onRegenerate={sendControlCommand ? () => sendControlCommand('regenerate', { turn_id: message.turnId }) : undefined}
                  />
                  {(message.confirmRequest || message.humanInputRequest || message.confirmResponse || message.humanInputResponse) && (
                    <ActionCard 
                      turn={message} 
                      sendConfirmResponse={sendConfirmResponse} 
                      sendHumanInputResponse={sendHumanInputResponse} 
                    />
                  )}
                </div>
              </div>
              {message.role === 'user' && (
                <div className={styles.avatar}>
                  <User size={16} />
                </div>
              )}
            </motion.div>
          )
        })}

        <OperationPanel
          operations={operations}
          onApprove={decideOperationApproval ? (approvalId) => decideOperationApproval(approvalId, 'approve') : undefined}
          onReject={decideOperationApproval ? (approvalId) => decideOperationApproval(approvalId, 'reject') : undefined}
          onDownloadAttachment={onDownloadAttachment}
        />
      </AnimatePresence>
      <div ref={scrollRef} style={{ height: 16 }} />
    </div>
  )
}
