import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent, ReactNode } from 'react'
import {
  Archive,
  ArchiveRestore,
  Bot,
  CheckCircle2,
  ChevronRight,
  Circle,
  Cpu,
  GitBranch,
  HardDrive,
  LayoutTemplate,
  Link2,
  Plus,
  RefreshCw,
  Save,
  Search,
  Server,
  ShieldCheck,
  Smartphone,
  Unlink,
  Wifi,
  WifiOff,
} from 'lucide-react'
import type {
  ApprovalDisplayModel,
  ConnectionState,
  HumanInputRequestPayload,
  OperationView,
  RuntimeWorkspace,
  WorkspaceTopology,
  WorkspaceTopologyAddress,
  WorkspaceTopologyEndpoint,
  WorkspaceTopologyWorkspace,
} from './types'
import './dashboard.css'
import styles from './WorkspaceWindow.module.css'
import SubWindow from './components/layout/SubWindow'
import { DEFAULT_BASE_URL, WINDOW_SYNC_CHANNEL } from './windowBridge'
import {
  addAddressWorkspace,
  addEndpointWorkspace,
  archiveOperatorWorkspace,
  createOperatorWorkspace,
  decideRuntimeApproval,
  listWorkspaceTopology,
  removeAddressWorkspace,
  removeEndpointWorkspace,
  restoreOperatorWorkspace,
  setAddressPrimaryWorkspace,
  setEndpointPrimaryWorkspace,
  updateOperatorWorkspaceGovernance,
} from './runtimeApi'
import { getConnectionText } from './utils/statusFormatting'

type WorkspaceWindowPayload = {
  baseUrl: string
  threadId: string
  workspace: RuntimeWorkspace | null
  connectionState: ConnectionState
  desktopToolsAvailable: boolean
  operations: OperationView[]
  approvalDisplay: ApprovalDisplayModel | null
  pendingHumanInput: HumanInputRequestPayload | null
}

type Selection =
  | { kind: 'workspace'; id: string }
  | { kind: 'endpoint'; id: string }
  | { kind: 'address'; id: string }

