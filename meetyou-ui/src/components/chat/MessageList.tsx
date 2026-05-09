import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { User, Bot, FolderPlus, MoreHorizontal, PencilLine, X } from 'lucide-react'
import { ChatTurn, HumanInputRequestPayload, RuntimeHealthSnapshot, RuntimeStateSnapshot, RuntimeErrorPayload, ApprovalDisplayModel } from '../../types'
import TurnBody from './TurnBody'
import ActionCard from './ActionCard'
import styles from './MessageList.module.css'

interface MessageListProps {
  connected: boolean
  messages: ChatTurn[]
  runtimeSnapshot: RuntimeStateSnapshot | null
  healthSnapshot: RuntimeHealthSnapshot | null
  lastError: RuntimeErrorPayload | null
  archivedTurnCount: number
  approvalDisplay: ApprovalDisplayModel | null
  pendingHumanInput: HumanInputRequestPayload | null
  activeProjectId?: string
  sendConfirmResponse: (requestId: string, accepted: boolean, approvalId?: string) => void
  sendHumanInputResponse: (requestId: string, val: string, option?: string) => void
  sendControlCommand?: (action: 'stop' | 'append_guidance' | 'regenerate' | 'rollback', params?: { guidance?: string; checkpoint_id?: string; turn_id?: string; stream_id?: string }) => void
  onSaveMessageAsProjectSource?: (message: ChatTurn) => Promise<unknown>
  onEditRetryMessage?: (message: ChatTurn, content: string) => Promise<unknown>
}

