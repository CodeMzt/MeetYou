import React, { useMemo, useRef, useState } from 'react'
import { Send, Settings2, Sparkles, BrainCircuit, Square, Paperclip } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { AssistantMode, ThinkingOverride, ConfirmRequestPayload, HumanInputRequestPayload, RuntimeStateSnapshot, ConnectionState } from '../../types'
import styles from './ChatInput.module.css'

const THINKING_OPTIONS: Array<{ label: string; value: ThinkingOverride }> = [
  { label: '自动', value: 'default' },
  { label: '关闭', value: 'off' },
  { label: '低', value: 'low' },
  { label: '中', value: 'medium' },
  { label: '高', value: 'high' },
]

const MODE_OPTIONS: Array<{ label: string; value: AssistantMode }> = [
  { label: '通用', value: 'general' },
  { label: '研究', value: 'research' },
  { label: '文档', value: 'documents' },
  { label: '学习', value: 'study' },
  { label: '自动化', value: 'automation' },
  { label: '旦夕', value: 'danxi' },
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
  sendControlCommand?: (action: 'stop' | 'append_guidance' | 'regenerate' | 'rollback', params?: { guidance?: string; checkpoint_id?: string; turn_id?: string; stream_id?: string }) => void
  onUploadAttachment?: (file: File) => void
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
  runtimeSnapshot,
  sendControlCommand,
  onUploadAttachment,
}: ChatInputProps) {
  const [showOptions, setShowOptions] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const composerLocked = Boolean(confirmRequest || pendingHumanInput)
  const isBusy = ['thinking', 'tool_calling', 'answering'].includes(runtimeSnapshot?.status || '')

  const inputPlaceholder = useMemo(() => {
    if (!connected) {
      return connectionState === 'connecting' ? '正在连接后端，可先输入...' : '后端未连接，可先输入，连接后发送...'
    }
    if (confirmRequest) return '请在上方确认操作...'
    if (pendingHumanInput) return pendingHumanInput.placeholder || '请在上方补充输入...'
    if (isBusy) return '可输入补充要求...'
    if (runtimeSnapshot?.status === 'tool_calling') return '工具运行中...'
    return '问点什么...'
  }, [confirmRequest, connected, connectionState, pendingHumanInput, runtimeSnapshot, isBusy])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (inputVal.trim() && connected && !composerLocked) {
        if (isBusy) {
          sendControlCommand?.('append_guidance', { guidance: inputVal })
          setInputVal('')
        } else {
          onSend()
        }
      }
    }
  }

  return (
    <div className={styles.dockContainer}>
      <AnimatePresence>
        {showOptions && (
          <motion.div
            initial={{ opacity: 0, y: 10, scale: 0.95, transformOrigin: 'bottom left' }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 5, scale: 0.95 }}
            transition={{ type: 'spring', stiffness: 400, damping: 25 }}
            className={styles.optionsPopup}
          >
            <div className={styles.optionGroup}>
              <div className={styles.optionLabel}><Sparkles size={12} /> 模式</div>
              <div className={styles.segmentedControl}>
                {MODE_OPTIONS.map(opt => (
                  <button
                    key={opt.value}
                    className={`${styles.segmentBtn} ${preferredMode === opt.value ? styles.active : ''}`}
                    onClick={() => setPreferredMode(opt.value)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
            <div className={styles.optionDivider} />
            <div className={styles.optionGroup}>
              <div className={styles.optionLabel}><BrainCircuit size={12} /> 思考</div>
              <div className={styles.segmentedControl}>
                {THINKING_OPTIONS.map(opt => (
                  <button
                    key={opt.value}
                    className={`${styles.segmentBtn} ${thinkingOverride === opt.value ? styles.active : ''}`}
                    onClick={() => setThinkingOverride(opt.value)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className={`${styles.inputWrapper} ${composerLocked ? styles.locked : ''}`}>
        <button 
          className={styles.settingsBtn} 
          onClick={() => setShowOptions(!showOptions)}
          disabled={composerLocked}
          title="会话设置"
        >
          <Settings2 size={18} />
        </button>

        <button
          className={styles.settingsBtn}
          onClick={() => fileInputRef.current?.click()}
          disabled={composerLocked}
          title="上传附件"
        >
          <Paperclip size={18} />
        </button>

        <input
          ref={fileInputRef}
          type="file"
          className={styles.hiddenFileInput}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) {
              onUploadAttachment?.(file)
            }
            event.currentTarget.value = ''
          }}
        />

        <textarea
          className={styles.textarea}
          placeholder={inputPlaceholder}
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={composerLocked}
          rows={1}
          autoFocus
        />

        <button
          className={`${styles.sendBtn} ${inputVal.trim() && connected && !composerLocked ? styles.active : ''} ${isBusy && !inputVal.trim() ? styles.stopBtn : ''}`}
          onClick={() => {
            if (isBusy) {
              if (!inputVal.trim()) {
                sendControlCommand?.('stop')
              } else {
                sendControlCommand?.('append_guidance', { guidance: inputVal })
                setInputVal('')
              }
            } else {
              onSend()
            }
          }}
          disabled={!connected || composerLocked || (!isBusy && !inputVal.trim())}
          title={isBusy && !inputVal.trim() ? "停止生成" : isBusy ? "追加引导" : "发送"}
        >
          {isBusy && !inputVal.trim() ? <Square size={14} fill="currentColor" /> : <Send size={16} />}
        </button>
      </div>
    </div>
  )
}
