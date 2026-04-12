import { useEffect, useState } from 'react'
import { LayoutTemplate, Minus, Square, X } from 'lucide-react'
import type {
  ApprovalDisplayModel,
  ClientThreadProcedureContext,
  ClientWorkspace,
  ConnectionState,
  HumanInputRequestPayload,
  OperationView,
} from './types'
import './dashboard.css'
import { getClientThreadProcedureContext } from './clientApi'
import WorkspaceGovernanceEditor from './components/workspace/WorkspaceGovernanceEditor'
import ProcedureCatalogPanel from './components/workspace/ProcedureCatalogPanel'
import WorkspacePanel from './components/workspace/WorkspacePanel'

type WorkspaceWindowPayload = {
  baseUrl: string
  threadId: string
  workspace: ClientWorkspace | null
  procedureContext: ClientThreadProcedureContext | null
  connectionState: ConnectionState
  desktopAgentConnected: boolean
  operations: OperationView[]
  approvalDisplay: ApprovalDisplayModel | null
  pendingHumanInput: HumanInputRequestPayload | null
}

const EMPTY_PAYLOAD: WorkspaceWindowPayload = {
  baseUrl: 'http://127.0.0.1:8000',
  threadId: '',
  workspace: null,
  procedureContext: null,
  connectionState: 'connecting',
  desktopAgentConnected: false,
  operations: [],
  approvalDisplay: null,
  pendingHumanInput: null,
}

export default function WorkspaceWindow() {
  const handleClose = () => window.ipcRenderer?.send('window-close')
  const handleMinimize = () => window.ipcRenderer?.send('window-minimize')
  const handleMaximize = () => window.ipcRenderer?.send('window-maximize')
  const [payload, setPayload] = useState<WorkspaceWindowPayload>(EMPTY_PAYLOAD)
  const [procedureContext, setProcedureContext] = useState<ClientThreadProcedureContext | null>(null)

  useEffect(() => {
    if (!payload.threadId) {
      setProcedureContext(payload.procedureContext)
      return
    }
    let cancelled = false
    const loadContext = async () => {
      try {
        const nextContext = await getClientThreadProcedureContext(payload.baseUrl, payload.threadId)
        if (!cancelled) {
          setProcedureContext(nextContext)
        }
      } catch {
        if (!cancelled) {
          setProcedureContext(payload.procedureContext)
        }
      }
    }
    void loadContext()
    return () => {
      cancelled = true
    }
  }, [payload.baseUrl, payload.procedureContext, payload.threadId])

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

    window.ipcRenderer?.on('workspace-panel-updated', handleWorkspaceUpdated)
    window.ipcRenderer?.send('request-workspace-panel')

    return () => {
      window.ipcRenderer?.off('workspace-panel-updated', handleWorkspaceUpdated)
    }
  }, [])

  return (
    <div className="dashboard-container">
      <div className="titlebar dashboard-titlebar">
        <div className="titlebar-title" style={{ paddingLeft: 8 }}>
          <LayoutTemplate size={16} /> 工作区与规程
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
        {payload.workspace ? (
          <WorkspacePanel
            workspace={payload.workspace}
            procedureContext={procedureContext}
            connectionState={payload.connectionState}
            desktopAgentConnected={payload.desktopAgentConnected}
            operations={payload.operations}
            approvalDisplay={payload.approvalDisplay}
            pendingHumanInput={payload.pendingHumanInput}
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

        {payload.workspace ? (
          <ProcedureCatalogPanel
            baseUrl={payload.baseUrl}
            threadId={payload.threadId}
            procedureContext={procedureContext}
            onProcedureContextChange={setProcedureContext}
          />
        ) : (
          <div style={{ padding: 20, color: 'var(--text-secondary)' }}>
            正在等待主窗口同步当前工作区与规程上下文。
          </div>
        )}
      </div>
    </div>
  )
}
