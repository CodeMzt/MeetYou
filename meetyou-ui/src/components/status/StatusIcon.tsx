import { BrainCircuit, Database, Loader2, Send, ShieldAlert, Sparkles, Wrench } from 'lucide-react'
import { ConnectionState, RuntimeStateSnapshot } from '../../types'
import styles from './StatusStrip.module.css'

interface StatusIconProps {
  runtimeSnapshot: RuntimeStateSnapshot | null
  connectionState: ConnectionState
  activePhase: string | null
}

export default function StatusIcon({ runtimeSnapshot, connectionState, activePhase }: StatusIconProps) {
  if (connectionState !== 'connected') {
    return <Loader2 size={15} className={connectionState === 'connecting' ? styles.spin : ''} />
  }

  if (!runtimeSnapshot || runtimeSnapshot.status === 'idle') {
    return <Sparkles size={15} />
  }

  if (runtimeSnapshot.status === 'thinking') {
    return <BrainCircuit size={15} className={styles.pulse} />
  }

  if (runtimeSnapshot.status === 'waiting_confirm') {
    return <ShieldAlert size={15} />
  }

  if (runtimeSnapshot.status === 'waiting_human_input') {
    return <Sparkles size={15} className={styles.pulse} />
  }

  if (runtimeSnapshot.status === 'tool_calling') {
    if (activePhase === 'loading_context') {
      return <Database size={15} />
    }
    if (activePhase === 'synthesizing') {
      return <BrainCircuit size={15} className={styles.pulse} />
    }
    return <Wrench size={15} />
  }

  if (runtimeSnapshot.status === 'answering') {
    return <Send size={15} />
  }

  return <Sparkles size={15} />
}
