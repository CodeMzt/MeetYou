import type { ReactNode, SelectHTMLAttributes } from 'react'
import { ChevronDown } from 'lucide-react'

type GlassSelectProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, 'className'> & {
  children: ReactNode
  selectClassName?: string
  wrapperClassName?: string
}

export default function GlassSelect({
  children,
  selectClassName = '',
  wrapperClassName = '',
  ...props
}: GlassSelectProps) {
  const wrapperClasses = ['glass-select', wrapperClassName].filter(Boolean).join(' ')
  const selectClasses = ['glass-select-native', selectClassName].filter(Boolean).join(' ')

  return (
    <div className={wrapperClasses}>
      <select className={selectClasses} {...props}>
        {children}
      </select>
      <ChevronDown size={14} className="glass-select-icon" aria-hidden="true" />
    </div>
  )
}
