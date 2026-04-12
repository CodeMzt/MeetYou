import React, { ReactNode } from 'react'
import { X, Minus, Square } from 'lucide-react'
import '../../dashboard.css'

interface SubWindowProps {
  title: ReactNode
  icon?: ReactNode
  children: ReactNode
  contentStyle?: React.CSSProperties
  className?: string
}

export default function SubWindow({ title, icon, children, contentStyle, className = '' }: SubWindowProps) {
  const handleClose = () => window.ipcRenderer?.send('window-close')
  const handleMinimize = () => window.ipcRenderer?.send('window-minimize')
  const handleMaximize = () => window.ipcRenderer?.send('window-maximize')

  return (
    <div className={`dashboard-container ${className}`.trim()}>
      <div className="titlebar dashboard-titlebar">
        <div className="titlebar-title" style={{ paddingLeft: 8 }}>
          {icon} {title}
        </div>
        <div style={{ flex: 1 }} />
        <div className="window-controls">
          <button className="win-btn minimize" onClick={handleMinimize} title="最小化">
            <Minus size={14} />
          </button>
          <button className="win-btn maximize" onClick={handleMaximize} title="最大化">
            <Square size={12} />
          </button>
          <button className="win-btn close" onClick={handleClose} title="关闭">
            <X size={14} />
          </button>
        </div>
      </div>

      {contentStyle ? (
        <div className="dashboard-content" style={contentStyle}>
          {children}
        </div>
      ) : (
        children
      )}
    </div>
  )
}