type TopologyLayout = {
  width: number
  height: number
  core: { x: number; y: number; width: number; height: number }
  lanes: Map<string, { x: number; y: number; width: number; height: number }>
  endpointMemberships: Array<{
    key: string
    workspace_id: string
    endpoint_id: string
    primary: boolean
    hidden_address_count: number
    x: number
    y: number
    width: number
    height: number
  }>
  addresses: Array<{
    key: string
    workspace_id: string
    address_id: string
    endpoint_id: string
    x: number
    y: number
    width: number
    height: number
  }>
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

const EMPTY_TOPOLOGY: WorkspaceTopology = {
  workspaces: [],
  endpoints: [],
  addresses: [],
}

const BOARD_WIDTH = 840
const CORE_X = 24
const CORE_Y = 28
const CORE_WIDTH = 88
const CORE_HEIGHT = 52
const CORE_RAIL_X = CORE_X + CORE_WIDTH / 2
const LANE_X = 96
const LANE_WIDTH = 720
const LANE_TOP = 108
const LANE_GAP = 18
const LANE_BUS_Y_OFFSET = 34
const LANE_CONTENT_TOP = 72
const LANE_BOTTOM_PADDING = 18
const ENDPOINT_STACK_X_OFFSET = 34
const ENDPOINT_WIDTH = 360
const ENDPOINT_HEIGHT = 68
const ADDRESS_HEIGHT = 26
const ADDRESS_GAP = 6
const ENDPOINT_COLUMN_GAP = 16
const ENDPOINT_ROW_GAP = 24
const ENDPOINTS_PER_ROW = 1
const ADDRESS_VISIBLE_LIMIT = 1
const EMPTY_LANE_HEIGHT = 96

function normalizeSearch(value: string): string {
  return value.trim().toLowerCase()
}

function includesSearch(parts: Array<string | undefined>, query: string): boolean {
  if (!query) {
    return true
  }
  return parts.some((part) => String(part || '').toLowerCase().includes(query))
}

function workspaceTitle(workspace: WorkspaceTopologyWorkspace | undefined, workspaceId: string): string {
  return workspace?.title || workspaceId
}

function statusTone(status: string): 'active' | 'archived' | 'neutral' {
  if (status === 'active') return 'active'
  if (status === 'archived') return 'archived'
  return 'neutral'
}

function providerIcon(providerType: string) {
  const provider = providerType.toLowerCase()
  if (provider === 'core') return <Cpu size={16} />
  if (provider.includes('desktop')) return <HardDrive size={16} />
  if (provider.includes('edge')) return <Server size={16} />
  if (provider.includes('wechat') || provider.includes('feishu')) return <Smartphone size={16} />
  return <Bot size={16} />
}

function endpointWorkspaceIds(endpoint: WorkspaceTopologyEndpoint): string[] {
  return Array.from(new Set([endpoint.primary_workspace_id, ...endpoint.workspace_ids].filter(Boolean)))
}

function addressWorkspaceIds(address: WorkspaceTopologyAddress): string[] {
  return Array.from(new Set([address.primary_workspace_id, ...address.workspace_ids].filter(Boolean)))
}

function endpointMembershipKey(workspaceId: string, endpointId: string): string {
  return `${workspaceId}::${endpointId}`
}

function addressMembershipKey(workspaceId: string, addressId: string): string {
  return `${workspaceId}::${addressId}`
}

function computeTopologyLayout(topology: WorkspaceTopology): TopologyLayout {
  const workspaces = topology.workspaces.length > 0
    ? topology.workspaces
    : [{ workspace_id: 'unassigned', title: 'Unassigned', status: 'active', base_mode: 'general', description: '', endpoint_count: 0, online_endpoint_count: 0 }]
  const endpointById = new Map(topology.endpoints.map((endpoint) => [endpoint.endpoint_id, endpoint]))
  const addressesByEndpoint = new Map<string, WorkspaceTopologyAddress[]>()
  topology.addresses.forEach((address) => {
    const bucket = addressesByEndpoint.get(address.endpoint_id) || []
    bucket.push(address)
    addressesByEndpoint.set(address.endpoint_id, bucket)
  })
  const endpointIdsByWorkspace = new Map<string, Set<string>>()
  const addEndpointToWorkspace = (workspaceId: string, endpointId: string) => {
    if (!workspaceId || !endpointId) {
      return
    }
    const bucket = endpointIdsByWorkspace.get(workspaceId) || new Set<string>()
    bucket.add(endpointId)
    endpointIdsByWorkspace.set(workspaceId, bucket)
  }
  topology.endpoints.forEach((endpoint) => {
    endpointWorkspaceIds(endpoint).forEach((workspaceId) => addEndpointToWorkspace(workspaceId, endpoint.endpoint_id))
  })
  topology.addresses.forEach((address) => {
    addressWorkspaceIds(address).forEach((workspaceId) => addEndpointToWorkspace(workspaceId, address.endpoint_id))
  })
  const endpointMembershipsForWorkspace = (workspaceId: string) => {
    return Array.from(endpointIdsByWorkspace.get(workspaceId) || [])
      .map((endpointId) => endpointById.get(endpointId))
      .filter((endpoint): endpoint is WorkspaceTopologyEndpoint => Boolean(endpoint))
      .sort((a, b) => {
        const primaryDelta = Number(b.primary_workspace_id === workspaceId) - Number(a.primary_workspace_id === workspaceId)
        if (primaryDelta !== 0) return primaryDelta
        const connectedDelta = Number(b.connected) - Number(a.connected)
        if (connectedDelta !== 0) return connectedDelta
        return (a.display_name || a.endpoint_id).localeCompare(b.display_name || b.endpoint_id)
      })
  }
  const addressesForEndpointWorkspace = (endpointId: string, workspaceId: string) => {
    return (addressesByEndpoint.get(endpointId) || [])
      .filter((address) => addressWorkspaceIds(address).includes(workspaceId))
      .sort((a, b) => (a.display_name || a.address_id).localeCompare(b.display_name || b.address_id))
  }

  const lanes = new Map<string, { x: number; y: number; width: number; height: number }>()
  const rowHeightsByWorkspace = new Map<string, number[]>()
  let cursorY = LANE_TOP
  workspaces.forEach((workspace) => {
    const endpoints = endpointMembershipsForWorkspace(workspace.workspace_id)
    const rowCount = Math.max(1, Math.ceil(endpoints.length / ENDPOINTS_PER_ROW))
    const rowHeights = Array.from({ length: rowCount }, (_, rowIndex) => {
      const rowEndpoints = endpoints.slice(rowIndex * ENDPOINTS_PER_ROW, rowIndex * ENDPOINTS_PER_ROW + ENDPOINTS_PER_ROW)
      const maxAddressStackHeight = Math.max(
        0,
        ...rowEndpoints.map((endpoint) => {
          const addressCount = addressesForEndpointWorkspace(endpoint.endpoint_id, workspace.workspace_id).length
          const visibleCount = Math.min(addressCount, ADDRESS_VISIBLE_LIMIT)
          if (visibleCount === 0) {
            return 0
          }
          return ADDRESS_GAP + visibleCount * (ADDRESS_HEIGHT + ADDRESS_GAP)
        }),
      )
      return ENDPOINT_HEIGHT + maxAddressStackHeight
    })
    const rowsHeight = rowHeights.reduce((sum, rowHeight) => sum + rowHeight, 0)
    const height = Math.max(
      EMPTY_LANE_HEIGHT,
      LANE_CONTENT_TOP + rowsHeight + Math.max(0, rowCount - 1) * ENDPOINT_ROW_GAP + LANE_BOTTOM_PADDING,
    )
    rowHeightsByWorkspace.set(workspace.workspace_id, rowHeights)
    lanes.set(workspace.workspace_id, { x: LANE_X, y: cursorY, width: LANE_WIDTH, height })
    cursorY += height + LANE_GAP
  })

  const endpointMembershipPositions: TopologyLayout['endpointMemberships'] = []
  workspaces.forEach((workspace) => {
    const workspaceId = workspace.workspace_id
    const endpoints = endpointMembershipsForWorkspace(workspaceId)
    const lane = lanes.get(workspaceId) || lanes.get(workspaces[0]?.workspace_id || 'unassigned')
    if (!lane) return
    endpoints
      .forEach((endpoint, index) => {
        const col = index % ENDPOINTS_PER_ROW
        const row = Math.floor(index / ENDPOINTS_PER_ROW)
        const rowHeights = rowHeightsByWorkspace.get(workspaceId) || []
        const yOffset = rowHeights.slice(0, row).reduce((sum, rowHeight) => sum + rowHeight + ENDPOINT_ROW_GAP, 0)
        const addressCount = addressesForEndpointWorkspace(endpoint.endpoint_id, workspaceId).length
        endpointMembershipPositions.push({
          key: endpointMembershipKey(workspaceId, endpoint.endpoint_id),
          workspace_id: workspaceId,
          endpoint_id: endpoint.endpoint_id,
          primary: endpoint.primary_workspace_id === workspaceId,
          hidden_address_count: Math.max(0, addressCount - ADDRESS_VISIBLE_LIMIT),
          x: lane.x + ENDPOINT_STACK_X_OFFSET + col * (ENDPOINT_WIDTH + ENDPOINT_COLUMN_GAP),
          y: lane.y + LANE_CONTENT_TOP + yOffset,
          width: ENDPOINT_WIDTH,
          height: ENDPOINT_HEIGHT,
        })
      })
  })

  const addressPositions: TopologyLayout['addresses'] = []
  endpointMembershipPositions.forEach((endpointPosition) => {
    const addresses = addressesForEndpointWorkspace(endpointPosition.endpoint_id, endpointPosition.workspace_id)
    addresses
      .slice(0, ADDRESS_VISIBLE_LIMIT)
      .forEach((address, index) => {
        addressPositions.push({
          key: addressMembershipKey(endpointPosition.workspace_id, address.address_id),
          workspace_id: endpointPosition.workspace_id,
          address_id: address.address_id,
          endpoint_id: endpointPosition.endpoint_id,
          x: endpointPosition.x,
          y: endpointPosition.y + endpointPosition.height + ADDRESS_GAP + index * (ADDRESS_HEIGHT + ADDRESS_GAP),
          width: endpointPosition.width,
          height: ADDRESS_HEIGHT,
        })
      })
  })

  const height = Math.max(540, cursorY + 36)
  return {
    width: BOARD_WIDTH,
    height,
    core: { x: CORE_X, y: CORE_Y, width: CORE_WIDTH, height: CORE_HEIGHT },
    lanes,
    endpointMemberships: endpointMembershipPositions,
    addresses: addressPositions,
  }
}

function selectionExists(selection: Selection | null, topology: WorkspaceTopology): boolean {
  if (!selection) return false
  if (selection.kind === 'workspace') {
    return topology.workspaces.some((workspace) => workspace.workspace_id === selection.id)
  }
  if (selection.kind === 'endpoint') {
    return topology.endpoints.some((endpoint) => endpoint.endpoint_id === selection.id)
  }
  return topology.addresses.some((address) => address.address_id === selection.id)
}

function summarizeOperationState(operations: OperationView[], approvalDisplay: ApprovalDisplayModel | null, input: HumanInputRequestPayload | null) {
  const running = operations.filter((item) => item.tone === 'running' || item.tone === 'pending').length
  const approvals = operations.filter((item) => item.approval_required && item.approval_status === 'pending').length + (approvalDisplay ? 1 : 0)
  return {
    running,
    approvals,
    inputs: input ? 1 : 0,
  }
}

export default function WorkspaceWindow() {
  const [payload, setPayload] = useState<WorkspaceWindowPayload>(EMPTY_PAYLOAD)
  const [topology, setTopology] = useState<WorkspaceTopology>(EMPTY_TOPOLOGY)
  const [includeArchived, setIncludeArchived] = useState(false)
  const [search, setSearch] = useState('')
  const [selection, setSelection] = useState<Selection | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [statusMessage, setStatusMessage] = useState('')
  const [mutating, setMutating] = useState(false)
  const [newWorkspaceId, setNewWorkspaceId] = useState('')
  const [newWorkspaceTitle, setNewWorkspaceTitle] = useState('')
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

  const baseUrl = payload.baseUrl || DEFAULT_BASE_URL

  const refreshTopology = useCallback(
    async (silent = false) => {
      if (!silent) {
        setLoading(true)
      }
      try {
        const nextTopology = await listWorkspaceTopology(baseUrl, includeArchived)
        setTopology(nextTopology)
        setError('')
        return nextTopology
      } catch (loadError) {
        const message = loadError instanceof Error ? loadError.message : '加载工作区拓扑失败'
        setError(message)
        return null
      } finally {
        if (!silent) {
          setLoading(false)
        }
      }
    },
    [baseUrl, includeArchived],
  )

  useEffect(() => {
    let cancelled = false
    const load = async (silent = false) => {
      if (!silent) {
        setLoading(true)
      }
      try {
        const nextTopology = await listWorkspaceTopology(baseUrl, includeArchived)
        if (!cancelled) {
          setTopology(nextTopology)
          setError('')
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : '加载工作区拓扑失败')
        }
      } finally {
        if (!cancelled && !silent) {
          setLoading(false)
        }
      }
    }

    void load(false)
    const interval = window.setInterval(() => {
      void load(true)
    }, 5000)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [baseUrl, includeArchived])

  useEffect(() => {
    setSelection((current) => {
      if (selectionExists(current, topology)) {
        return current
      }
      const activeWorkspaceId = payload.workspace?.workspace_id
      if (activeWorkspaceId && topology.workspaces.some((workspace) => workspace.workspace_id === activeWorkspaceId)) {
        return { kind: 'workspace', id: activeWorkspaceId }
      }
      const firstWorkspace = topology.workspaces[0]
      if (firstWorkspace) {
        return { kind: 'workspace', id: firstWorkspace.workspace_id }
      }
      const firstEndpoint = topology.endpoints[0]
      if (firstEndpoint) {
        return { kind: 'endpoint', id: firstEndpoint.endpoint_id }
      }
      return null
    })
  }, [payload.workspace?.workspace_id, topology])

  const workspaceMap = useMemo(() => {
    return new Map(topology.workspaces.map((workspace) => [workspace.workspace_id, workspace]))
  }, [topology.workspaces])
  const endpointMap = useMemo(() => {
    return new Map(topology.endpoints.map((endpoint) => [endpoint.endpoint_id, endpoint]))
  }, [topology.endpoints])
  const addressMap = useMemo(() => {
    return new Map(topology.addresses.map((address) => [address.address_id, address]))
  }, [topology.addresses])
  const addressesByEndpoint = useMemo(() => {
    const result = new Map<string, WorkspaceTopologyAddress[]>()
    topology.addresses.forEach((address) => {
      const bucket = result.get(address.endpoint_id) || []
      bucket.push(address)
      result.set(address.endpoint_id, bucket)
    })
    return result
  }, [topology.addresses])
  const activeWorkspaces = useMemo(
    () => topology.workspaces.filter((workspace) => workspace.status !== 'archived'),
    [topology.workspaces],
  )
  const filteredWorkspaces = useMemo(() => {
    const query = normalizeSearch(search)
    return topology.workspaces.filter((workspace) =>
      includesSearch([workspace.workspace_id, workspace.title, workspace.description], query),
    )
  }, [search, topology.workspaces])
  const visibleEndpoints = useMemo(() => {
    const query = normalizeSearch(search)
    return topology.endpoints.filter((endpoint) =>
      includesSearch([
        endpoint.endpoint_id,
        endpoint.display_name,
        endpoint.provider_type,
        endpoint.primary_workspace_id,
        endpoint.workspace_ids.join(' '),
      ], query),
    )
  }, [search, topology.endpoints])
  const canvasWorkspaces = useMemo(() => {
    const query = normalizeSearch(search)
    if (!query) {
      return topology.workspaces
    }
    const requiredWorkspaceIds = new Set<string>(filteredWorkspaces.map((workspace) => workspace.workspace_id))
    visibleEndpoints.forEach((endpoint) => {
      endpoint.workspace_ids.forEach((workspaceId) => requiredWorkspaceIds.add(workspaceId))
      if (endpoint.primary_workspace_id) {
        requiredWorkspaceIds.add(endpoint.primary_workspace_id)
      }
    })
    return topology.workspaces.filter((workspace) => requiredWorkspaceIds.has(workspace.workspace_id))
  }, [filteredWorkspaces, search, topology.workspaces, visibleEndpoints])
  const operationSummary = useMemo(
    () => summarizeOperationState(payload.operations, payload.approvalDisplay, payload.pendingHumanInput),
    [payload.approvalDisplay, payload.operations, payload.pendingHumanInput],
  )

  const selectedWorkspace = selection?.kind === 'workspace' ? workspaceMap.get(selection.id) : undefined
  const selectedEndpoint = selection?.kind === 'endpoint' ? endpointMap.get(selection.id) : undefined
  const selectedAddress = selection?.kind === 'address' ? addressMap.get(selection.id) : undefined

  const runMutation = async (action: () => Promise<unknown>, message: string) => {
    try {
      setMutating(true)
      setError('')
      await action()
      setStatusMessage(message)
      await refreshTopology(true)
    } catch (mutationError) {
      setError(mutationError instanceof Error ? mutationError.message : message)
    } finally {
      setMutating(false)
    }
  }

  const handleDecideOperationApproval = async (approvalId: string, decision: 'approve' | 'reject') => {
    if (!approvalId || approvalSubmittingIds.includes(approvalId)) {
      return
    }
    setApprovalSubmittingIds((current) => [...current, approvalId])
    try {
      await decideRuntimeApproval(baseUrl, approvalId, { decision })
      setStatusMessage(decision === 'approve' ? '操作已批准' : '操作已拒绝')
    } catch (approvalError) {
      setError(approvalError instanceof Error ? approvalError.message : '提交审批结果失败')
    } finally {
      setApprovalSubmittingIds((current) => current.filter((item) => item !== approvalId))
    }
  }

  const handleCreateWorkspace = async () => {
    const workspaceId = newWorkspaceId.trim()
    if (!workspaceId) {
      setError('请输入工作区 ID')
      return
    }
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]*$/.test(workspaceId)) {
      setError('工作区 ID 只能包含字母、数字、下划线、横线和点号')
      return
    }
    await runMutation(
      async () => {
        await createOperatorWorkspace(baseUrl, {
          workspace_id: workspaceId,
          title: newWorkspaceTitle.trim() || workspaceId,
        })
        setNewWorkspaceId('')
        setNewWorkspaceTitle('')
        setSelection({ kind: 'workspace', id: workspaceId })
      },
      '工作区已创建',
    )
  }

  const selectWorkspaceTarget = activeWorkspaces.length > 0 ? activeWorkspaces[0]?.workspace_id || '' : ''

  return (
    <SubWindow title="工作区" icon={<LayoutTemplate size={16} />} className={styles.windowOverride}>
      <div className={`dashboard-content ${styles.mainContent}`}>
        <div className={styles.shell}>
          <aside className={styles.sidebar}>
            <div className={styles.sidebarHeader}>
              <div>
                <h2>工作区</h2>
                <p>Core 管理的运行边界</p>
              </div>
              <button
                className={styles.iconButton}
                type="button"
                onClick={() => void refreshTopology(false)}
                disabled={loading}
                title="刷新拓扑"
              >
                <RefreshCw size={15} />
              </button>
            </div>

            <label className={styles.searchBox}>
              <Search size={14} />
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索工作区或 Endpoint" />
            </label>

            <div className={styles.createBox}>
              <input
                value={newWorkspaceId}
                onChange={(event) => setNewWorkspaceId(event.target.value)}
                placeholder="workspace-id"
                aria-label="新工作区 ID"
              />
              <input
                value={newWorkspaceTitle}
                onChange={(event) => setNewWorkspaceTitle(event.target.value)}
                placeholder="显示名称"
                aria-label="新工作区标题"
              />
              <button type="button" onClick={() => void handleCreateWorkspace()} disabled={mutating}>
                <Plus size={14} /> 创建
              </button>
            </div>

            <button
              className={styles.archiveToggle}
              type="button"
              data-active={includeArchived}
              onClick={() => setIncludeArchived((current) => !current)}
            >
              {includeArchived ? <ArchiveRestore size={14} /> : <Archive size={14} />}
              {includeArchived ? '显示归档中' : '隐藏归档'}
            </button>

            <div className={styles.workspaceList} role="list">
              {filteredWorkspaces.map((workspace) => {
                const selected = selection?.kind === 'workspace' && selection.id === workspace.workspace_id
                return (
                  <button
                    key={workspace.workspace_id}
                    type="button"
                    className={styles.workspaceRow}
                    data-selected={selected}
                    data-status={statusTone(workspace.status)}
                    onClick={() => setSelection({ kind: 'workspace', id: workspace.workspace_id })}
                  >
                    <span className={styles.workspaceRowMain}>
                      <span>{workspace.title || workspace.workspace_id}</span>
                      <small>{workspace.workspace_id}</small>
                    </span>
                    <span className={styles.workspaceCounts}>
                      {workspace.online_endpoint_count}/{workspace.endpoint_count}
                    </span>
                  </button>
                )
              })}
            </div>

            <div className={styles.runtimeStrip}>
              <span><Wifi size={13} /> {getConnectionText(payload.connectionState)}</span>
              <span><HardDrive size={13} /> {payload.desktopToolsAvailable ? '本地可用' : '本地离线'}</span>
              <span><Circle size={13} /> 运行 {operationSummary.running}</span>
              <span><ShieldCheck size={13} /> 待确认 {operationSummary.approvals + operationSummary.inputs}</span>
            </div>
            <ApprovalQueue
              operations={payload.operations}
              submittingIds={approvalSubmittingIds}
              onDecide={(approvalId, decision) => void handleDecideOperationApproval(approvalId, decision)}
            />
          </aside>

          <main className={styles.topologyPane}>
            <div className={styles.topologyHeader}>
              <div>
                <h1>Workspace Terminal</h1>
                <p>Core 总线连接工作区轨道，Provider 卡槽展示主归属，地址收纳在对应 Endpoint 下。</p>
              </div>
              <div className={styles.topologyStats}>
                <span>{topology.workspaces.length} 工作区</span>
                <span>{topology.endpoints.filter((endpoint) => endpoint.connected).length}/{topology.endpoints.length} 在线</span>
                <span>{topology.addresses.length} 地址</span>
              </div>
            </div>

            {error ? <div className={styles.errorBanner}>{error}</div> : null}
            {statusMessage ? <div className={styles.statusBanner}>{statusMessage}</div> : null}

            <TopologyCanvas
              topology={{
                workspaces: canvasWorkspaces,
                endpoints: visibleEndpoints,
                addresses: topology.addresses.filter((address) => visibleEndpoints.some((endpoint) => endpoint.endpoint_id === address.endpoint_id)),
              }}
              workspaceMap={workspaceMap}
              selection={selection}
              onSelect={setSelection}
            />
          </main>

          <aside className={styles.inspector}>
            <Inspector
              selection={selection}
              workspace={selectedWorkspace}
              endpoint={selectedEndpoint}
              address={selectedAddress}
              workspaceMap={workspaceMap}
              endpointMap={endpointMap}
              activeWorkspaces={activeWorkspaces}
              addressesByEndpoint={addressesByEndpoint}
              mutating={mutating}
              fallbackWorkspaceId={selectWorkspaceTarget}
              onSelect={setSelection}
              onSaveWorkspace={(workspaceId, updates) =>
                runMutation(
                  async () => {
                    await updateOperatorWorkspaceGovernance(baseUrl, workspaceId, updates)
                  },
                  '工作区信息已保存',
                )
              }
              onArchiveWorkspace={(workspaceId) =>
                runMutation(
                  async () => {
                    await archiveOperatorWorkspace(baseUrl, workspaceId)
                  },
                  '工作区已归档',
                )
              }
              onRestoreWorkspace={(workspaceId) =>
                runMutation(
                  async () => {
                    await restoreOperatorWorkspace(baseUrl, workspaceId)
                  },
                  '工作区已恢复',
                )
              }
              onAddEndpointWorkspace={(endpointId, workspaceId, makePrimary) =>
                runMutation(
                  async () => {
                    await addEndpointWorkspace(baseUrl, endpointId, { workspace_id: workspaceId, make_primary: makePrimary })
                  },
                  makePrimary ? 'Endpoint 主工作区已更新' : 'Endpoint 归属已添加',
                )
              }
              onRemoveEndpointWorkspace={(endpointId, workspaceId) =>
                runMutation(
                  async () => {
                    await removeEndpointWorkspace(baseUrl, endpointId, workspaceId)
                  },
                  'Endpoint 归属已移除',
                )
              }
              onSetEndpointPrimary={(endpointId, workspaceId) =>
                runMutation(
                  async () => {
                    await setEndpointPrimaryWorkspace(baseUrl, endpointId, workspaceId)
                  },
                  'Endpoint 主工作区已更新',
                )
              }
              onAddAddressWorkspace={(addressId, workspaceId, makePrimary) =>
                runMutation(
                  async () => {
                    await addAddressWorkspace(baseUrl, addressId, { workspace_id: workspaceId, make_primary: makePrimary })
                  },
                  makePrimary ? '地址主工作区已更新' : '地址归属已添加',
                )
              }
              onRemoveAddressWorkspace={(addressId, workspaceId) =>
                runMutation(
                  async () => {
                    await removeAddressWorkspace(baseUrl, addressId, workspaceId)
                  },
                  '地址归属已移除',
                )
              }
              onSetAddressPrimary={(addressId, workspaceId) =>
                runMutation(
                  async () => {
                    await setAddressPrimaryWorkspace(baseUrl, addressId, workspaceId)
                  },
                  '地址主工作区已更新',
                )
              }
            />
          </aside>
        </div>
      </div>
    </SubWindow>
  )
}

