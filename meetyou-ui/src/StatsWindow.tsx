import { useEffect, useState } from 'react'
import { Gauge, X, Minus, Square } from 'lucide-react'
import './dashboard.css'
import UsagePanel from './components/status/UsagePanel'
import { fetchWithAuth } from './apiClient'
import { parseRuntimeDebugEnvelope } from './protocolClient'
import { RuntimeDebugSnapshot, RuntimeUsageSnapshot } from './types'

export default function StatsWindow() {
  const handleClose = () => window.ipcRenderer?.send('window-close')
  const handleMinimize = () => window.ipcRenderer?.send('window-minimize')
  const handleMaximize = () => window.ipcRenderer?.send('window-maximize')

  const [usageSnapshot, setUsageSnapshot] = useState<RuntimeUsageSnapshot | null>(null)
  const [runtimeDebugSnapshot, setRuntimeDebugSnapshot] = useState<RuntimeDebugSnapshot | null>(null)
  const [sessionId, setSessionId] = useState('')
  const [baseUrl, setBaseUrl] = useState('http://127.0.0.1:8000')

  useEffect(() => {
    if (!sessionId) {
      setRuntimeDebugSnapshot(null)
      return
    }

    let cancelled = false

    const loadDebug = async () => {
      try {
        const response = await fetchWithAuth(
          `${baseUrl}/developer/runtime/debug?session_id=${encodeURIComponent(sessionId)}`,
        )
        if (!response.ok) {
          return
        }
        const snapshot = parseRuntimeDebugEnvelope(await response.json())
        if (!cancelled) {
          setRuntimeDebugSnapshot(snapshot)
        }
      } catch (error) {
        if (!cancelled) {
          console.error('Failed to load runtime debug snapshot:', error)
        }
      }
    }

    void loadDebug()
    const timer = window.setInterval(() => {
      void loadDebug()
    }, 2000)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [baseUrl, sessionId])

  useEffect(() => {
    // Listener for stats update
    const handleStatsUpdated = (_event: any, data: { usageSnapshot: RuntimeUsageSnapshot | null, sessionId?: string, baseUrl?: string }) => {
      setUsageSnapshot(data.usageSnapshot)
      setSessionId(data.sessionId || '')
      setBaseUrl(data.baseUrl || 'http://127.0.0.1:8000')
    }

    // Register IPC listener
    window.ipcRenderer?.on('devtools-updated', handleStatsUpdated)

    window.ipcRenderer?.send('request-devtools')

    return () => {
      // Cleanup listener
      window.ipcRenderer?.off('devtools-updated', handleStatsUpdated)
    }
  }, [])

  return (
    <div className="dashboard-container">
      {/* Titlebar */}
      <div className="titlebar dashboard-titlebar">
        <div className="titlebar-title" style={{ paddingLeft: 8 }}>
          <Gauge size={16} /> 开发工具
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
