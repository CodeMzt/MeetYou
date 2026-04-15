import { MemorySnapshot } from '../hooks/useMemory';
import { sortMemoryRecordsByTimeline } from './memoryTimeline';

export default function OverviewView({ snapshot }: { snapshot: MemorySnapshot | null }) {
  if (!snapshot) return <div>正在加载概览...</div>;

  const { working_summaries, stats, records } = snapshot;

  const recentEvents = sortMemoryRecordsByTimeline(records.filter(r => r.type === 'episode')).slice(0, 5);

  return (
    <div className="overview-view" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-lg)' }}>
      <div className="card">
        <h3 style={{ marginBottom: 12 }}>工作上下文</h3>
        <p style={{ fontSize: 13, marginBottom: 8 }}>
          <strong>全局：</strong> {working_summaries.global_summary || '无全局摘要'}
        </p>
        <p style={{ fontSize: 13 }}>
          <strong>会话：</strong> {working_summaries.session_summary || '无会话摘要'}
        </p>
      </div>

      <div style={{ display: 'flex', gap: 'var(--spacing-md)' }}>
        <div className="card" style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: 24, fontWeight: 600, color: 'var(--text-accent)' }}>{stats.by_type.profile || 0}</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>用户画像</div>
        </div>
        <div className="card" style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: 24, fontWeight: 600, color: 'var(--text-accent)' }}>{stats.by_type.fact || 0}</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>长期事实</div>
        </div>
        <div className="card" style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: 24, fontWeight: 600, color: 'var(--text-accent)' }}>{stats.by_type.episode || 0}</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>事件记录</div>
        </div>
      </div>

      <div className="card" style={{ flex: 1 }}>
        <h3 style={{ marginBottom: 12 }}>最近事件</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-sm)' }}>
          {recentEvents.length === 0 && <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>暂无事件</span>}
          {recentEvents.map(ev => (
            <div key={ev.id} style={{ fontSize: 13, padding: '8px 12px', background: 'var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginBottom: 4 }}>
                {new Date(ev.created_at).toLocaleString()}
              </div>
              {ev.content}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