interface TopologyCanvasProps {
  topology: WorkspaceTopology
  workspaceMap: Map<string, WorkspaceTopologyWorkspace>
  selection: Selection | null
  onSelect: (selection: Selection) => void
}

function ApprovalQueue({
  operations,
  submittingIds,
  onDecide,
}: {
  operations: OperationView[]
  submittingIds: string[]
  onDecide: (approvalId: string, decision: 'approve' | 'reject') => void
}) {
  const pendingOperations = operations.filter(
    (operation) => operation.approval_required && operation.approval_status === 'pending' && operation.approval_id,
  )
  if (pendingOperations.length === 0) {
    return null
  }
  return (
    <div className={styles.approvalQueue}>
      <div className={styles.approvalQueueHeader}>待确认操作</div>
      {pendingOperations.slice(0, 3).map((operation) => {
        const approvalId = operation.approval_id || ''
        const disabled = submittingIds.includes(approvalId)
        return (
          <div key={operation.operation_id} className={styles.approvalItem}>
            <div>
              <strong>{operation.title || operation.operation_id}</strong>
              <span>{operation.tool_key || operation.operation_type || 'operation'}</span>
            </div>
            <div className={styles.approvalActions}>
              <button type="button" disabled={disabled} onClick={() => onDecide(approvalId, 'approve')}>
                允许
              </button>
              <button type="button" disabled={disabled} onClick={() => onDecide(approvalId, 'reject')}>
                拒绝
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function TopologyCanvas({ topology, workspaceMap, selection, onSelect }: TopologyCanvasProps) {
  const layout = useMemo(() => computeTopologyLayout(topology), [topology])
  const endpointMap = useMemo(() => new Map(topology.endpoints.map((endpoint) => [endpoint.endpoint_id, endpoint])), [topology.endpoints])
  const addressMap = useMemo(() => new Map(topology.addresses.map((address) => [address.address_id, address])), [topology.addresses])
  const endpointMembershipMap = useMemo(
    () => new Map(layout.endpointMemberships.map((membership) => [membership.key, membership])),
    [layout.endpointMemberships],
  )
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const panStateRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    scrollLeft: number
    scrollTop: number
  } | null>(null)
  const [panning, setPanning] = useState(false)

  const handlePanStart = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return
    }
    const target = event.target instanceof Element ? event.target : null
    if (target?.closest('button,input,textarea,select,a')) {
      return
    }
    panStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: event.currentTarget.scrollLeft,
      scrollTop: event.currentTarget.scrollTop,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    setPanning(true)
  }, [])

  const handlePanMove = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const panState = panStateRef.current
    const surface = scrollRef.current
    if (!panState || panState.pointerId !== event.pointerId || !surface) {
      return
    }
    surface.scrollLeft = panState.scrollLeft - (event.clientX - panState.startX)
    surface.scrollTop = panState.scrollTop - (event.clientY - panState.startY)
  }, [])

  const finishPan = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const panState = panStateRef.current
    if (!panState || panState.pointerId !== event.pointerId) {
      return
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    panStateRef.current = null
    setPanning(false)
  }, [])

  return (
    <div
      ref={scrollRef}
      className={styles.boardScroll}
      data-panning={panning}
      data-testid="workspace-topology-pan-surface"
      onPointerDown={handlePanStart}
      onPointerMove={handlePanMove}
      onPointerUp={finishPan}
      onPointerCancel={finishPan}
    >
      <div className={styles.board} style={{ width: layout.width, height: layout.height }}>
        <svg className={styles.edgeLayer} viewBox={`0 0 ${layout.width} ${layout.height}`} aria-hidden="true">
          <path
            className={styles.coreRail}
            d={`M ${CORE_RAIL_X} ${layout.core.y + layout.core.height} L ${CORE_RAIL_X} ${layout.height - 32}`}
          />
          {topology.workspaces.map((workspace) => {
            const lane = layout.lanes.get(workspace.workspace_id)
            if (!lane) return null
            return (
              <path
                key={`bus-${workspace.workspace_id}`}
                className={styles.workspaceBus}
                d={`M ${CORE_RAIL_X} ${lane.y + LANE_BUS_Y_OFFSET} L ${lane.x + lane.width - 24} ${lane.y + LANE_BUS_Y_OFFSET}`}
              />
            )
          })}
          {layout.endpointMemberships.map((endpointPosition) => {
            const endpoint = endpointMap.get(endpointPosition.endpoint_id)
            const lane = layout.lanes.get(endpointPosition.workspace_id)
            if (!endpoint || !lane) return null
            return (
              <path
                key={`membership-edge-${endpointPosition.key}`}
                className={endpointPosition.primary ? (endpoint.connected ? styles.primaryEdge : styles.offlineEdge) : styles.secondaryEdge}
                d={`M ${endpointPosition.x + endpointPosition.width / 2} ${lane.y + LANE_BUS_Y_OFFSET} L ${endpointPosition.x + endpointPosition.width / 2} ${endpointPosition.y}`}
              />
            )
          })}
          {layout.addresses.map((addressPosition) => {
            const endpointPosition = endpointMembershipMap.get(endpointMembershipKey(addressPosition.workspace_id, addressPosition.endpoint_id))
            if (!endpointPosition || !addressPosition) return null
            return (
              <path
                key={`address-edge-${addressPosition.key}`}
                className={styles.addressEdge}
                d={`M ${endpointPosition.x + endpointPosition.width / 2} ${endpointPosition.y + endpointPosition.height} L ${addressPosition.x + addressPosition.width / 2} ${addressPosition.y}`}
              />
            )
          })}
        </svg>

        <div className={styles.coreNode} style={{ left: layout.core.x, top: layout.core.y, width: layout.core.width, height: layout.core.height }}>
          <Cpu size={19} />
          <span>Core</span>
        </div>

        {topology.workspaces.map((workspace) => {
          const lane = layout.lanes.get(workspace.workspace_id)
          if (!lane) return null
          const selected = selection?.kind === 'workspace' && selection.id === workspace.workspace_id
          return (
            <div
              key={workspace.workspace_id}
              className={styles.workspaceLane}
              data-selected={selected}
              data-status={statusTone(workspace.status)}
              style={{ left: lane.x, top: lane.y, width: lane.width, height: lane.height }}
            >
              <button
                type="button"
                className={styles.workspaceLaneButton}
                onClick={() => onSelect({ kind: 'workspace', id: workspace.workspace_id })}
              >
                <span className={styles.laneTitle}>{workspace.title || workspace.workspace_id}</span>
                <span className={styles.laneMeta}>{workspace.workspace_id} · {workspace.online_endpoint_count}/{workspace.endpoint_count} online</span>
              </button>
            </div>
          )
        })}

        {layout.endpointMemberships.map((position) => {
          const endpoint = endpointMap.get(position.endpoint_id)
          if (!endpoint) return null
          const selected = selection?.kind === 'endpoint' && selection.id === endpoint.endpoint_id
          const primaryWorkspace = workspaceTitle(workspaceMap.get(endpoint.primary_workspace_id), endpoint.primary_workspace_id || 'unassigned')
          const secondaryWorkspaceTitles = endpointWorkspaceIds(endpoint)
            .filter((workspaceId) => workspaceId !== endpoint.primary_workspace_id)
            .map((workspaceId) => workspaceTitle(workspaceMap.get(workspaceId), workspaceId))
          const visibleWorkspaceTags = position.primary ? secondaryWorkspaceTitles : [`主 ${primaryWorkspace}`]
          const membershipText = position.primary
            ? `${endpoint.provider_type} · 主归属${secondaryWorkspaceTitles.length > 0 ? ' · 兼属' : ''}`
            : `${endpoint.provider_type} · 兼属`
          return (
            <button
              key={position.key}
              type="button"
              className={styles.endpointNode}
              data-selected={selected}
              data-online={endpoint.connected}
              data-core={endpoint.core_owned}
              data-primary={position.primary}
              style={{ left: position.x, top: position.y, width: position.width, height: position.height }}
              onClick={() => onSelect({ kind: 'endpoint', id: endpoint.endpoint_id })}
              title={`${endpoint.endpoint_id} · ${workspaceTitle(workspaceMap.get(position.workspace_id), position.workspace_id)}`}
            >
              <span className={styles.nodeIcon}>{providerIcon(endpoint.provider_type)}</span>
              <span className={styles.nodeText}>
                <strong>{endpoint.display_name || endpoint.endpoint_id}</strong>
                <small title={membershipText}>{membershipText}</small>
                {visibleWorkspaceTags.length > 0 ? (
                  <span className={styles.workspaceBadgeLine}>
                    {visibleWorkspaceTags.slice(0, 2).map((title) => (
                      <span key={title}>{title}</span>
                    ))}
                    {visibleWorkspaceTags.length > 2 ? <span>+{visibleWorkspaceTags.length - 2}</span> : null}
                  </span>
                ) : null}
              </span>
              {endpoint.connected ? <Wifi size={13} className={styles.onlineIcon} /> : <WifiOff size={13} className={styles.offlineIcon} />}
            </button>
          )
        })}

        {layout.addresses.map((position) => {
          const address = addressMap.get(position.address_id)
          if (!address) return null
          const selected = selection?.kind === 'address' && selection.id === address.address_id
          return (
            <button
              key={position.key}
              type="button"
              className={styles.addressNode}
              data-selected={selected}
              style={{ left: position.x, top: position.y, width: position.width, height: position.height }}
              onClick={() => onSelect({ kind: 'address', id: address.address_id })}
              title={address.address_id}
            >
              <Link2 size={12} />
              <span>{address.display_name || address.address_type || 'Address'}</span>
            </button>
          )
        })}

        {layout.endpointMemberships.map((endpointPosition) => {
          if (endpointPosition.hidden_address_count <= 0) return null
          return (
            <span
              key={`hidden-${endpointPosition.key}`}
              className={styles.hiddenAddressBadge}
              style={{
                left: endpointPosition.x + endpointPosition.width - 42,
                top: endpointPosition.y + endpointPosition.height + ADDRESS_GAP + Math.max(0, ADDRESS_VISIBLE_LIMIT - 1) * (ADDRESS_HEIGHT + ADDRESS_GAP) + 1,
              }}
            >
              +{endpointPosition.hidden_address_count}
            </span>
          )
        })}
      </div>
    </div>
  )
}

