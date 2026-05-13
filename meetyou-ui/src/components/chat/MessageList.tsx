import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { User, Bot, Clock, Download, FolderPlus, GitFork, MoreHorizontal, PencilLine, Play, RefreshCw, RotateCcw, Square, X } from 'lucide-react'
import { ChatTurn, HumanInputRequestPayload, RuntimeHealthSnapshot, RuntimeStateSnapshot, RuntimeErrorPayload, ApprovalDisplayModel, RuntimeConversationCheckpoint, RuntimeResearchTask, RuntimeResearchTaskEvent } from '../../types'
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
  checkpoints?: RuntimeConversationCheckpoint[]
  researchTasks?: RuntimeResearchTask[]
  researchTaskEvents?: Record<string, RuntimeResearchTaskEvent[]>
  researchBusy?: boolean
  sendConfirmResponse: (requestId: string, accepted: boolean, approvalId?: string) => void
  sendHumanInputResponse: (requestId: string, val: string, option?: string) => void
  sendControlCommand?: (action: 'stop' | 'append_guidance' | 'regenerate' | 'rollback', params?: { guidance?: string; checkpoint_id?: string; turn_id?: string; stream_id?: string }) => void
  onSaveMessageAsProjectSource?: (message: ChatTurn) => Promise<unknown>
  onEditRetryMessage?: (message: ChatTurn, content: string) => Promise<unknown>
  onArtifactDownload?: (artifactId: string) => Promise<unknown> | unknown
  onRestoreCheckpoint?: (checkpointId: string) => Promise<unknown>
  onCheckoutCheckpoint?: (checkpointId: string) => Promise<unknown>
  onStartResearchTask?: (taskId: string) => Promise<unknown>
  onCancelResearchTask?: (taskId: string) => Promise<unknown>
  onDownloadResearchTaskArtifact?: (task: RuntimeResearchTask) => Promise<unknown>
  onRefreshResearchTasks?: () => Promise<unknown> | unknown
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
  checkpoints = [],
  researchTasks = [],
  researchTaskEvents = {},
  researchBusy = false,
  sendConfirmResponse,
  sendHumanInputResponse,
  sendControlCommand,
  onSaveMessageAsProjectSource,
  onEditRetryMessage,
  onArtifactDownload,
  onRestoreCheckpoint,
  onCheckoutCheckpoint,
  onStartResearchTask,
  onCancelResearchTask,
  onDownloadResearchTaskArtifact,
  onRefreshResearchTasks,
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
  const checkpointByMessageId = useMemo(
    () => new Map(checkpoints.map((checkpoint) => [checkpoint.message_id, checkpoint])),
    [checkpoints],
  )
  const isStreaming = ['thinking', 'tool_calling', 'answering'].includes(runtimeSnapshot?.status || '')
  const visibleResearchTask = useMemo(() => {
    const candidates = researchTasks
      .filter((task) => {
        const status = String(task.status || '').toLowerCase()
        const metadata = task.metadata || {}
        return ['planned', 'approved', 'running', 'failed', 'cancelled'].includes(status)
          || (status === 'completed' && !String(metadata.delivery_message_id || '').trim())
      })
      .sort((a, b) => {
        const activeWeight = (task: RuntimeResearchTask) => String(task.status || '').toLowerCase() === 'running' ? 0 : 1
        return activeWeight(a) - activeWeight(b)
          || Date.parse(b.updated_at || b.created_at || '') - Date.parse(a.updated_at || a.created_at || '')
      })
    return candidates[0] || null
  }, [researchTasks])
  const runResearchTaskAction = async (
    task: RuntimeResearchTask,
    action: 'start' | 'cancel' | 'download' | 'refresh',
  ) => {
    if (researchBusy || busyMessageId) {
      return
    }
    setBusyMessageId(`research:${task.research_task_id}:${action}`)
    setActionError('')
    try {
      if (action === 'start') {
        await onStartResearchTask?.(task.research_task_id)
      } else if (action === 'cancel') {
        await onCancelResearchTask?.(task.research_task_id)
      } else if (action === 'download') {
        await onDownloadResearchTaskArtifact?.(task)
      } else {
        await onRefreshResearchTasks?.()
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '研究任务操作失败')
    } finally {
      setBusyMessageId('')
    }
  }

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

  useEffect(() => {
    if (!openMenuMessageId || typeof document === 'undefined') {
      return
    }
    const close = (event: MouseEvent | PointerEvent) => {
      const target = event.target as Element | null
      if (!target) {
        return
      }
      if (menuRef.current?.contains(target)) {
        return
      }
      if (target.closest(`[data-message-action-trigger="${openMenuMessageId}"]`)) {
        return
      }
      setOpenMenuMessageId('')
      setActionError('')
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpenMenuMessageId('')
        setActionError('')
      }
    }
    document.addEventListener('pointerdown', close, true)
    document.addEventListener('mousedown', close, true)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', close, true)
      document.removeEventListener('mousedown', close, true)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [openMenuMessageId])

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
    const width = 176
    const checkpoint = checkpointByMessageId.get(message.id)
    const itemCount = (onSaveMessageAsProjectSource ? 1 : 0)
      + (message.role === 'user' && onEditRetryMessage ? 1 : 0)
      + (checkpoint && onRestoreCheckpoint ? 1 : 0)
      + (checkpoint && onCheckoutCheckpoint ? 1 : 0)
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

  const runCheckpointAction = async (message: ChatTurn, action: 'restore' | 'checkout') => {
    const checkpoint = checkpointByMessageId.get(message.id)
    const handler = action === 'restore' ? onRestoreCheckpoint : onCheckoutCheckpoint
    if (!checkpoint || !handler || busyMessageId) {
      return
    }
    setBusyMessageId(message.id)
    setActionError('')
    try {
      await handler(checkpoint.checkpoint_id)
      setOpenMenuMessageId('')
    } catch (error) {
      setActionError(error instanceof Error ? error.message : action === 'restore' ? '恢复到此处失败' : '从此处签出失败')
    } finally {
      setBusyMessageId('')
    }
  }

  const renderResearchStatusBubble = () => {
    const task = visibleResearchTask
    if (!task) {
      return null
    }
    const metadata = task.metadata || {}
    const progress = (metadata.progress && typeof metadata.progress === 'object' ? metadata.progress : {}) as Record<string, unknown>
    const events = researchTaskEvents[task.research_task_id] || []
    const latestEvent = events[events.length - 1]
    const latestPayload = (latestEvent?.payload && typeof latestEvent.payload === 'object' ? latestEvent.payload : {}) as Record<string, unknown>
    const status = String(task.status || '').toLowerCase()
    const provider = String(metadata.research_provider || progress.research_provider || latestPayload.research_provider || 'gpt_researcher')
    const adapterStatus = String(metadata.adapter_status || progress.adapter_status || latestPayload.adapter_status || status || 'running')
    const stage = String(progress.stage || latestPayload.stage || adapterStatus || 'adapter')
    const progressMessage = String(progress.message || latestPayload.message || task.summary || '外部研究服务正在运行')
    const sourceCount = Number(
      metadata.adapter_source_count
      || progress.adapter_source_count
      || latestPayload.adapter_source_count
      || task.evidence_ledger?.length
      || 0,
    )
    const artifactId = String(task.artifact?.artifact_id || task.artifact_id || metadata.artifact_id || '')
    const externalRunId = String(metadata.external_run_id || progress.external_run_id || latestPayload.external_run_id || '')
    const adapterError = String(metadata.adapter_error || progress.adapter_error || latestPayload.adapter_error || '')
    const updatedAt = String(progress.at || latestPayload.at || task.updated_at || task.created_at || '')
    const elapsedMs = Math.max(0, Date.now() - (Date.parse(task.created_at || '') || Date.now()))
    const elapsedMinutes = Math.floor(elapsedMs / 60000)
    const elapsedSeconds = Math.floor((elapsedMs % 60000) / 1000)
    const statusLabel = ({
      planned: '计划待确认',
      approved: '计划已确认',
      running: '研究运行中',
      completed: '研究已完成',
      failed: '研究失败',
      cancelled: '研究已取消',
    } as Record<string, string>)[status] || task.status || '研究任务'
    const canStart = ['planned', 'approved'].includes(status) && Boolean(onStartResearchTask)
    const canCancel = status === 'running' && Boolean(onCancelResearchTask)
    const canDownload = Boolean(artifactId && onDownloadResearchTaskArtifact)

    return (
      <motion.div
        key={`research-status-${task.research_task_id}`}
        className={`${styles.messageWrapper} ${styles.assistant} ${styles.researchStatusWrapper}`}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring', stiffness: 400, damping: 30 }}
        data-research-status-bubble="true"
      >
        <div className={styles.avatar}>
          <Bot size={16} />
        </div>
        <div className={styles.message}>
          <div className={`${styles.messageInner} ${styles.researchStatusInner}`}>
            <div className={styles.researchHeader}>
              <div className={styles.researchTitle}>{task.topic || '深度研究'}</div>
              <span className={`${styles.researchBadge} ${styles[`research_${status}`] || ''}`}>{statusLabel}</span>
            </div>
            <div className={styles.researchProgressLine}>{progressMessage}</div>
            <div className={styles.researchMetaGrid}>
              <span>服务：{provider}</span>
              <span>阶段：{stage}</span>
              <span>状态：{adapterStatus}</span>
              <span>来源：{sourceCount || 0}</span>
              <span><Clock size={12} aria-hidden="true" /> {elapsedMinutes > 0 ? `${elapsedMinutes}分${elapsedSeconds}秒` : `${elapsedSeconds}秒`}</span>
              {updatedAt ? <span>更新：{new Date(updatedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span> : null}
            </div>
            {externalRunId ? <div className={styles.researchRunId}>运行：{externalRunId}</div> : null}
            {adapterError ? <div className={styles.researchError}>错误：{adapterError}</div> : null}
            <div className={styles.researchActions}>
              {canStart ? (
                <button type="button" className={styles.researchActionButton} disabled={researchBusy || Boolean(busyMessageId)} onClick={() => void runResearchTaskAction(task, 'start')}>
                  <Play size={13} aria-hidden="true" /> 开始
                </button>
              ) : null}
              {canCancel ? (
                <button type="button" className={styles.researchActionButton} disabled={researchBusy || Boolean(busyMessageId)} onClick={() => void runResearchTaskAction(task, 'cancel')}>
                  <Square size={12} aria-hidden="true" /> 取消
                </button>
              ) : null}
              {canDownload ? (
                <button type="button" className={styles.researchActionButton} disabled={researchBusy || Boolean(busyMessageId)} onClick={() => void runResearchTaskAction(task, 'download')}>
                  <Download size={13} aria-hidden="true" /> 下载报告
                </button>
              ) : null}
              {onRefreshResearchTasks ? (
                <button type="button" className={styles.researchIconButton} disabled={researchBusy || Boolean(busyMessageId)} onClick={() => void runResearchTaskAction(task, 'refresh')} title="刷新研究状态" aria-label="刷新研究状态">
                  <RefreshCw size={13} aria-hidden="true" />
                </button>
              ) : null}
            </div>
            {actionError && !openMenuMessageId && !editingMessage ? <div className={styles.inlineActionError}>{actionError}</div> : null}
          </div>
        </div>
      </motion.div>
    )
  }

  const renderMessageActionMenu = (message: ChatTurn) => {
    if (openMenuMessageId !== message.id || typeof document === 'undefined') {
      return null
    }
    const checkpoint = checkpointByMessageId.get(message.id)
    return createPortal(
      <div className={styles.messageActionMenu} role="menu" style={menuStyle} ref={menuRef}>
        {onSaveMessageAsProjectSource ? (
          <button
            type="button"
            role="menuitem"
            className={styles.messageActionItem}
            data-message-action="save-source"
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
            data-message-action="edit-retry"
            disabled={Boolean(busyMessageId)}
            onClick={() => openEditRetry(message)}
          >
            <PencilLine size={14} aria-hidden="true" />
            <span>编辑并重试</span>
          </button>
        ) : null}
        {checkpoint && onRestoreCheckpoint ? (
          <button
            type="button"
            role="menuitem"
            className={styles.messageActionItem}
            data-message-action="restore-checkpoint"
            disabled={Boolean(busyMessageId)}
            onClick={() => void runCheckpointAction(message, 'restore')}
          >
            <RotateCcw size={14} aria-hidden="true" />
            <span>恢复到此处</span>
          </button>
        ) : null}
        {checkpoint && onCheckoutCheckpoint ? (
          <button
            type="button"
            role="menuitem"
            className={styles.messageActionItem}
            data-message-action="checkout-checkpoint"
            disabled={Boolean(busyMessageId)}
            onClick={() => void runCheckpointAction(message, 'checkout')}
          >
            <GitFork size={14} aria-hidden="true" />
            <span>从此处签出</span>
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
            <button type="button" className={styles.primaryButton} data-edit-retry-submit="true" onClick={submitEditRetry} disabled={Boolean(busyMessageId) || !editDraft.trim()}>重试</button>
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
                  {isPersistedMessage(message) && (onSaveMessageAsProjectSource || (message.role === 'user' && onEditRetryMessage) || ((onRestoreCheckpoint || onCheckoutCheckpoint) && checkpointByMessageId.has(message.id))) ? (
                    <div className={styles.messageActions}>
                      <button
                        type="button"
                        className={styles.messageActionTrigger}
                        title="消息操作"
                        aria-label="消息操作"
                        aria-haspopup="menu"
                        aria-expanded={openMenuMessageId === message.id}
                        data-message-action-trigger={message.id}
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
                    onArtifactDownload={onArtifactDownload}
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

        {renderResearchStatusBubble()}

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
