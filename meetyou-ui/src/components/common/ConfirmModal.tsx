import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertTriangle, X } from 'lucide-react'
import styles from './ConfirmModal.module.css'

interface ConfirmModalProps {
  isOpen: boolean
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  isDestructive?: boolean
  confirmationLabel?: string
  confirmationHint?: string
  confirmationText?: string
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export default function ConfirmModal({
  isOpen,
  title,
  message,
  confirmText = '确认',
  cancelText = '取消',
  isDestructive = false,
  confirmationLabel = '确认文本',
  confirmationHint = '',
  confirmationText = '',
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const [typedValue, setTypedValue] = useState('')

  useEffect(() => {
    if (!isOpen) {
      setTypedValue('')
    }
  }, [isOpen])

  const confirmationRequired = confirmationText.trim().length > 0
  const confirmDisabled = useMemo(() => {
    if (!confirmationRequired) {
      return false
    }
    return typedValue.trim() !== confirmationText.trim()
  }, [confirmationRequired, typedValue, confirmationText])

  return (
    <AnimatePresence>
      {isOpen && (
        <div className={styles.overlay}>
          <motion.div
            className={styles.backdrop}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={busy ? undefined : onCancel}
          />
          <motion.div
            className={styles.modal}
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
          >
            <div className={styles.header}>
              <div className={`${styles.iconWrapper} ${isDestructive ? styles.destructiveIcon : styles.primaryIcon}`}>
                <AlertTriangle size={18} />
              </div>
              <h3 className={styles.title}>{title}</h3>
              <button className={styles.closeBtn} onClick={onCancel} title="关闭" disabled={busy}>
                <X size={16} />
              </button>
            </div>
            <div className={styles.body}>
              <p className={styles.message}>{message}</p>
              {confirmationRequired ? (
                <div className={styles.confirmationBlock}>
                  <div className={styles.confirmationLabelRow}>
                    <span className={styles.confirmationLabel}>{confirmationLabel}</span>
                    <code className={styles.confirmationCode}>{confirmationText}</code>
                  </div>
                  {confirmationHint ? <p className={styles.confirmationHint}>{confirmationHint}</p> : null}
                  <input
                    className={styles.confirmationInput}
                    value={typedValue}
                    onChange={(event) => setTypedValue(event.target.value)}
                    placeholder={confirmationText}
                    autoFocus
                  />
                </div>
              ) : null}
            </div>
            <div className={styles.footer}>
              <button className={styles.cancelBtn} onClick={onCancel} disabled={busy}>
                {cancelText}
              </button>
              <button
                className={`${styles.confirmBtn} ${isDestructive ? styles.destructiveBtn : styles.primaryBtn}`}
                onClick={onConfirm}
                disabled={confirmDisabled || busy}
              >
                {confirmText}
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