interface InspectorProps {
  selection: Selection | null
  workspace?: WorkspaceTopologyWorkspace
  endpoint?: WorkspaceTopologyEndpoint
  address?: WorkspaceTopologyAddress
  workspaceMap: Map<string, WorkspaceTopologyWorkspace>
  endpointMap: Map<string, WorkspaceTopologyEndpoint>
  activeWorkspaces: WorkspaceTopologyWorkspace[]
  addressesByEndpoint: Map<string, WorkspaceTopologyAddress[]>
  mutating: boolean
  fallbackWorkspaceId: string
  onSelect: (selection: Selection) => void
  onSaveWorkspace: (workspaceId: string, updates: { title?: string; description?: string }) => void
  onArchiveWorkspace: (workspaceId: string) => void
  onRestoreWorkspace: (workspaceId: string) => void
  onAddEndpointWorkspace: (endpointId: string, workspaceId: string, makePrimary: boolean) => void
  onRemoveEndpointWorkspace: (endpointId: string, workspaceId: string) => void
  onSetEndpointPrimary: (endpointId: string, workspaceId: string) => void
  onAddAddressWorkspace: (addressId: string, workspaceId: string, makePrimary: boolean) => void
  onRemoveAddressWorkspace: (addressId: string, workspaceId: string) => void
  onSetAddressPrimary: (addressId: string, workspaceId: string) => void
}

