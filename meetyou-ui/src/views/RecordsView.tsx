import { useMemo, useState } from 'react'
import { Ban, RotateCcw, Trash2 } from 'lucide-react'
import ConfirmModal from '../components/common/ConfirmModal'
import GlassSelect from '../components/GlassSelect'
import { MemoryRecord, MemorySnapshot } from '../hooks/useMemory'

type MemoryRecordStatus = 'active' | 'invalidated'

type PendingAction =
  | { type: 'invalidate'; record: MemoryRecord }
  | { type: 'restore'; record: MemoryRecord }
  | { type: 'delete'; record: MemoryRecord }
  | null

interface RecordsViewProps {
  snapshot: MemorySnapshot | null
  mutatingRecordIds?: Set<string>
  onUpdateStatus?: (memoryId: string, status: MemoryRecordStatus) => Promise<unknown>
  onDeleteRecord?: (memoryId: string) => Promise<unknown>
}

function formatRecordType(type: string): string {
  if (type === 'profile') return '画像'
  if (type === 'fact') return '事实'
  if (type === 'episode') return '事件'
  return type || '记录'
}

function formatRecordStatus(status: string): string {
  if (status === 'active') return '活跃'
  if (status === 'invalidated') return '已失效'
  return status || '未知'
}

function actionConfig(action: PendingAction) {
  if (!action) {
    return {
      title: '',
      message: '',
      confirmText: '',
    }
  }
  if (action.type === 'delete') {
    return {
      title: '删除这条记忆',
      message: `这会永久删除记忆“${action.record.content}”，并移除相关图关系。`,
      confirmText: '删除',
    }
  }
  if (action.type === 'restore') {
    return {
      title: '恢复这条记忆',
      message: `恢复后，这条记忆会重新参与后续召回：${action.record.content}`,
      confirmText: '恢复',
    }
  }
  return {
    title: '使这条记忆失效',
    message: `失效后，这条记忆不会继续参与默认召回：${action.record.content}`,
    confirmText: '失效',
  }
}

export default function RecordsView({
  snapshot,
  mutatingRecordIds = new Set(),
  onUpdateStatus,
  onDeleteRecord,
}: RecordsViewProps) {
  const [filterType, setFilterType] = useState('all')
  const [filterStatus, setFilterStatus] = useState('active')
  const [pendingAction, setPendingAction] = useState<PendingAction>(null)
  const [isConfirming, setIsConfirming] = useState(false)

  const records = useMemo(() => {
    return (snapshot?.records || []).filter((record) => {
      if (filterType !== 'all' && record.type !== filterType) {
        return false
      }
      if (filterStatus !== 'all' && record.status !== filterStatus) {
        return false
      }
      return true
    })
  }, [filterStatus, filterType, snapshot])

  if (!snapshot) {
    return <div>正在加载记录...</div>
  }

  const handleConfirmAction = async () => {
    if (!pendingAction) {
      return
    }
    try {
      setIsConfirming(true)
      if (pendingAction.type === 'delete') {
        await onDeleteRecord?.(pendingAction.record.id)
      } else {
        await onUpdateStatus?.(
          pendingAction.record.id,
          pendingAction.type === 'restore' ? 'active' : 'invalidated',
        )
      }
      setPendingAction(null)
    } finally {
      setIsConfirming(false)
    }
  }

  const confirmation = actionConfig(pendingAction)

  return (
    <div className="records-view">
      <div className="card records-toolbar">
        <div className="records-toolbar-filters">
          <div className="records-toolbar-label">筛选</div>
          <GlassSelect
            wrapperClassName="records-filter-select"
            value={filterType}
            onChange={(event) => setFilterType(event.target.value)}
          >
            <option value="all">所有类型</option>
            <option value="profile">用户画像</option>
            <option value="fact">长期事实</option>
            <option value="episode">事件记录</option>
          </GlassSelect>
          <GlassSelect
            wrapperClassName="records-filter-select"
            value={filterStatus}
            onChange={(event) => setFilterStatus(event.target.value)}
          >
            <option value="all">所有状态</option>
            <option value="active">活跃</option>
            <option value="invalidated">已失效</option>
          </GlassSelect>
        </div>
        <div className="records-toolbar-count">共 {records.length} 条记录</div>
      </div>

      <div className="records-grid">
        {records.map((record) => {
          const isMutating = mutatingRecordIds.has(record.id)
          const isInvalidated = record.status === 'invalidated'
          return (
            <div key={record.id} className="card records-card">
              <div className="records-card-header">
                <span className="records-type-chip">{formatRecordType(record.type)}</span>
                <span className={`records-status-chip ${isInvalidated ? 'invalidated' : 'active'}`}>
                  {formatRecordStatus(record.status)}
                </span>
              </div>
              <div className="records-content">
                {record.type === 'profile' && record.fact_key ? (
                  <span className="records-fact-key">[{record.fact_key}] </span>
                ) : null}
                {record.type === 'fact' && record.fact_key ? (
                  <span className="records-fact-key">[{record.fact_key}] </span>
                ) : null}
                {record.content}
              </div>
              <div className="records-meta">
                <span>置信度 {(record.confidence * 100).toFixed(0)}%</span>
                <span>强度 {(record.strength * 100).toFixed(0)}%</span>
                {record.fact_value ? <span>值 {record.fact_value}</span> : null}
              </div>
              <div className="records-actions">
                {isInvalidated ? (
                  <button
                    type="button"
                    className="records-action-btn"
                    disabled={isMutating}
                    onClick={() => setPendingAction({ type: 'restore', record })}
                  >
                    <RotateCcw size={14} />
                    恢复
                  </button>
                ) : (
                  <button
                    type="button"
                    className="records-action-btn"
                    disabled={isMutating}
                    onClick={() => setPendingAction({ type: 'invalidate', record })}
                  >
                    <Ban size={14} />
                    失效
                  </button>
                )}
                <button
                  type="button"
                  className="records-action-btn danger"
                  disabled={isMutating}
                  onClick={() => setPendingAction({ type: 'delete', record })}
                >
                  <Trash2 size={14} />
                  删除
                </button>
              </div>
            </div>
          )
        })}
      </div>

      <ConfirmModal
        isOpen={pendingAction !== null}
        title={confirmation.title}
        message={confirmation.message}
        confirmText={isConfirming ? '处理中...' : confirmation.confirmText}
        cancelText="取消"
        isDestructive={pendingAction?.type !== 'restore'}
        onConfirm={handleConfirmAction}
        onCancel={() => setPendingAction(null)}
      />
    </div>
  )
}
