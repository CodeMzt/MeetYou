import { useEffect, useState } from 'react'
import { LayoutTemplate } from 'lucide-react'
import type {
  ApprovalDisplayModel,
  ClientWorkspace,
  ConnectionState,
  HumanInputRequestPayload,
  OperationView,
} from './types'
import './dashboard.css'
import styles from './WorkspaceWindow.module.css'
import WorkspaceGovernanceEditor from './components/workspace/WorkspaceGovernanceEditor'
import WorkspacePanel from './components/workspace/WorkspacePanel'
import SubWindow from './components/layout/SubWindow'
import { DEFAULT_BASE_URL, WINDOW_SYNC_CHANNEL } from './windowBridge'
import { decideClientApproval } from './clientApi'

type WorkspaceWindowPayload = {
  baseUrl: string
  threadId: string
  workspace: ClientWorkspace | null
  connectionState: ConnectionState
  desktopToolsAvailable: boolean
  operations: OperationView[]
  approvalDisplay: ApprovalDisplayModel | null
  pendingHumanInput: HumanInputRequestPayload | null
}

const EMPTY_PAYLOAD: WorkspaceWindowPayload = {
  baseUrl: DEFAULT_BASE_URL,
  threadId: '',
  workspace: null,
  connectionState: 'connecting',
  desktopToolsAvailable: false,
  operations: [],
  approvalDisplay: null,
  pendingHumanInput: null,
}

export default function WorkspaceWindow() {
  const [payload, setPayload] = useState<WorkspaceWindowPayload>(EMPTY_PAYLOAD)
  const [approvalSubmittingIds, setApprovalSubmittingIds] = useState<string[]>([])

  useEffect(() => {
    const handleWorkspaceUpdated = (_event: unknown, data: WorkspaceWindowPayload | null) => {
      if (!data) {
        return
      }
      setPayload({
        ...EMPTY_PAYLOAD,
        ...data,
        operations: Array.isArray(data.operations) ? data.operations : [],
      })
    }

    window.ipcRenderer?.on(WINDOW_SYNC_CHANNEL.workspace.update, handleWorkspaceUpdated)
    window.ipcRenderer?.send(WINDOW_SYNC_CHANNEL.workspace.request)

    return () => {
      window.ipcRenderer?.off(WINDOW_SYNC_CHANNEL.workspace.update, handleWorkspaceUpdated)
    }
  }, [])

  const handleDecideOperationApproval = async (approvalId: string, decision: 'approve' | 'reject') => {
    if (!approvalId || approvalSubmittingIds.includes(approvalId)) {
      return
    }
    setApprovalSubmittingIds((current) => [...current, approvalId])
    try {
      await decideClientApproval(payload.baseUrl, approvalId, { decision })
    } catch (error) {
      console.warn('Failed to submit operation approval from workspace window:', error)
    } finally {
      setApprovalSubmittingIds((current) => current.filter((item) => item !== approvalId))
    }
  }

  return (
    <SubWindow title="工作区" icon={<LayoutTemplate size={16} />} className={styles.windowOverride}>
      <div className={`dashboard-content ${styles.mainContent}`}>
        <div className={styles.container}>
          {payload.workspace ? (
            <WorkspacePanel
              workspace={payload.workspace}
              connectionState={payload.connectionState}
              desktopToolsAvailable={payload.desktopToolsAvailable}
              operations={payload.operations}
              approvalDisplay={payload.approvalDisplay}
              pendingHumanInput={payload.pendingHumanInput}
              onDecideOperationApproval={handleDecideOperationApproval}
              approvalSubmittingIds={approvalSubmittingIds}
            />
          ) : null}

          {payload.workspace ? (
            <WorkspaceGovernanceEditor
              baseUrl={payload.baseUrl}
              workspace={payload.workspace}
              onWorkspaceSaved={(workspace) => {
                setPayload((current) => ({
                  ...current,
                  workspace,
                }))
              }}
            />
          ) : null}
          {!payload.workspace ? (
            <div style={{ padding: 20, color: 'var(--text-secondary)' }}>
              正在等待主窗口同步当前工作区上下文。
            </div>
          ) : null}
      </div>
      </div>
    </SubWindow>
  )
}
