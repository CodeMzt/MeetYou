import { Settings, X, Minus, Square } from 'lucide-react'
import './dashboard.css'
import SettingsView from './views/SettingsView'

export default function SettingsWindow() {
  const handleClose = () => window.ipcRenderer?.send('window-close')
  const handleMinimize = () => window.ipcRenderer?.send('window-minimize')
  const handleMaximize = () => window.ipcRenderer?.send('window-maximize')

  return (
    <div className="dashboard-container">
      {/* Titlebar */}
      <div className="titlebar dashboard-titlebar">
        <div className="titlebar-title" style={{ paddingLeft: 8 }}>
          <Settings size={16} /> 设置中心
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

      <div className="dashboard-content" style={{ padding: 0 }}>
        <SettingsView />
      </div>
    </div>
  )
}