function Inspector(props: InspectorProps) {
  if (!props.selection) {
    return (
      <section className={styles.emptyInspector}>
        <GitBranch size={18} />
        <h2>选择一个节点</h2>
        <p>查看工作区、Endpoint 或地址的归属与能力。</p>
      </section>
    )
  }
  if (props.workspace) {
    return <WorkspaceInspector {...props} workspace={props.workspace} />
  }
  if (props.endpoint) {
    return <EndpointInspector {...props} endpoint={props.endpoint} />
  }
  if (props.address) {
    return <AddressInspector {...props} address={props.address} />
  }
  return (
    <section className={styles.emptyInspector}>
      <Unlink size={18} />
      <h2>节点已不存在</h2>
      <p>拓扑刷新后，这个节点已经不在当前视图中。</p>
    </section>
  )
}

function WorkspaceInspector({
  workspace,
  endpointMap,
  addressesByEndpoint,
  mutating,
  onSelect,
  onSaveWorkspace,
  onArchiveWorkspace,
  onRestoreWorkspace,
}: InspectorProps & { workspace: WorkspaceTopologyWorkspace }) {
  const [title, setTitle] = useState(workspace.title || workspace.workspace_id)
  const [description, setDescription] = useState(workspace.description || '')

  useEffect(() => {
    setTitle(workspace.title || workspace.workspace_id)
    setDescription(workspace.description || '')
  }, [workspace])

  const memberEndpoints = Array.from(endpointMap.values()).filter((endpoint) => endpoint.workspace_ids.includes(workspace.workspace_id))
  const memberAddresses = Array.from(addressesByEndpoint.values())
    .flat()
    .filter((address) => address.workspace_ids.includes(workspace.workspace_id))
  const changed = title !== (workspace.title || workspace.workspace_id) || description !== (workspace.description || '')
  const isPersonal = workspace.workspace_id === 'personal'
  const archived = workspace.status === 'archived'

  return (
    <section className={styles.inspectorSection}>
      <div className={styles.inspectorHeader}>
        <span className={styles.inspectorIcon}><LayoutTemplate size={18} /></span>
        <div>
          <h2>{workspace.title || workspace.workspace_id}</h2>
          <p>{workspace.workspace_id}</p>
        </div>
      </div>

      <div className={styles.formStack}>
        <label>
          <span>显示名称</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label>
          <span>描述</span>
          <textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} />
        </label>
        <button
          className={styles.primaryButton}
          type="button"
          disabled={mutating || !changed}
          onClick={() => onSaveWorkspace(workspace.workspace_id, { title: title.trim() || workspace.workspace_id, description })}
        >
          <Save size={14} /> 保存
        </button>
      </div>

      <div className={styles.detailGrid}>
        <span>状态</span>
        <strong>{workspace.status}</strong>
        <span>Endpoint</span>
        <strong>{workspace.online_endpoint_count}/{workspace.endpoint_count} 在线</strong>
        <span>默认模式</span>
        <strong>{workspace.base_mode || 'general'}</strong>
      </div>

      <div className={styles.actionBlock}>
        {archived ? (
          <button className={styles.secondaryButton} type="button" disabled={mutating} onClick={() => onRestoreWorkspace(workspace.workspace_id)}>
            <ArchiveRestore size={14} /> 恢复工作区
          </button>
        ) : (
          <button
            className={styles.dangerButton}
            type="button"
            disabled={mutating || isPersonal}
            onClick={() => {
              if (window.confirm(`归档工作区 ${workspace.workspace_id}？归档会隐藏它，但不会删除历史引用。`)) {
                onArchiveWorkspace(workspace.workspace_id)
              }
            }}
          >
            <Archive size={14} /> 归档
          </button>
        )}
        {isPersonal ? <small>personal 是系统 fallback 工作区，不能归档。</small> : null}
      </div>

      <NodeList title="Endpoint" empty="这个工作区还没有 Endpoint 归属">
        {memberEndpoints.map((endpoint) => (
          <button key={endpoint.endpoint_id} type="button" className={styles.relatedRow} onClick={() => onSelect({ kind: 'endpoint', id: endpoint.endpoint_id })}>
            {providerIcon(endpoint.provider_type)}
            <span>{endpoint.display_name || endpoint.endpoint_id}</span>
            <ChevronRight size={13} />
          </button>
        ))}
      </NodeList>

      <NodeList title="地址" empty="这个工作区还没有地址归属">
        {memberAddresses.map((address) => (
          <button key={address.address_id} type="button" className={styles.relatedRow} onClick={() => onSelect({ kind: 'address', id: address.address_id })}>
            <Link2 size={13} />
            <span>{address.display_name || address.address_id}</span>
            <ChevronRight size={13} />
          </button>
        ))}
      </NodeList>
    </section>
  )
}

