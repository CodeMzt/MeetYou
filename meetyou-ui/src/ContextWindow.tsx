import { useEffect, useState } from 'react'
import { Gauge } from 'lucide-react'
import './dashboard.css'
import UsagePanel from './components/status/UsagePanel'
import type { RuntimeUsageSnapshot } from './types'
import SubWindow from './components/layout/SubWindow'
import { WINDOW_SYNC_CHANNEL } from './windowBridge'

type StatsPayload = {
  usageSnapshot: RuntimeUsageSnapshot | null
}

export default function ContextWindow() {
  const [usageSnapshot, setUsageSnapshot] = useState<RuntimeUsageSnapshot | null>(null)

  useEffect(() => {
    const handleStatsUpdated = (_event: unknown, data: StatsPayload | null) => {
      setUsageSnapshot(data?.usageSnapshot ?? null)
    }

    window.ipcRenderer?.on(WINDOW_SYNC_CHANNEL.context.update, handleStatsUpdated)
    window.ipcRenderer?.send(WINDOW_SYNC_CHANNEL.context.request)

    return () => {
      window.ipcRenderer?.off(WINDOW_SYNC_CHANNEL.context.update, handleStatsUpdated)
    }
  }, [])

  return (
    <SubWindow title="上下文与用量" icon={<Gauge size={16} />} contentStyle={{ padding: '20px', display: 'flex', flexDirection: 'column' }}>
      <UsagePanel usageSnapshot={usageSnapshot} runtimeDebugSnapshot={null} />
    </SubWindow>
  )
}
