import { useEffect, useState } from 'react'
import { Gauge, Minus, Square, X } from 'lucide-react'
import './dashboard.css'
import UsagePanel from './components/status/UsagePanel'
import type { RuntimeUsageSnapshot } from './types'

type StatsPayload = {
  usageSnapshot: RuntimeUsageSnapshot | null
}

export default function ContextWindow() {
  const handleClose = () => window.ipcRenderer?.send('window-close')
  const handleMinimize = () => window.ipcRenderer?.send('window-minimize')
  const handleMaximize = () => window.ipcRenderer?.send('window-maximize')
  const [usageSnapshot, setUsageSnapshot] = useState<RuntimeUsageSnapshot | null>(null)

  useEffect(() => {
    const handleStatsUpdated = (_event: unknown, data: StatsPayload | null) => {
      setUsageSnapshot(data?.usageSnapshot ?? null)
    }

    window.ipcRenderer?.on('stats-updated', handleStatsUpdated)
    window.ipcRenderer?.send('request-stats')

    return () => {
      window.ipcRenderer?.off('stats-updated', handleStatsUpdated)
    }
  }, [])

  return (
    <div className="dashboard-container">
      <div className="titlebar dashboard-titlebar">
        <div className="titlebar-title" style={{ paddingLeft: 8 }}>
          <Gauge size={16} /> 上下文与用量
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
        <UsagePanel usageSnapshot={usageSnapshot} runtimeDebugSnapshot={null} />
      </div>
    </div>
  )
}
