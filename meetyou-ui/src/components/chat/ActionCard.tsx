import { useState } from 'react'
import { AlertCircle, HelpCircle, Clock, CheckCircle } from 'lucide-react'
import MotionCard from '../common/MotionCard'
import type { ChatTurn } from '../../types'
import styles from './ActionCard.module.css'

interface ActionCardProps {
  turn: ChatTurn
  sendConfirmResponse: (requestId: string, accepted: boolean, approvalId?: string) => void
  sendHumanInputResponse: (requestId: string, answerText: string, selectedOption?: string) => void
}

export default function ActionCard({
  turn,
  sendConfirmResponse,
  sendHumanInputResponse,
}: ActionCardProps) {
  const [inputValue, setInputValue] = useState('')

  const { confirmRequest, confirmResponse, humanInputRequest, humanInputResponse } = turn

  if (!confirmRequest && !humanInputRequest) return null

  if (confirmResponse) {
    return (
      <div className={styles.cardWrapper}>
        <div className={`${styles.actionCard} ${styles.resolvedCard}`}>
          <CheckCircle size={14} className={styles.resolvedIcon} />
          <span className={styles.resolvedLabel}>
            {confirmResponse.accepted ? '已允许执行' : '已拒绝执行'}
          </span>
        </div>
      </div>
    )
  }

  if (humanInputResponse) {
    return (
      <div className={styles.cardWrapper}>
        <div className={`${styles.actionCard} ${styles.resolvedCard}`}>
          <CheckCircle size={14} className={styles.resolvedIcon} />
          <div className={styles.resolvedLabel}>补充信息：</div>
          <div className={styles.resolvedContent}>
            {humanInputResponse.selectedOption || humanInputResponse.answerText}
          </div>
        </div>
      </div>
    )
  }

  if (confirmRequest) {
    return (
      <div className={styles.cardWrapper}>
        <MotionCard className={`${styles.actionCard} ${confirmRequest.defaultDecision !== undefined ? styles.blocking : ''}`}>
          <div className={styles.header}>
            <AlertCircle className={styles.icon} size={18} />
            <div className={styles.titleWrap}>
              <span className={styles.title}>请求确认</span>
              {confirmRequest.defaultDecision !== undefined && <span className={styles.badge}>阻塞运行</span>}
            </div>
          </div>
          <div className={styles.content}>{confirmRequest.content}</div>
          
          <div className={styles.footer}>
            <div className={styles.metadata}>
              {confirmRequest.timeout !== undefined && (
                <span className={styles.metaItem}>
                  <Clock size={12} />
                  {confirmRequest.timeout}s 后自动{confirmRequest.defaultDecision ? '允许' : '拒绝'}
                </span>
              )}
            </div>
            <div className={styles.buttonGroup}>
              <button className={`${styles.btn} ${styles.btnCancel}`} onClick={() => sendConfirmResponse(confirmRequest.requestId, false, confirmRequest.approvalId)}>
                拒绝
              </button>
              <button className={`${styles.btn} ${styles.btnConfirm}`} onClick={() => sendConfirmResponse(confirmRequest.requestId, true, confirmRequest.approvalId)}>
                允许执行
              </button>
            </div>
          </div>
        </MotionCard>
      </div>
    )
  }

  if (humanInputRequest) {
    return (
      <div className={styles.cardWrapper}>
        <MotionCard className={styles.actionCard}>
          <div className={styles.header}>
            <HelpCircle className={styles.icon} size={18} />
            需要补充信息
          </div>
          <div className={styles.content}>{humanInputRequest.question}</div>
          
          <input 
            type="text" 
            className={styles.inputField}
            placeholder={humanInputRequest.placeholder || '输入您的回答...'}
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && inputValue.trim()) {
                sendHumanInputResponse(humanInputRequest.requestId, inputValue)
                setInputValue('')
              }
            }}
          />

          <div className={styles.buttonGroup}>
            {humanInputRequest.options?.map(opt => (
              <button 
                key={opt}
                className={`${styles.btn} ${styles.btnCancel}`} 
                onClick={() => sendHumanInputResponse(humanInputRequest.requestId, opt, opt)}
              >
                {opt}
              </button>
            ))}
            <button 
              className={`${styles.btn} ${styles.btnConfirm}`} 
              onClick={() => {
                sendHumanInputResponse(humanInputRequest.requestId, inputValue)
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
