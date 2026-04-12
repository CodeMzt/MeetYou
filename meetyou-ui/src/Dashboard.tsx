import React, { useEffect } from 'react'
import { Clock, Network, FileText, LayoutDashboard, Database } from 'lucide-react'
import './dashboard.css'
import { useMemory } from './hooks/useMemory'
import OverviewView from './views/OverviewView'
import RecordsView from './views/RecordsView'
import TimelineView from './views/TimelineView'
import GraphView from './views/GraphView'
import SubWindow from './components/layout/SubWindow'

export default function Dashboard() {
  const [activeTab, setActiveTab] = React.useState('overview')
  const { snapshot, graph, refresh } = useMemory()

  useEffect(() => {
    // Refresh memory data when tab changes to memory related views
    if (['overview', 'records', 'timeline', 'graph'].includes(activeTab)) {
      refresh()
    }
  }, [activeTab, refresh])

  return (
    <SubWindow title="记忆图谱" icon={<Database size={16} />}>
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
    </SubWindow>
  )
}

