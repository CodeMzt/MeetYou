import { useEffect, useState } from 'react'
import { Gauge } from 'lucide-react'
import './dashboard.css'
import UsagePanel from './components/status/UsagePanel'
import type { RuntimeUsageSnapshot } from './types'
import SubWindow from './components/layout/SubWindow'

type StatsPayload = {
  usageSnapshot: RuntimeUsageSnapshot | null
}

export default function ContextWindow() {
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
    <SubWindow title="上下文与用量" icon={<Gauge size={16} />} contentStyle={{ padding: '20px', display: 'flex', flexDirection: 'column' }}>
      <UsagePanel usageSnapshot={usageSnapshot} runtimeDebugSnapshot={null} />
    </SubWindow>
  )
}
