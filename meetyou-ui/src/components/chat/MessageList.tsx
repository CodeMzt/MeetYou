import { useEffect, useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ChatTurn, ConfirmRequestPayload, HumanInputRequestPayload, RuntimeHealthSnapshot, RuntimeStateSnapshot, AckPayload, RuntimeErrorPayload, RuntimeDebugSnapshot } from '../../types'
import TurnBody from './TurnBody'
import { ConfirmModal, HumanInputPanel } from './InteractionPanels'
import styles from './MessageList.module.css'

interface MessageListProps {
  connected: boolean
  messages: ChatTurn[]
  runtimeSnapshot: RuntimeStateSnapshot | null
  runtimeDebugSnapshot: RuntimeDebugSnapshot | null
  healthSnapshot: RuntimeHealthSnapshot | null
  lastAck: AckPayload | null
  lastError: RuntimeErrorPayload | null
  archivedTurnCount: number
  confirmRequest: ConfirmRequestPayload | null
  pendingHumanInput: HumanInputRequestPayload | null
  sendConfirmResponse: (requestId: string, accepted: boolean) => void
  sendHumanInputResponse: (requestId: string, val: string, option?: string) => void
}

export default function MessageList({
  connected,
  messages,
  runtimeSnapshot,
  runtimeDebugSnapshot,
  healthSnapshot,
  lastAck,
  lastError,
  archivedTurnCount,
  confirmRequest,
  pendingHumanInput,
  sendConfirmResponse,
  sendHumanInputResponse
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const compression = runtimeDebugSnapshot?.compression
  const request = runtimeDebugSnapshot?.request
  const debugFailure = runtimeDebugSnapshot?.last_failure
  const objectOperations = runtimeDebugSnapshot?.object_operations ?? []
  const latestObjectOperation = objectOperations.length > 0 ? objectOperations[objectOperations.length - 1] : null
  const authorization = runtimeDebugSnapshot?.authorization ?? {}
  const confirmation = authorization && typeof authorization === 'object' ? (authorization as Record<string, unknown>).confirmation : null
  const confirmationPending =
    confirmation && typeof confirmation === 'object' ? Boolean((confirmation as Record<string, unknown>).pending) : false
  const objectSummary =
    latestObjectOperation && typeof latestObjectOperation.summary === 'string'
      ? latestObjectOperation.summary
      : ''
  const objectStatus =
    latestObjectOperation && typeof latestObjectOperation.status === 'string'
      ? latestObjectOperation.status
      : ''

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
          <motion.div className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className={styles.systemInner}>
              为保持长会话性能，已折叠较早的 {archivedTurnCount} 条消息，仅保留最近上下文。
            </div>
          </motion.div>
        )}

        {healthSnapshot?.degraded && (
          <motion.div className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className={styles.systemInner}>服务当前处于降级状态，部分能力可能受限。</div>
          </motion.div>
        )}

        {compression?.triggered && (
          <motion.div className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className={styles.systemInner}>
              本轮已自动压缩 {compression.trimmed_messages} 条历史消息，预算从 {compression.before_tokens} 降至 {compression.after_tokens}。
            </div>
          </motion.div>
        )}

        {!compression?.triggered && request?.near_limit && (
          <motion.div className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className={styles.systemInner}>
              当前上下文接近 provider 上限，预计占用 {Math.round(request.pressure_ratio * 100)}%，后续可能触发自动压缩。
            </div>
          </motion.div>
        )}

        {lastError && (
          <motion.div className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className={styles.systemInner}>{lastError.message}</div>
          </motion.div>
        )}

        {!lastError && debugFailure && (
          <motion.div className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className={styles.systemInner}>
              最近失败分类：{debugFailure.code} / {debugFailure.category}，{debugFailure.message}
            </div>
          </motion.div>
        )}

        {!lastError && objectSummary && (
          <motion.div className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className={styles.systemInner}>
              {objectStatus === 'ambiguous'
                ? `对象定位存在歧义：${objectSummary}`
                : objectStatus === 'cancelled'
                  ? `对象操作已取消：${objectSummary}`
                  : objectStatus === 'not_found'
                    ? `对象未找到：${objectSummary}`
                    : `最近对象操作：${objectSummary}`}
            </div>
          </motion.div>
        )}

        {confirmationPending && !confirmRequest && (
          <motion.div className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className={styles.systemInner}>存在待确认的对象操作，请先完成确认。</div>
          </motion.div>
        )}

        {lastAck && lastAck.action !== 'input.accepted' && (
          <motion.div className={styles.systemMessage} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className={styles.systemInner}>
              {lastAck.action === 'confirm_response' ? '确认响应已被服务接收。' : '补充输入已被服务接收。'}
            </div>
          </motion.div>
        )}

        {messages.map((message) => (
          <motion.div
            key={message.id}
            className={`${styles.message} ${styles[message.role]}`}
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: 'spring', stiffness: 380, damping: 28 }}
          >
            <div className={styles.messageInner}>
              <TurnBody turn={message} runtimeSnapshot={runtimeSnapshot} />
            </div>
          </motion.div>
        ))}

        {confirmRequest && (
          <ConfirmModal request={confirmRequest} onConfirm={sendConfirmResponse} />
        )}

        {pendingHumanInput && !confirmRequest && (
          <HumanInputPanel request={pendingHumanInput} connected={connected} onSubmit={sendHumanInputResponse} />
        )}
      </AnimatePresence>
      <div ref={scrollRef} style={{ height: 1 }} />
    </div>
  )
}
