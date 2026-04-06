import { motion, HTMLMotionProps } from 'framer-motion'
import { ReactNode } from 'react'

interface MotionCardProps extends HTMLMotionProps<'div'> {
  children: ReactNode
  className?: string
  glass?: boolean
}

export default function MotionCard({ children, className = '', glass = true, ...props }: MotionCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
      className={`${glass ? 'glass-panel' : ''} ${className}`}
      {...props}
    >
      {children}
    </motion.div>
  )
}