function EndpointInspector({
  endpoint,
  workspaceMap,
  activeWorkspaces,
  addressesByEndpoint,
  mutating,
  fallbackWorkspaceId,
  onSelect,
  onAddEndpointWorkspace,
  onRemoveEndpointWorkspace,
  onSetEndpointPrimary,
}: InspectorProps & { endpoint: WorkspaceTopologyEndpoint }) {
  const [targetWorkspace, setTargetWorkspace] = useState(endpoint.primary_workspace_id || fallbackWorkspaceId)

  useEffect(() => {
    setTargetWorkspace(endpoint.primary_workspace_id || fallbackWorkspaceId)
  }, [endpoint.endpoint_id, endpoint.primary_workspace_id, fallbackWorkspaceId])

  const endpointAddresses = addressesByEndpoint.get(endpoint.endpoint_id) || []
  const declaredMismatch = endpoint.provider_declared_workspace_ids.length > 0
    && endpoint.provider_declared_workspace_ids.join('|') !== endpoint.workspace_ids.join('|')

  return (
    <section className={styles.inspectorSection}>
      <div className={styles.inspectorHeader}>
        <span className={styles.inspectorIcon}>{providerIcon(endpoint.provider_type)}</span>
        <div>
          <h2>{endpoint.display_name || endpoint.endpoint_id}</h2>
          <p>{endpoint.endpoint_id}</p>
        </div>
      </div>

      <div className={styles.statusLine} data-online={endpoint.connected}>
        {endpoint.connected ? <Wifi size={14} /> : <WifiOff size={14} />}
        <span>{endpoint.connected ? '在线' : '离线'} · {endpoint.provider_type || 'provider'} · {endpoint.endpoint_type || 'endpoint'}</span>
      </div>

      {endpoint.core_owned ? (
        <div className={styles.noticeBox}>
          <Cpu size={14} /> Core 内置 Endpoint 只能展示，不能移动或移除归属。
        </div>
      ) : null}

      <MembershipEditor
        workspaceIds={endpoint.workspace_ids}
        primaryWorkspaceId={endpoint.primary_workspace_id}
        workspaceMap={workspaceMap}
        activeWorkspaces={activeWorkspaces}
        targetWorkspace={targetWorkspace}
        disabled={mutating || endpoint.core_owned}
        onTargetWorkspaceChange={setTargetWorkspace}
        onAdd={(workspaceId, makePrimary) => onAddEndpointWorkspace(endpoint.endpoint_id, workspaceId, makePrimary)}
        onSetPrimary={(workspaceId) => onSetEndpointPrimary(endpoint.endpoint_id, workspaceId)}
        onRemove={(workspaceId) => {
          if (window.confirm(`移除 ${endpoint.endpoint_id} 在 ${workspaceId} 的归属？`)) {
            onRemoveEndpointWorkspace(endpoint.endpoint_id, workspaceId)
          }
        }}
      />

      <div className={styles.detailGrid}>
        <span>连接数</span>
        <strong>{endpoint.connection_count}</strong>
        <span>传输</span>
        <strong>{endpoint.transport_type || 'unknown'}</strong>
        <span>能力</span>
        <strong>{endpoint.capability_count}</strong>
      </div>

      {declaredMismatch ? (
        <div className={styles.noticeBox}>
          <ShieldCheck size={14} /> Provider 声明：{endpoint.provider_declared_workspace_ids.join(', ')}。Core 管理归属优先生效。
        </div>
      ) : null}

      <NodeList title="EndpointAddress" empty="这个 Endpoint 还没有地址">
        {endpointAddresses.map((address) => (
          <button key={address.address_id} type="button" className={styles.relatedRow} onClick={() => onSelect({ kind: 'address', id: address.address_id })}>
            <Link2 size={13} />
            <span>{address.display_name || address.address_id}</span>
            <ChevronRight size={13} />
          </button>
        ))}
      </NodeList>

      <NodeList title={`Capabilities (${endpoint.executable_tools.length})`} empty="这个 Endpoint 没有上报可执行工具">
        {endpoint.executable_tools.map((tool) => (
          <span key={tool} className={styles.capabilityChip}>{tool}</span>
        ))}
      </NodeList>
    </section>
  )
}

