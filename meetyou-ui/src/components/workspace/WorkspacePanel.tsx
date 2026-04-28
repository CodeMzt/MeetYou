import { Activity, Bot, LayoutTemplate, ShieldCheck, Sparkles, Wrench } from 'lucide-react'
import type {
  ApprovalDisplayModel,
  ClientWorkspace,
  ConnectionState,
  HumanInputRequestPayload,
  OperationView,
} from '../../types'
import {
  formatAssistantModeLabel,
  formatCapabilityPolicyLabel,
  formatExecutionTargetLabel,
  formatMemoryRankingPolicyLabel,
  formatResourceStatusLabel,
  formatRoutingPolicyLabel,
  formatSourceProfileLabel,
  getConnectionText,
} from '../../utils/statusFormatting'
import styles from './WorkspacePanel.module.css'

interface WorkspacePanelProps {
  workspace: ClientWorkspace | null
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
  if (tone === 'running') return '运行中'
  if (tone === 'pending') return '等待中'
  if (tone === 'success') return '已完成'
  if (tone === 'failed') return '失败'
  return '未知'
}

export default function WorkspacePanel({
  workspace,
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
  const recentOperations = operations.slice(0, 3)

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <div>
          <div className={styles.kicker}>当前工作区</div>
          <h2 className={styles.title}>{workspace.title || workspace.workspace_id}</h2>
          {workspace.description && <p className={styles.description}>{workspace.description}</p>}
        </div>
      </div>

      <div className={styles.statusGrid}>
        <div className={styles.statusCard}>
          <span className={styles.statusLabel}>核心服务</span>
          <span className={styles.statusValue}>{getConnectionText(connectionState)}</span>
        </div>
        <div className={styles.statusCard}>
          <span className={styles.statusLabel}>本地工具</span>
          <span className={styles.statusValue}>{desktopToolsAvailable ? '在线' : '离线'}</span>
        </div>
        <div className={styles.statusCard}>
          <span className={styles.statusLabel}>工作区</span>
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
          <span className={styles.activityLabel}>运行中操作</span>
          <span className={styles.activityValue}>{runningOperations}</span>
        </div>
        <div className={styles.activityCard}>
          <span className={styles.activityLabel}>待确认</span>
          <span className={styles.activityValue}>{pendingApprovals}</span>
        </div>
        <div className={styles.activityCard}>
          <span className={styles.activityLabel}>待补充输入</span>
          <span className={styles.activityValue}>{pendingInputs}</span>
        </div>
      </div>

      <div className={styles.metaList}>
        <div className={styles.metaItem}>
          <Wrench size={12} />
          <span>允许工具：{workspace.allowed_tool_ids.length || '全部'}</span>
        </div>
        <div className={styles.metaItem}>
          <Activity size={12} />
          <span>偏好端点：{workspace.preferred_target_endpoint_ids.length || 0}</span>
        </div>
        <div className={styles.metaItem}>
          <Sparkles size={12} />
          <span>
            来源偏好：{workspace.preferred_source_profiles.length > 0
              ? workspace.preferred_source_profiles.map((item) => formatSourceProfileLabel(item)).join(' / ')
              : '未设置'}
          </span>
        </div>
        <div className={styles.metaItem}>
          <LayoutTemplate size={12} />
          <span>记忆排序：{formatMemoryRankingPolicyLabel(workspace.memory_ranking_policy)}</span>
        </div>
      </div>

      {recentOperations.length > 0 ? (
        <div className={styles.operationsCard}>
          <div className={styles.operationsHeader}>
            <span className={styles.kicker}>最近操作</span>
            <span className={styles.operationsHint}>最近 3 条</span>
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
                      允许
                    </button>
                    <button
                      type="button"
                      className={`${styles.approvalBtn} ${styles.rejectBtn}`}
                      disabled={approvalSubmittingIds.includes(item.approval_id)}
                      onClick={() => onDecideOperationApproval?.(item.approval_id || '', 'reject')}
                    >
                      拒绝
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

    </section>
  )
}
