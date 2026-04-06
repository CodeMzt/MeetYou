import { useState } from 'react'
import { AlertCircle, HelpCircle } from 'lucide-react'
import MotionCard from '../common/MotionCard'
import type { ConfirmRequestPayload, HumanInputRequestPayload } from '../../types'
import styles from './ActionCard.module.css'

interface ActionCardProps {
  confirmRequest: ConfirmRequestPayload | null
  pendingHumanInput: HumanInputRequestPayload | null
  sendConfirmResponse: (requestId: string, accepted: boolean, metadata?: Record<string, unknown>) => void
  sendHumanInputResponse: (requestId: string, answerText: string, selectedOption?: string, metadata?: Record<string, unknown>) => void
}

export default function ActionCard({
  confirmRequest,
  pendingHumanInput,
  sendConfirmResponse,
  sendHumanInputResponse
}: ActionCardProps) {
  const [inputValue, setInputValue] = useState('')

  if (!confirmRequest && !pendingHumanInput) return null

  if (confirmRequest) {
    return (
      <div className={styles.cardWrapper}>
        <MotionCard className={styles.actionCard}>
          <div className={styles.header}>
            <AlertCircle className={styles.icon} size={18} />
            请求确认
          </div>
          <div className={styles.content}>{confirmRequest.content}</div>
          <div className={styles.buttonGroup}>
            <button className={`${styles.btn} ${styles.btnCancel}`} onClick={() => sendConfirmResponse(confirmRequest.requestId, false)}>
              拒绝
            </button>
            <button className={`${styles.btn} ${styles.btnConfirm}`} onClick={() => sendConfirmResponse(confirmRequest.requestId, true)}>
              允许执行
            </button>
          </div>
        </MotionCard>
      </div>
    )
  }

  if (pendingHumanInput) {
    return (
      <div className={styles.cardWrapper}>
        <MotionCard className={styles.actionCard}>
          <div className={styles.header}>
            <HelpCircle className={styles.icon} size={18} />
            需要补充信息
          </div>
          <div className={styles.content}>{pendingHumanInput.question}</div>
          
          <input 
            type="text" 
            className={styles.inputField}
            placeholder={pendingHumanInput.placeholder || '输入您的回答...'}
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && inputValue.trim()) {
                sendHumanInputResponse(pendingHumanInput.requestId, inputValue)
                setInputValue('')
              }
            }}
          />

          <div className={styles.buttonGroup}>
            {pendingHumanInput.options?.map(opt => (
              <button 
                key={opt}
                className={`${styles.btn} ${styles.btnCancel}`} 
                onClick={() => sendHumanInputResponse(pendingHumanInput.requestId, opt, opt)}
              >
                {opt}
              </button>
            ))}
            <button 
              className={`${styles.btn} ${styles.btnConfirm}`} 
              onClick={() => {
                sendHumanInputResponse(pendingHumanInput.requestId, inputValue)
                setInputValue('')
              }}
              disabled={!inputValue.trim()}
            >
              提交
            </button>
          </div>
        </MotionCard>
      </div>
    )
  }

  return null
}