function AddressInspector({
  address,
  endpointMap,
  workspaceMap,
  activeWorkspaces,
  mutating,
  fallbackWorkspaceId,
  onSelect,
  onAddAddressWorkspace,
  onRemoveAddressWorkspace,
  onSetAddressPrimary,
}: InspectorProps & { address: WorkspaceTopologyAddress }) {
  const [targetWorkspace, setTargetWorkspace] = useState(address.primary_workspace_id || fallbackWorkspaceId)
  const endpoint = endpointMap.get(address.endpoint_id)

  useEffect(() => {
    setTargetWorkspace(address.primary_workspace_id || fallbackWorkspaceId)
  }, [address.address_id, address.primary_workspace_id, fallbackWorkspaceId])

  return (
    <section className={styles.inspectorSection}>
      <div className={styles.inspectorHeader}>
        <span className={styles.inspectorIcon}><Link2 size={18} /></span>
        <div>
          <h2>{address.display_name || address.address_id}</h2>
          <p>{address.address_id}</p>
        </div>
      </div>

      <div className={styles.detailGrid}>
        <span>Provider</span>
        <strong>{address.provider_type || 'unknown'}</strong>
        <span>类型</span>
        <strong>{address.address_type || 'address'}</strong>
        <span>状态</span>
        <strong>{address.status || 'unknown'}</strong>
      </div>

      {endpoint ? (
        <button type="button" className={styles.parentEndpoint} onClick={() => onSelect({ kind: 'endpoint', id: endpoint.endpoint_id })}>
          {providerIcon(endpoint.provider_type)}
          <span>所属 Endpoint：{endpoint.display_name || endpoint.endpoint_id}</span>
          <ChevronRight size={13} />
        </button>
      ) : null}

      <MembershipEditor
        workspaceIds={address.workspace_ids}
        primaryWorkspaceId={address.primary_workspace_id}
        workspaceMap={workspaceMap}
        activeWorkspaces={activeWorkspaces}
        targetWorkspace={targetWorkspace}
        disabled={mutating}
        onTargetWorkspaceChange={setTargetWorkspace}
        onAdd={(workspaceId, makePrimary) => onAddAddressWorkspace(address.address_id, workspaceId, makePrimary)}
        onSetPrimary={(workspaceId) => onSetAddressPrimary(address.address_id, workspaceId)}
        onRemove={(workspaceId) => {
          if (window.confirm(`移除地址 ${address.address_id} 在 ${workspaceId} 的归属？`)) {
            onRemoveAddressWorkspace(address.address_id, workspaceId)
          }
        }}
      />

      <NodeList title="Capabilities" empty="这个地址没有独立能力摘要">
        {address.capabilities.map((capability) => (
          <span key={capability} className={styles.capabilityChip}>{capability}</span>
        ))}
      </NodeList>
    </section>
  )
}

