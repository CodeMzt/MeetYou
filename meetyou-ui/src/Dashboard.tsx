import React, { useEffect } from 'react'
import { Clock, Network, FileText, LayoutDashboard, X, Minus, Square, Database } from 'lucide-react'
import './dashboard.css'
import { useMemory } from './hooks/useMemory'
import OverviewView from './views/OverviewView'
import RecordsView from './views/RecordsView'
import TimelineView from './views/TimelineView'
import GraphView from './views/GraphView'

export default function Dashboard() {
  const [activeTab, setActiveTab] = React.useState('overview')
  const { snapshot, graph, refresh } = useMemory()

  useEffect(() => {
    // Refresh memory data when tab changes to memory related views
    if (['overview', 'records', 'timeline', 'graph'].includes(activeTab)) {
      refresh()
    }
  }, [activeTab, refresh])

  const handleClose = () => window.ipcRenderer?.send('window-close')
  const handleMinimize = () => window.ipcRenderer?.send('window-minimize')
  const handleMaximize = () => window.ipcRenderer?.send('window-maximize')

  return (
    <div className="dashboard-container">
      {/* Titlebar with Windows Controls */}
      <div className="titlebar dashboard-titlebar">
        <div className="titlebar-title" style={{ paddingLeft: 8 }}>
          <Database size={16} /> 记忆图谱
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

      <div className="dashboard-layout">
        {/* Sidebar */}
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

        {/* Main Content Area */}
        <div className="dashboard-content">
          {activeTab === 'overview' && <OverviewView snapshot={snapshot} />}
          {activeTab === 'records' && <RecordsView snapshot={snapshot} />}
          {activeTab === 'timeline' && <TimelineView snapshot={snapshot} />}
          {activeTab === 'graph' && <GraphView graph={graph} />}
        </div>
      </div>
    </div>
  )
}

