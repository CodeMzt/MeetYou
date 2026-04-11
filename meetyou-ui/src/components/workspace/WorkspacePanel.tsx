import { Activity, Bot, LayoutTemplate, ShieldCheck, Sparkles, Wrench } from 'lucide-react'
import type {
  ApprovalDisplayModel,
  ClientWorkspace,
  ConnectionState,
  HumanInputRequestPayload,
  OperationView,
} from '../../types'
import { getConnectionText } from '../../utils/statusFormatting'
import styles from './WorkspacePanel.module.css'

interface WorkspacePanelProps {
  workspace: ClientWorkspace | null
  connectionState: ConnectionState
  desktopAgentConnected: boolean
  operations: OperationView[]
  approvalDisplay: ApprovalDisplayModel | null
  pendingHumanInput: HumanInputRequestPayload | null
  onOpenDiagnostics: () => void
}

function countRunningOperations(operations: OperationView[]): number {
  return operations.filter((item) => item.tone === 'running' || item.tone === 'pending').length
}

export default function WorkspacePanel({
  workspace,
  connectionState,
  desktopAgentConnected,
  operations,
  approvalDisplay,
  pendingHumanInput,
  onOpenDiagnostics,
}: WorkspacePanelProps) {
  if (!workspace) {
    return null
  }

  const runningOperations = countRunningOperations(operations)
  const pendingOperationApprovals = operations.filter(
    (item) => item.approval_required && item.approval_status === 'pending',
  ).length
  const pendingApprovals = pendingOperationApprovals + (approvalDisplay ? 1 : 0)
  const pendingInputs = pendingHumanInput ? 1 : 0

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <div>
          <div className={styles.kicker}>Current Workspace</div>
          <h2 className={styles.title}>{workspace.title || workspace.workspace_id}</h2>
          {workspace.description && <p className={styles.description}>{workspace.description}</p>}
        </div>

        <button className={styles.secondaryBtn} onClick={onOpenDiagnostics}>
          Diagnostics
        </button>
      </div>

      <div className={styles.statusGrid}>
        <div className={styles.statusCard}>
          <span className={styles.statusLabel}>Core</span>
          <span className={styles.statusValue}>{getConnectionText(connectionState)}</span>
        </div>
        <div className={styles.statusCard}>
          <span className={styles.statusLabel}>Local Agent</span>
          <span className={styles.statusValue}>{desktopAgentConnected ? 'online' : 'offline'}</span>
        </div>
        <div className={styles.statusCard}>
          <span className={styles.statusLabel}>Workspace</span>
          <span className={styles.statusValue}>{workspace.status}</span>
        </div>
      </div>

      <div className={styles.chipRow}>
        <span className={styles.infoChip}><Sparkles size={12} /> {workspace.base_mode}</span>
        <span className={styles.infoChip}><Bot size={12} /> {workspace.default_execution_target}</span>
        <span className={styles.infoChip}><ShieldCheck size={12} /> {workspace.capability_policy}</span>
        <span className={styles.infoChip}><LayoutTemplate size={12} /> {workspace.agent_routing_policy}</span>
      </div>

      <div className={styles.activityRow}>
        <div className={styles.activityCard}>
          <span className={styles.activityLabel}>Running Ops</span>
          <span className={styles.activityValue}>{runningOperations}</span>
        </div>
        <div className={styles.activityCard}>
          <span className={styles.activityLabel}>Pending Approvals</span>
          <span className={styles.activityValue}>{pendingApprovals}</span>
        </div>
        <div className={styles.activityCard}>
          <span className={styles.activityLabel}>Pending Inputs</span>
          <span className={styles.activityValue}>{pendingInputs}</span>
        </div>
      </div>

      <div className={styles.metaList}>
        <div className={styles.metaItem}>
          <Wrench size={12} />
          <span>Allowed capabilities: {workspace.allowed_capability_ids.length || 'all'}</span>
        </div>
        <div className={styles.metaItem}>
          <Activity size={12} />
          <span>Preferred agent ids: {workspace.preferred_agent_ids.length || 0}</span>
        </div>
      </div>
    </section>
  )
}