interface MembershipEditorProps {
  workspaceIds: string[]
  primaryWorkspaceId: string
  workspaceMap: Map<string, WorkspaceTopologyWorkspace>
  activeWorkspaces: WorkspaceTopologyWorkspace[]
  targetWorkspace: string
  disabled: boolean
  onTargetWorkspaceChange: (workspaceId: string) => void
  onAdd: (workspaceId: string, makePrimary: boolean) => void
  onSetPrimary: (workspaceId: string) => void
  onRemove: (workspaceId: string) => void
}

function MembershipEditor({
  workspaceIds,
  primaryWorkspaceId,
  workspaceMap,
  activeWorkspaces,
  targetWorkspace,
  disabled,
  onTargetWorkspaceChange,
  onAdd,
  onSetPrimary,
  onRemove,
}: MembershipEditorProps) {
  return (
    <div className={styles.membershipBox}>
      <div className={styles.membershipHeader}>
        <span>工作区归属</span>
        <small>移动 = 设为主工作区并保留旧归属</small>
      </div>
      <div className={styles.membershipList}>
        {workspaceIds.map((workspaceId) => {
          const primary = workspaceId === primaryWorkspaceId
          return (
            <span key={workspaceId} className={styles.membershipChip} data-primary={primary}>
              {primary ? <CheckCircle2 size={12} /> : <Circle size={12} />}
              {workspaceTitle(workspaceMap.get(workspaceId), workspaceId)}
              {!primary && !disabled ? (
                <button type="button" onClick={() => onRemove(workspaceId)} title="移除归属">
                  <Unlink size={11} />
                </button>
              ) : null}
            </span>
          )
        })}
      </div>
      <div className={styles.membershipActions}>
        <select value={targetWorkspace} onChange={(event) => onTargetWorkspaceChange(event.target.value)} disabled={disabled}>
          {activeWorkspaces.map((workspace) => (
            <option key={workspace.workspace_id} value={workspace.workspace_id}>
              {workspace.title || workspace.workspace_id}
            </option>
          ))}
        </select>
        <button type="button" disabled={disabled || !targetWorkspace} onClick={() => onSetPrimary(targetWorkspace)}>
          设为主工作区
        </button>
        <button type="button" disabled={disabled || !targetWorkspace} onClick={() => onAdd(targetWorkspace, false)}>
          添加归属
        </button>
      </div>
    </div>
  )
}

function NodeList({ title, empty, children }: { title: string; empty: string; children: ReactNode }) {
  const items = Array.isArray(children) ? children.filter(Boolean) : children
  const hasItems = Array.isArray(items) ? items.length > 0 : Boolean(items)
  return (
    <div className={styles.nodeList}>
      <div className={styles.nodeListHeader}>{title}</div>
      <div className={styles.nodeListBody}>{hasItems ? items : <span className={styles.emptyText}>{empty}</span>}</div>
    </div>
  )
}
