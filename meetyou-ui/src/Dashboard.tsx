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
  const { snapshot, graph, refresh, error, clearFeedback, clearing, clearMemory } = useMemory()

  useEffect(() => {
    if (['overview', 'records', 'timeline', 'graph'].includes(activeTab)) {
      refresh()
    }
  }, [activeTab, refresh])

  const feedbackSummary = useMemo(() => {
    if (!clearFeedback) {
      return ''
    }
    const summaryParts = [
      `${clearFeedback.clearedRecordCount} records`,
      `${clearFeedback.clearedEdgeCount} edges`,
      `${clearFeedback.clearedSessionSummaryCount} session summaries`,
    ]
    if (clearFeedback.clearedGlobalSummary) {
      summaryParts.push('global summary')
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
                <h2 className="memory-actions-title">Memory Control</h2>
                <span className="memory-actions-badge">
                  <AlertTriangle size={12} />
                  Destructive
                </span>
              </div>
              <p className="memory-actions-description">
                Clear the working summaries and memory graph in one step. Thread messages remain intact, but future turns
                will no longer use the cleared memory state.
              </p>
              {clearFeedback ? (
                <div className="settings-banner success">
                  <div className="settings-banner-copy">
                    <strong>Memory cleared</strong>
                    <span>{feedbackSummary}</span>
                  </div>
                </div>
              ) : null}
              {error ? (
                <div className="settings-banner error">
                  <div className="settings-banner-copy">
                    <strong>Action failed</strong>
                    <span>{error}</span>
                  </div>
                </div>
              ) : null}
            </div>
            <div className="memory-actions-buttons">
              <button className="settings-secondary-btn" onClick={() => refresh()} disabled={clearing}>
                <RefreshCw size={16} />
                Refresh
              </button>
              <button className="memory-clear-btn" onClick={() => setConfirmClearOpen(true)} disabled={clearing}>
                <Trash2 size={16} />
                {clearing ? 'Clearing...' : 'Clear Memory'}
              </button>
            </div>
          </div>

          {activeTab === 'overview' && <OverviewView snapshot={snapshot} />}
          {activeTab === 'records' && <RecordsView snapshot={snapshot} />}
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
        title="Clear memory state"
        message="This removes stored memory records, graph edges, session summaries, and in-memory conversation state. It does not delete thread messages."
        confirmText={clearing ? 'Clearing...' : 'Clear memory'}
        cancelText="Cancel"
        isDestructive
        confirmationLabel="Type to confirm"
        confirmationHint="Enter the confirmation phrase exactly before this action becomes available."
        confirmationText={MEMORY_CLEAR_CONFIRMATION}
        onConfirm={handleConfirmClear}
        onCancel={() => setConfirmClearOpen(false)}
      />
    </SubWindow>
  )
}
