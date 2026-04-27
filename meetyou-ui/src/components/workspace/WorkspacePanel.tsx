import { Activity, Bot, LayoutTemplate, Pin, ShieldCheck, Sparkles, Wrench } from 'lucide-react'
import type {
  ApprovalDisplayModel,
  ClientThreadProcedureContext,
  ClientWorkspace,
  ConnectionState,
  HumanInputRequestPayload,
  OperationView,
} from '../../types'
import {
  formatAssistantModeLabel,
  formatCapabilityPolicyLabel,
  formatExecutionTargetLabel,
  formatInferenceReasonLabel,
  formatMemoryRankingPolicyLabel,
  formatProcedureSourceLabel,
  formatRiskProfileLabel,
  formatResourceStatusLabel,
  formatRoutingPolicyLabel,
  formatSourceProfileLabel,
  getConnectionText,
} from '../../utils/statusFormatting'
import styles from './WorkspacePanel.module.css'

interface WorkspacePanelProps {
  workspace: ClientWorkspace | null
  procedureContext: ClientThreadProcedureContext | null
  connectionState: ConnectionState
  desktopToolsAvailable: boolean
  operations: OperationView[]
  approvalDisplay: ApprovalDisplayModel | null
  pendingHumanInput: HumanInputRequestPayload | null
  onDecideOperationApproval?: (approvalId: string, decision: 'approve' | 'reject') => void
  approvalSubmittingIds?: string[]
}

function countRunningOperations(operations: OperationView[]): number {
  return operations.filter((item) => item.tone === 'running' || item.tone === 'pending').length
}

function formatOperationTone(tone: string): string {
  if (tone === 'running') return 'Running'
  if (tone === 'pending') return 'Pending'
  if (tone === 'success') return 'Succeeded'
  if (tone === 'failed') return 'Failed'
  return 'Unknown'
}

