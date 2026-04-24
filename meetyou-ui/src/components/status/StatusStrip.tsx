import { ConnectionState, RuntimeHealthSnapshot, RuntimeStateSnapshot, TurnActivity } from '../../types'
import { buildStatusPresentation } from '../../utils/statusFormatting'
import StatusIcon from './StatusIcon'
import styles from './StatusStrip.module.css'

interface StatusStripProps {
  connectionState: ConnectionState
  runtimeSnapshot: RuntimeStateSnapshot | null
  healthSnapshot: RuntimeHealthSnapshot | null
  turnActivities: TurnActivity[]
}

export default function StatusStrip({
  connectionState,
  runtimeSnapshot,
  healthSnapshot,
  turnActivities,
}: StatusStripProps) {
  const presentation = buildStatusPresentation(connectionState, runtimeSnapshot, healthSnapshot, turnActivities)
  const metaChips = [
    runtimeSnapshot?.current_mode ? `mode:${runtimeSnapshot.current_mode}` : '',
    runtimeSnapshot?.source_profile ? `source:${runtimeSnapshot.source_profile}` : '',
    runtimeSnapshot?.action_risk ? `risk:${runtimeSnapshot.action_risk}` : '',
  ].filter(Boolean)
  const isDefaultReadyState =
    presentation.title === '已就绪' &&
    presentation.phaseLabel === '就绪' &&
    presentation.activePhase === null &&
    !healthSnapshot?.degraded

  if (isDefaultReadyState) {
    return null
  }

  return (
    <div className={styles.statusStrip}>
      <div className={styles.topRegion}>
        <div className={styles.main}>
          <div className={styles.iconWrapper}>
            <StatusIcon
              runtimeSnapshot={runtimeSnapshot}
              connectionState={connectionState}
              activePhase={presentation.activePhase}
            />
          </div>
          <div className={styles.copy}>
            <div className={styles.title}>{presentation.title}</div>
            <div className={styles.detail}>{presentation.detail || '随时可以继续对话'}</div>
          </div>
        </div>
        <div className={styles.phaseChip}>{presentation.phaseLabel}</div>
      </div>
      
      {metaChips.length > 0 && (
        <div className={styles.meta}>
          {metaChips.map((chip) => (
            <span
              key={chip}
              className={styles.metaChip}
              title={chip.startsWith('mode:') ? runtimeSnapshot?.route_reason || chip : chip}
            >
              {chip}
            </span>
          ))}
        </div>
      )}
      
      {(presentation.toolChips.length > 0 || presentation.hiddenToolCount > 0) && (
        <div className={styles.tools}>
          {presentation.toolChips.map((tool) => (
            <span key={tool.key} className={styles.toolChip} title={tool.title}>
              {tool.label}
            </span>
          ))}
          {presentation.hiddenToolCount > 0 && (
            <span className={`${styles.toolChip} ${styles.more}`} title={presentation.hiddenToolsTitle}>
              +{presentation.hiddenToolCount}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
