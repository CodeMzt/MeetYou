import React, { useState, useRef, useEffect, ReactNode } from 'react'
import { ChevronDown, Check } from 'lucide-react'

type GlassSelectProps = {
  children: ReactNode
  value?: string | number | readonly string[]
  onChange?: (event: any) => void
  disabled?: boolean
  wrapperClassName?: string
  title?: string
}

export default function GlassSelect({
  children,
  value,
  onChange,
  disabled,
  wrapperClassName = '',
  title
}: GlassSelectProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const options: Array<{ value: any, label: ReactNode }> = []
  React.Children.forEach(children, child => {
    if (React.isValidElement(child) && child.type === 'option') {
      options.push({ value: child.props.value, label: child.props.children })
    }
  })

  const selectedOption = options.find(o => String(o.value) === String(value))
  const displayLabel = selectedOption ? selectedOption.label : 'Select...'

  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleOutside)
    return () => document.removeEventListener('mousedown', handleOutside)
  }, [])

  const handleSelect = (val: any) => {
    setOpen(false)
    if (onChange && val !== value) {
      onChange({ target: { value: val } })
    }
  }

  const wrapperClasses = ['glass-select-custom', wrapperClassName, disabled ? 'disabled' : ''].filter(Boolean).join(' ')

  return (
    <div className={wrapperClasses} ref={containerRef} title={title}>
      <div 
        className="glass-select-trigger" 
        onClick={() => !disabled && setOpen(!open)}
      >
        <span className="glass-select-value">{displayLabel}</span>
        <ChevronDown size={14} className="glass-select-icon" aria-hidden="true" />
      </div>
      
      {open && !disabled && (
        <div className="glass-select-dropdown">
          {options.map((opt, i) => (
            <div 
              key={i}
              className={`glass-select-option ${String(opt.value) === String(value) ? 'selected' : ''}`}
              onClick={() => handleSelect(opt.value)}
            >
              <span className="glass-select-option-label">{opt.label}</span>
              {String(opt.value) === String(value) && <Check size={14} className="glass-select-check" />}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
