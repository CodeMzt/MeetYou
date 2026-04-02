import { useState } from 'react';
import { MemorySnapshot } from '../hooks/useMemory';

export default function RecordsView({ snapshot }: { snapshot: MemorySnapshot | null }) {
  const [filterType, setFilterType] = useState('all');
  const [filterStatus, setFilterStatus] = useState('active');

  if (!snapshot) return <div>正在加载记录...</div>;

  const records = snapshot.records.filter(r => {
    if (filterType !== 'all' && r.type !== filterType) return false;
    if (filterStatus !== 'all' && r.status !== filterStatus) return false;
    return true;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 16 }}>
      <div className="card" style={{ display: 'flex', gap: 16, padding: '12px 16px', alignItems: 'center' }}>
        <div style={{ fontSize: 14, fontWeight: 500 }}>筛选：</div>
        <select 
          style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid var(--glass-border)', background: 'transparent', color: 'var(--text-primary)' }}
          value={filterType} onChange={e => setFilterType(e.target.value)}
        >
          <option value="all">所有类型</option>
          <option value="profile_fact">用户画像</option>
          <option value="task">任务</option>
          <option value="episode">事件记录</option>
        </select>
        <select 
          style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid var(--glass-border)', background: 'transparent', color: 'var(--text-primary)' }}
          value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
        >
          <option value="all">所有状态</option>
          <option value="active">活跃</option>
          <option value="invalidated">已失效</option>
        </select>
        <div style={{ flex: 1 }} />
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>共 {records.length} 条记录</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16, overflowY: 'auto', paddingRight: 4 }}>
        {records.map(r => (
          <div key={r.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <span style={{ fontSize: 11, background: 'var(--accent-color)', color: 'white', padding: '2px 6px', borderRadius: 4, textTransform: 'uppercase' }}>{r.type}</span>
              <span style={{ fontSize: 11, color: r.status === 'active' ? '#34c759' : '#ff3b30' }}>{r.status}</span>
            </div>
            <div style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.4 }}>
              {r.type === 'profile_fact' && r.fact_key ? <span style={{ color: 'var(--text-secondary)' }}>[{r.fact_key}] </span> : null}
              {r.type === 'task' && r.task_key ? <span style={{ color: 'var(--text-secondary)' }}>[{r.task_key}] </span> : null}
              {r.content}
            </div>
            <div style={{ marginTop: 'auto', paddingTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 11, background: 'rgba(128,128,128,0.1)', padding: '2px 6px', borderRadius: 4 }}>
                Conf: {(r.confidence * 100).toFixed(0)}%
              </span>
              <span style={{ fontSize: 11, background: 'rgba(128,128,128,0.1)', padding: '2px 6px', borderRadius: 4 }}>
                Str: {(r.strength * 100).toFixed(0)}%
              </span>
              {r.type === 'task' && r.task_status && (
                <span style={{ fontSize: 11, background: 'rgba(128,128,128,0.1)', padding: '2px 6px', borderRadius: 4 }}>
                  Status: {r.task_status}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
