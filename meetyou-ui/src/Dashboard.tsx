import React, { Suspense, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Clock, Database, FileText, LayoutDashboard, Network, RefreshCw, Trash2 } from 'lucide-react'
import './dashboard.css'
import { useMemory } from './hooks/useMemory'
import OverviewView from './views/OverviewView'
import RecordsView from './views/RecordsView'
import TimelineView from './views/TimelineView'
import SubWindow from './components/layout/SubWindow'
import ConfirmModal from './components/common/ConfirmModal'

const GraphView = React.lazy(() => import('./views/GraphView'))
const MEMORY_CLEAR_CONFIRMATION = '清除记忆'

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState('overview')
  const [confirmClearOpen, setConfirmClearOpen] = useState(false)
  const {
    snapshot,
    graph,
    refresh,
    error,
    clearFeedback,
    clearing,
    mutatingRecordIds,
    clearMemory,
    updateRecordStatus,
    deleteRecord,
  } = useMemory()

  useEffect(() => {
    if (['overview', 'records', 'timeline', 'graph'].includes(activeTab)) {
      refresh(activeTab === 'records')
    }
  }, [activeTab, refresh])

  const feedbackSummary = useMemo(() => {
    if (!clearFeedback) {
      return ''
    }
    const summaryParts = [
      `${clearFeedback.clearedRecordCount} 条记忆`,
      `${clearFeedback.clearedEdgeCount} 条关系`,
      `${clearFeedback.clearedSessionSummaryCount} 条会话摘要`,
    ]
    if (clearFeedback.clearedGlobalSummary) {
      summaryParts.push('全局摘要')
    }
    return summaryParts.join(', ')
  }, [clearFeedback])

  const handleConfirmClear = async () => {
    try {
      await clearMemory()
      setConfirmClearOpen(false)
    } catch {
      // Error state is already handled inside the hook.
    }
  }

  return (
    <SubWindow title="记忆图谱" icon={<Database size={16} />}>
      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <div
            className={`nav-item ${activeTab === 'overview' ? 'active' : ''}`}
            onClick={() => setActiveTab('overview')}
          >
            <LayoutDashboard size={18} /> 概览
          </div>
          <div
            className={`nav-item ${activeTab === 'records' ? 'active' : ''}`}
            onClick={() => setActiveTab('records')}
          >
            <FileText size={18} /> 记录列表
          </div>
          <div
            className={`nav-item ${activeTab === 'timeline' ? 'active' : ''}`}
            onClick={() => setActiveTab('timeline')}
          >
            <Clock size={18} /> 时间线
          </div>
          <div
            className={`nav-item ${activeTab === 'graph' ? 'active' : ''}`}
            onClick={() => setActiveTab('graph')}
          >
            <Network size={18} /> 图谱视图
          </div>
        </div>

        <div className="dashboard-content">
          <div className="card memory-actions-card">
            <div className="memory-actions-copy">
              <div className="memory-actions-title-row">
                <h2 className="memory-actions-title">记忆管理</h2>
                <span className="memory-actions-badge">
                  <AlertTriangle size={12} />
                  高风险
                </span>
              </div>
              <p className="memory-actions-description">
                可以清空全部记忆，也可以在记录列表中单独失效或删除某条记忆。线程消息不会被删除。
              </p>
              {clearFeedback ? (
                <div className="settings-banner success">
                  <div className="settings-banner-copy">
                    <strong>记忆已清空</strong>
                    <span>{feedbackSummary}</span>
                  </div>
                </div>
              ) : null}
              {error ? (
                <div className="settings-banner error">
                  <div className="settings-banner-copy">
                    <strong>操作失败</strong>
                    <span>{error}</span>
                  </div>
                </div>
              ) : null}
            </div>
            <div className="memory-actions-buttons">
              <button className="settings-secondary-btn" onClick={() => refresh()} disabled={clearing}>
                <RefreshCw size={16} />
                刷新
              </button>
              <button className="memory-clear-btn" onClick={() => setConfirmClearOpen(true)} disabled={clearing}>
                <Trash2 size={16} />
                {clearing ? '清空中...' : '清空全部记忆'}
              </button>
            </div>
          </div>

          {activeTab === 'overview' && <OverviewView snapshot={snapshot} />}
          {activeTab === 'records' && (
            <RecordsView
              snapshot={snapshot}
              mutatingRecordIds={mutatingRecordIds}
              onUpdateStatus={updateRecordStatus}
              onDeleteRecord={deleteRecord}
            />
          )}
          {activeTab === 'timeline' && <TimelineView snapshot={snapshot} />}
          {activeTab === 'graph' && (
            <Suspense fallback={<div className="card graph-loading">Loading graph view...</div>}>
              <GraphView graph={graph} />
            </Suspense>
          )}
        </div>
      </div>

      <ConfirmModal
        isOpen={confirmClearOpen}
        title="清空全部记忆"
        message="这会删除已存储的记忆记录、关系图、会话摘要和当前内存中的对话状态，但不会删除线程消息。"
        confirmText={clearing ? '清空中...' : '清空记忆'}
        cancelText="取消"
        isDestructive
        confirmationLabel="输入确认词"
        confirmationHint="必须完整输入确认词后才会执行。"
        confirmationText={MEMORY_CLEAR_CONFIRMATION}
        onConfirm={handleConfirmClear}
        onCancel={() => setConfirmClearOpen(false)}
      />
    </SubWindow>
  )
}
