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
  onConfirm: () => void
  onCancel: () => void
}

export default function ConfirmModal({
  isOpen,
  title,
  message,
  confirmText = '确定',
  cancelText = '取消',
  isDestructive = false,
  onConfirm,
  onCancel
}: ConfirmModalProps) {
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
            onClick={onCancel}
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
              <button className={styles.closeBtn} onClick={onCancel} title="关闭">
                <X size={16} />
              </button>
            </div>
            <div className={styles.body}>
              <p className={styles.message}>{message}</p>
            </div>
            <div className={styles.footer}>
              <button className={styles.cancelBtn} onClick={onCancel}>
                {cancelText}
              </button>
              <button 
                className={`${styles.confirmBtn} ${isDestructive ? styles.destructiveBtn : styles.primaryBtn}`} 
                onClick={onConfirm}
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
