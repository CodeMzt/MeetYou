import { useState, useEffect } from 'react'
import { ShieldAlert, Sparkles } from 'lucide-react'
import { motion } from 'framer-motion'
import { ConfirmRequestPayload, HumanInputRequestPayload } from '../../types'
import styles from './InteractionPanels.module.css'

interface ConfirmModalProps {
  request: ConfirmRequestPayload
  onConfirm: (requestId: string, accepted: boolean) => void
}

export function ConfirmModal({ request, onConfirm }: ConfirmModalProps) {
  return (
    <motion.div
      className={styles.modalConfirm}
      initial={{ opacity: 0, y: 10, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
    >
      <div className={styles.confirmHeader}>
        <ShieldAlert size={16} color="#ff3b30" />
        <span>危险操作确认</span>
      </div>
      <div className={styles.body}>{request.content}</div>
      <div className={styles.actions}>
        <button className={`${styles.btn} ${styles.reject}`} onClick={() => onConfirm(request.requestId, false)}>
          拒绝
        </button>
        <button className={`${styles.btn} ${styles.accept}`} onClick={() => onConfirm(request.requestId, true)}>
          允许
        </button>
      </div>
    </motion.div>
  )
}

interface HumanInputPanelProps {
  request: HumanInputRequestPayload
  connected: boolean
  onSubmit: (requestId: string, val: string, option?: string) => void
}

export function HumanInputPanel({ request, connected, onSubmit }: HumanInputPanelProps) {
  const [val, setVal] = useState('')

  useEffect(() => {
    setVal('')
  }, [request.requestId])

  const handleSubmit = () => {
    if (!val.trim() || !connected) return
    onSubmit(request.requestId, val)
  }

  return (
    <motion.div
      className={styles.modalInput}
      initial={{ opacity: 0, y: 10, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
    >
      <div className={styles.inputHeader}>
        <Sparkles size={16} color="var(--accent-color)" />
        <span>继续当前步骤前，需要你补充一下</span>
      </div>
      <div className={styles.body}>{request.question}</div>
      
      {request.options.length > 0 && (
        <div className={styles.options}>
          {request.options.map((option) => (
            <button
              key={option}
              className={styles.optionBtn}
              onClick={() => onSubmit(request.requestId, option, option)}
            >
              {option}
            </button>
          ))}
        </div>
      )}
      
      <div className={styles.formContainer}>
        <input
          className={styles.inputField}
          placeholder={request.placeholder || '输入你的补充信息'}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSubmit()
            }
          }}
        />
        <button
          className={styles.submitBtn}
          onClick={handleSubmit}
          disabled={!val.trim() || !connected}
        >
          提交
        </button>
      </div>
    </motion.div>
  )
}