export default function WorkspacePanel({
  workspace,
  procedureContext,
  connectionState,
  desktopToolsAvailable,
  operations,
  approvalDisplay,
  pendingHumanInput,
  onDecideOperationApproval,
  approvalSubmittingIds = [],
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
  const effectiveProcedure = procedureContext?.effective_procedure ?? null
  const procedureSource = procedureContext?.source ?? 'none'
  const latestInferenceVisible = procedureSource === 'inferred' && procedureContext?.latest_inferred_reason
  const recentOperations = operations.slice(0, 3)

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <div>
          <div className={styles.kicker}>Current Workspace</div>
          <h2 className={styles.title}>{workspace.title || workspace.workspace_id}</h2>
          {workspace.description && <p className={styles.description}>{workspace.description}</p>}
        </div>
      </div>

      <div className={styles.statusGrid}>
        <div className={styles.statusCard}>
          <span className={styles.statusLabel}>Core</span>
          <span className={styles.statusValue}>{getConnectionText(connectionState)}</span>
        </div>
        <div className={styles.statusCard}>
          <span className={styles.statusLabel}>鏈湴宸ュ叿</span>
          <span className={styles.statusValue}>{desktopToolsAvailable ? 'Online' : 'Offline'}</span>
        </div>
        <div className={styles.statusCard}>
          <span className={styles.statusLabel}>Workspace</span>
          <span className={styles.statusValue}>{formatResourceStatusLabel(workspace.status)}</span>
        </div>
      </div>

      <div className={styles.chipRow}>
        <span className={styles.infoChip}><Sparkles size={12} /> {formatAssistantModeLabel(workspace.base_mode)}</span>
        <span className={styles.infoChip}><Bot size={12} /> {formatExecutionTargetLabel(workspace.default_execution_target)}</span>
        <span className={styles.infoChip}><ShieldCheck size={12} /> {formatCapabilityPolicyLabel(workspace.tool_policy)}</span>
        <span className={styles.infoChip}><LayoutTemplate size={12} /> {formatRoutingPolicyLabel(workspace.tool_target_routing_policy)}</span>
      </div>

      <div className={styles.activityRow}>
        <div className={styles.activityCard}>
          <span className={styles.activityLabel}>Running Operations</span>
          <span className={styles.activityValue}>{runningOperations}</span>
        </div>
        <div className={styles.activityCard}>
          <span className={styles.activityLabel}>Pending Approvals</span>
          <span className={styles.activityValue}>{pendingApprovals}</span>
        </div>
        <div className={styles.activityCard}>
          <span className={styles.activityLabel}>Pending Input</span>
          <span className={styles.activityValue}>{pendingInputs}</span>
        </div>
      </div>

      <div className={styles.metaList}>
        <div className={styles.metaItem}>
          <Wrench size={12} />
          <span>Allowed tools: {workspace.allowed_tool_ids.length || 'All'}</span>
        </div>
        <div className={styles.metaItem}>
          <Activity size={12} />
          <span>Preferred endpoints: {workspace.preferred_target_endpoint_ids.length || 0}</span>
        </div>
        <div className={styles.metaItem}>
          <Sparkles size={12} />
          <span>
            Source preferences: {workspace.preferred_source_profiles.length > 0
              ? workspace.preferred_source_profiles.map((item) => formatSourceProfileLabel(item)).join(' / ')
              : 'Unset'}
          </span>
        </div>
        <div className={styles.metaItem}>
          <LayoutTemplate size={12} />
          <span>Memory ranking: {formatMemoryRankingPolicyLabel(workspace.memory_ranking_policy)}</span>
        </div>
      </div>

      {recentOperations.length > 0 ? (
        <div className={styles.operationsCard}>
          <div className={styles.operationsHeader}>
            <span className={styles.kicker}>Recent Operations</span>
            <span className={styles.operationsHint}>Latest 3 operations</span>
          </div>
          <div className={styles.operationsList}>
            {recentOperations.map((item) => (
              <div key={item.operation_id} className={styles.operationItem}>
                <div className={styles.operationMain}>
                  <strong>{item.title || item.operation_id}</strong>
                  <span>{formatOperationTone(item.tone)}</span>
                </div>
                {item.approval_required && item.approval_status === 'pending' && item.approval_id ? (
                  <div className={styles.operationActions}>
                    <button
                      type="button"
                      className={`${styles.approvalBtn} ${styles.approveBtn}`}
                      disabled={approvalSubmittingIds.includes(item.approval_id)}
                      onClick={() => onDecideOperationApproval?.(item.approval_id || '', 'approve')}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className={`${styles.approvalBtn} ${styles.rejectBtn}`}
                      disabled={approvalSubmittingIds.includes(item.approval_id)}
                      onClick={() => onDecideOperationApproval?.(item.approval_id || '', 'reject')}
                    >
                      Reject
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className={styles.procedureCard}>
        <div className={styles.procedureHeader}>
          <div className={styles.procedureTitleRow}>
            <Pin size={13} />
            <span className={styles.procedureKicker}>Current Procedure</span>
          </div>
          <span className={styles.procedureSource} data-source={procedureSource}>
            {formatProcedureSourceLabel(procedureSource)}
          </span>
        </div>

        {effectiveProcedure ? (
          <>
            <div className={styles.procedureNameRow}>
              <strong>{effectiveProcedure.title || effectiveProcedure.procedure_id}</strong>
              <span className={styles.procedureId}>{effectiveProcedure.procedure_id}</span>
            </div>
            {effectiveProcedure.description ? (
              <p className={styles.procedureDescription}>{effectiveProcedure.description}</p>
            ) : null}
            {effectiveProcedure.prompt_overlay ? (
              <p className={styles.procedureOverlay}>{effectiveProcedure.prompt_overlay}</p>
            ) : null}
            <div className={styles.procedureMetaRow}>
              <span className={styles.infoChip}><Sparkles size={12} /> {formatRiskProfileLabel(effectiveProcedure.risk_profile)}</span>
              <span className={styles.infoChip}><Bot size={12} /> {formatExecutionTargetLabel(effectiveProcedure.default_execution_target)}</span>
              <span className={styles.infoChip}><LayoutTemplate size={12} /> {formatRoutingPolicyLabel(effectiveProcedure.tool_target_routing_policy)}</span>
            </div>
            {effectiveProcedure.recommended_tools.length > 0 ? (
              <div className={styles.procedureTags}>
                {effectiveProcedure.recommended_tools.map((item) => (
                  <span key={item} className={styles.procedureTag}>{item}</span>
                ))}
              </div>
            ) : null}
            {latestInferenceVisible ? (
              <div className={styles.procedureHint}>
                Latest inference: {formatInferenceReasonLabel(procedureContext?.latest_inferred_reason || '')}
              </div>
            ) : null}
          </>
        ) : (
          <p className={styles.procedureEmpty}>
            This thread does not have a pinned or inferred procedure yet. Context will refresh during later turns.
          </p>
        )}
      </div>
    </section>
  )
}
