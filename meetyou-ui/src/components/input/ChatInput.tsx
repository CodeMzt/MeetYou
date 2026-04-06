import React, { useMemo } from 'react'
import { Send } from 'lucide-react'
import GlassSelect from '../GlassSelect'
import { AssistantMode, ThinkingOverride, ConfirmRequestPayload, HumanInputRequestPayload, RuntimeStateSnapshot, ConnectionState } from '../../types'
import styles from './ChatInput.module.css'

const THINKING_OPTIONS: Array<{ label: string; value: ThinkingOverride }> = [
  { label: '跟随默认', value: 'default' },
  { label: '关闭', value: 'off' },
  { label: '低', value: 'low' },
  { label: '中', value: 'medium' },
  { label: '高', value: 'high' },
]

const MODE_OPTIONS: Array<{ label: string; value: AssistantMode }> = [
  { label: 'Normal', value: 'normal' },
  { label: 'Brain Decides', value: 'auto' },
  { label: 'Documents', value: 'documents' },
  { label: 'Research', value: 'research' },
  { label: 'Office', value: 'office' },
  { label: 'Study', value: 'study' },
]

interface ChatInputProps {
  connected: boolean
  connectionState: ConnectionState
  inputVal: string
  setInputVal: (val: string) => void
  preferredMode: AssistantMode
  setPreferredMode: (mode: AssistantMode) => void
  thinkingOverride: ThinkingOverride
  setThinkingOverride: (value: ThinkingOverride) => void
  onSend: () => void
  confirmRequest: ConfirmRequestPayload | null
  pendingHumanInput: HumanInputRequestPayload | null
  runtimeSnapshot: RuntimeStateSnapshot | null
}

export default function ChatInput({
  connected,
  connectionState,
  inputVal,
  setInputVal,
  preferredMode,
  setPreferredMode,
  thinkingOverride,
  setThinkingOverride,
  onSend,
  confirmRequest,
  pendingHumanInput,
  runtimeSnapshot
}: ChatInputProps) {
  const composerLocked = Boolean(confirmRequest || pendingHumanInput)

  const inputPlaceholder = useMemo(() => {
    if (!connected) {
      return connectionState === 'connecting' ? '正在连接后端服务…' : '等待后端服务启动…'
    }
    if (confirmRequest) {
      return '请先处理确认请求'
    }
    if (pendingHumanInput) {
      return pendingHumanInput.placeholder || '请先回答当前问题'
    }
    if (runtimeSnapshot?.status === 'tool_calling') {
      return '工具执行中，请稍候…'
    }
    return '输入消息，按 Enter 发送'
  }, [confirmRequest, connected, connectionState, pendingHumanInput, runtimeSnapshot])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (inputVal.trim() && connected && !composerLocked) {
        onSend()
      }
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.composerRow}>
        <div className={styles.toolbar}>
          <label className={styles.label} htmlFor="mode-override">
            Mode
          </label>
          <GlassSelect
            id="mode-override"
            wrapperClassName={styles.selectWrap}
            value={preferredMode}
            onChange={(e) => setPreferredMode(e.target.value as AssistantMode)}
            disabled={!connected || composerLocked}
            title={
              preferredMode === 'normal'
                ? 'Normal keeps everyday conversation and lightweight web search in one mode, and may upgrade only when needed.'
                : preferredMode === 'auto'
                  ? 'Brain decides the mode and may switch it during the turn.'
                  : 'The selected mode is locked for this turn.'
            }
          >
            {MODE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </GlassSelect>
          <label className={styles.label} htmlFor="thinking-override">
            本次推理
          </label>
          <GlassSelect
            id="thinking-override"
            wrapperClassName={styles.selectWrap}
            value={thinkingOverride}
            onChange={(e) => setThinkingOverride(e.target.value as ThinkingOverride)}
            disabled={!connected || composerLocked}
          >
            {THINKING_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </GlassSelect>
        </div>
        <div className={styles.inputRow}>
          <input
            className={styles.chatInput}
            placeholder={inputPlaceholder}
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={!connected || composerLocked}
            autoFocus
          />
          <button
            className={styles.sendBtn}
            onClick={onSend}
            disabled={!inputVal.trim() || !connected || composerLocked}
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  )
}
