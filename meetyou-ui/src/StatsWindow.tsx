import { useEffect, useState } from 'react'
import { Gauge, X, Minus, Square } from 'lucide-react'
import './dashboard.css'
import UsagePanel from './components/status/UsagePanel'
import { RuntimeDebugSnapshot, RuntimeUsageSnapshot } from './types'

export default function StatsWindow() {
  const handleClose = () => window.ipcRenderer?.send('window-close')
  const handleMinimize = () => window.ipcRenderer?.send('window-minimize')
  const handleMaximize = () => window.ipcRenderer?.send('window-maximize')

  const [usageSnapshot, setUsageSnapshot] = useState<RuntimeUsageSnapshot | null>(null)
  const [runtimeDebugSnapshot, setRuntimeDebugSnapshot] = useState<RuntimeDebugSnapshot | null>(null)

  useEffect(() => {
    // Listener for stats update
    const handleStatsUpdated = (_event: any, data: { usageSnapshot: RuntimeUsageSnapshot | null, runtimeDebugSnapshot: RuntimeDebugSnapshot | null }) => {
      setUsageSnapshot(data.usageSnapshot)
      setRuntimeDebugSnapshot(data.runtimeDebugSnapshot)
    }

    // Register IPC listener
    window.ipcRenderer?.on('stats-updated', handleStatsUpdated)

    // Request initial stats
    window.ipcRenderer?.send('request-stats')

    return () => {
      // Cleanup listener
      window.ipcRenderer?.off('stats-updated', handleStatsUpdated)
    }
  }, [])

  return (
    <div className="dashboard-container">
      {/* Titlebar */}
      <div className="titlebar dashboard-titlebar">
        <div className="titlebar-title" style={{ paddingLeft: 8 }}>
          <Gauge size={16} /> Token / Context 统计
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

      <div className="dashboard-content" style={{ padding: '20px', display: 'flex', flexDirection: 'column' }}>
        <UsagePanel usageSnapshot={usageSnapshot} runtimeDebugSnapshot={runtimeDebugSnapshot} />
      </div>
    </div>
  )
}