export default function MessageList({
  connected,
  messages,
  runtimeSnapshot,
  healthSnapshot,
  lastError,
  archivedTurnCount,
  approvalDisplay,
  pendingHumanInput,
  activeProjectId = '',
  sendConfirmResponse,
  sendHumanInputResponse,
  sendControlCommand,
  onSaveMessageAsProjectSource,
  onEditRetryMessage,
}: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const editTextareaRef = useRef<HTMLTextAreaElement>(null)
  const [autoFollowEnabled, setAutoFollowEnabled] = useState(true)
  const [openMenuMessageId, setOpenMenuMessageId] = useState('')
  const [busyMessageId, setBusyMessageId] = useState('')
  const [actionError, setActionError] = useState('')
  const [editingMessage, setEditingMessage] = useState<ChatTurn | null>(null)
  const [editDraft, setEditDraft] = useState('')
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({})
  const lastAssistantMessageId = useMemo(
    () => [...messages].reverse().find((message) => message.role === 'assistant')?.id,
    [messages],
  )
  const isStreaming = ['thinking', 'tool_calling', 'answering'].includes(runtimeSnapshot?.status || '')

  useLayoutEffect(() => {
    if (!openMenuMessageId) {
      return
    }
    const menu = menuRef.current
    if (!menu) {
      return
    }
    const rect = menu.getBoundingClientRect()
    const gutter = 8
    const maxTop = Math.max(gutter, window.innerHeight - rect.height - gutter)
    const maxLeft = Math.max(gutter, window.innerWidth - rect.width - gutter)
    const nextTop = Math.min(Math.max(gutter, rect.top), maxTop)
    const nextLeft = Math.min(Math.max(gutter, rect.left), maxLeft)
    if (Math.abs(nextTop - rect.top) > 0.5 || Math.abs(nextLeft - rect.left) > 0.5) {
      setMenuStyle((current) => ({ ...current, top: nextTop, left: nextLeft }))
    }
  }, [openMenuMessageId, menuStyle.left, menuStyle.top])

  const isNearBottom = () => {
    const container = containerRef.current
    if (!container) {
      return true
    }
    const distance = container.scrollHeight - container.scrollTop - container.clientHeight
    return distance <= 80
  }

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const container = containerRef.current
    if (!container) {
      return
    }
    container.scrollTo({ top: container.scrollHeight, behavior })
  }, [])

  useEffect(() => {
    if (autoFollowEnabled) {
      scrollToBottom(isStreaming ? 'auto' : 'smooth')
    }
  }, [autoFollowEnabled, messages, approvalDisplay, pendingHumanInput, runtimeSnapshot?.status, isStreaming, scrollToBottom])

  useEffect(() => {
    if (autoFollowEnabled && isNearBottom()) {
      return
    }
    if (!isStreaming && isNearBottom()) {
      setAutoFollowEnabled(true)
    }
  }, [isStreaming, messages, autoFollowEnabled])

  const handleScroll = () => {
    if (!isStreaming) {
      if (!autoFollowEnabled && isNearBottom()) {
        setAutoFollowEnabled(true)
      }
      return
    }
    if (isNearBottom()) {
      if (!autoFollowEnabled) {
        setAutoFollowEnabled(true)
      }
      return
    }
    if (autoFollowEnabled) {
      setAutoFollowEnabled(false)
    }
  }

  const isPersistedMessage = (message: ChatTurn) => Boolean(message.id && message.id.startsWith('msg_') && !message.temporary)

  const updateMenuPosition = (button: HTMLButtonElement, message: ChatTurn) => {
    const rect = button.getBoundingClientRect()
    const gutter = 8
    const width = 160
    const itemCount = (onSaveMessageAsProjectSource ? 1 : 0) + (message.role === 'user' && onEditRetryMessage ? 1 : 0)
    const estimatedHeight = 14 + itemCount * 34
    const belowTop = rect.bottom + 6
    const top = belowTop + estimatedHeight <= window.innerHeight - gutter
      ? belowTop
      : Math.max(gutter, rect.top - estimatedHeight - 6)
    const left = Math.min(
      Math.max(gutter, rect.right - width),
      Math.max(gutter, window.innerWidth - width - gutter),
    )
    setMenuStyle({ left, top, width })
  }

  const handleSaveSource = async (message: ChatTurn) => {
    if (!onSaveMessageAsProjectSource || busyMessageId) {
      return
    }
    setBusyMessageId(message.id)
    setActionError('')
    try {
      await onSaveMessageAsProjectSource(message)
      setOpenMenuMessageId('')
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '保存项目源失败')
    } finally {
      setBusyMessageId('')
    }
  }

  const openEditRetry = (message: ChatTurn) => {
    setEditingMessage(message)
    setEditDraft(message.content)
    setOpenMenuMessageId('')
    setActionError('')
  }

  const renderMessageActionMenu = (message: ChatTurn) => {
    if (openMenuMessageId !== message.id || typeof document === 'undefined') {
      return null
    }
    return createPortal(
      <div className={styles.messageActionMenu} role="menu" style={menuStyle} ref={menuRef}>
        {onSaveMessageAsProjectSource ? (
          <button
            type="button"
            role="menuitem"
            className={styles.messageActionItem}
            disabled={!activeProjectId || Boolean(busyMessageId)}
            onClick={() => void handleSaveSource(message)}
          >
            <FolderPlus size={14} aria-hidden="true" />
            <span>保存为项目源</span>
          </button>
        ) : null}
        {message.role === 'user' && onEditRetryMessage ? (
          <button
            type="button"
            role="menuitem"
            className={styles.messageActionItem}
            disabled={Boolean(busyMessageId)}
            onClick={() => openEditRetry(message)}
          >
            <PencilLine size={14} aria-hidden="true" />
            <span>编辑并重试</span>
          </button>
        ) : null}
      </div>,
      document.body,
    )
  }

  const submitEditRetry = async () => {
    if (!editingMessage || !onEditRetryMessage || busyMessageId) {
      return
    }
    setBusyMessageId(editingMessage.id)
    setActionError('')
    try {
      const liveDraft = typeof document !== 'undefined'
        ? document.querySelector<HTMLTextAreaElement>('textarea[data-edit-retry-textarea="true"]')?.value
        : undefined
      await onEditRetryMessage(editingMessage, liveDraft ?? editTextareaRef.current?.value ?? editDraft)
      setEditingMessage(null)
      setEditDraft('')
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '编辑并重试失败')
    } finally {
      setBusyMessageId('')
    }
  }

  const editRetryDialog = editingMessage && typeof document !== 'undefined'
    ? createPortal(
      <div className={styles.editOverlay}>
        <div className={styles.editBackdrop} onClick={() => busyMessageId ? undefined : setEditingMessage(null)} />
        <div className={styles.editDialog} role="dialog" aria-modal="true" aria-label="Edit and retry message">
          <div className={styles.editHeader}>
            <div className={styles.editTitle}>编辑并重试</div>
            <button type="button" className={styles.editIconButton} onClick={() => setEditingMessage(null)} disabled={Boolean(busyMessageId)} title="关闭">
              <X size={15} aria-hidden="true" />
            </button>
          </div>
          <textarea
            key={editingMessage.id}
            ref={editTextareaRef}
            className={styles.editTextarea}
            data-edit-retry-textarea="true"
            defaultValue={editDraft}
            onChange={(event) => setEditDraft(event.target.value)}
            autoFocus
          />
          {actionError ? <div className={styles.actionError}>{actionError}</div> : null}
          <div className={styles.editFooter}>
            <button type="button" className={styles.secondaryButton} onClick={() => setEditingMessage(null)} disabled={Boolean(busyMessageId)}>取消</button>
            <button type="button" className={styles.primaryButton} onClick={submitEditRetry} disabled={Boolean(busyMessageId) || !editDraft.trim()}>重试</button>
          </div>
        </div>
      </div>,
      document.body,
    )
    : null

  return (
    <div ref={containerRef} className={styles.scrollContainer} onScroll={handleScroll}>
      <AnimatePresence initial={false}>
        {messages.length === 0 && (
          <motion.div key="empty-state" className={styles.emptyState} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className={styles.emptyCopy}>
              {connected ? '随时可以开始对话。' : '正在连接服务，连接恢复后即可使用。'}
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
              layout={!isStreaming || !isLastAssistantTurn}
            >
              {message.role === 'assistant' && (
                <div className={styles.avatar}>
                  <Bot size={16} />
                </div>
              )}
              <div className={styles.message}>
                <div className={styles.messageInner}>
                  {isPersistedMessage(message) && (onSaveMessageAsProjectSource || (message.role === 'user' && onEditRetryMessage)) ? (
                    <div className={styles.messageActions}>
                      <button
                        type="button"
                        className={styles.messageActionTrigger}
                        title="消息操作"
                        aria-label="消息操作"
                        aria-haspopup="menu"
                        aria-expanded={openMenuMessageId === message.id}
                        onClick={(event) => {
                          setActionError('')
                          if (openMenuMessageId === message.id) {
                            setOpenMenuMessageId('')
                            return
                          }
                          updateMenuPosition(event.currentTarget, message)
                          setOpenMenuMessageId(message.id)
                        }}
                      >
                        <MoreHorizontal size={14} aria-hidden="true" />
                      </button>
                      {renderMessageActionMenu(message)}
                    </div>
                  ) : null}
                  <TurnBody
                    turn={message}
                    runtimeSnapshot={runtimeSnapshot}
                    isLastAssistantTurn={isLastAssistantTurn}
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
                {actionError && openMenuMessageId === message.id ? <div className={styles.inlineActionError}>{actionError}</div> : null}
              </div>
              {message.role === 'user' && (
                <div className={styles.avatar}>
                  <User size={16} />
                </div>
              )}
            </motion.div>
          )
        })}

      </AnimatePresence>
      {!autoFollowEnabled && isStreaming && (
        <button
          type="button"
          className={styles.resumeFollowBtn}
          onClick={() => {
            setAutoFollowEnabled(true)
            scrollToBottom('smooth')
          }}
        >
          回到底部继续追踪输出
        </button>
      )}
      {editRetryDialog}
    </div>
  )
}
