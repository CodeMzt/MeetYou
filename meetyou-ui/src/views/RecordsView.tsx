import { useState } from 'react'
import GlassSelect from '../components/GlassSelect'
import { MemorySnapshot } from '../hooks/useMemory'

export default function RecordsView({ snapshot }: { snapshot: MemorySnapshot | null }) {
  const [filterType, setFilterType] = useState('all')
  const [filterStatus, setFilterStatus] = useState('active')

  if (!snapshot) {
    return <div>正在加载记录...</div>
  }

  const records = snapshot.records.filter((record) => {
    if (filterType !== 'all' && record.type !== filterType) {
      return false
    }
    if (filterStatus !== 'all' && record.status !== filterStatus) {
      return false
    }
    return true
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 14 }}>
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
        {records.map((record) => (
          <div key={record.id} className="card records-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <span
                style={{
                  fontSize: 11,
                  background: 'var(--accent-color)',
                  color: 'white',
                  padding: '2px 6px',
                  borderRadius: 4,
                  textTransform: 'uppercase',
                }}
              >
                {record.type}
              </span>
              <span style={{ fontSize: 11, color: record.status === 'active' ? '#34c759' : '#ff3b30' }}>
                {record.status}
              </span>
            </div>
            <div style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.45 }}>
              {record.type === 'profile' && record.fact_key ? (
                <span style={{ color: 'var(--text-secondary)' }}>[{record.fact_key}] </span>
              ) : null}
              {record.type === 'fact' && record.fact_key ? (
                <span style={{ color: 'var(--text-secondary)' }}>[{record.fact_key}] </span>
              ) : null}
              {record.content}
            </div>
            <div style={{ marginTop: 'auto', paddingTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 11, background: 'rgba(128,128,128,0.1)', padding: '2px 6px', borderRadius: 4 }}>
                Conf: {(record.confidence * 100).toFixed(0)}%
              </span>
              <span style={{ fontSize: 11, background: 'rgba(128,128,128,0.1)', padding: '2px 6px', borderRadius: 4 }}>
                Str: {(record.strength * 100).toFixed(0)}%
              </span>
              {record.fact_value ? (
                <span style={{ fontSize: 11, background: 'rgba(128,128,128,0.1)', padding: '2px 6px', borderRadius: 4 }}>
                  Value: {record.fact_value}
                </span>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
