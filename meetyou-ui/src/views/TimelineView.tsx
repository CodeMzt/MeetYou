import { MemorySnapshot } from '../hooks/useMemory';

export default function TimelineView({ snapshot }: { snapshot: MemorySnapshot | null }) {
  if (!snapshot) return <div>正在加载时间线...</div>;

  const events = [...snapshot.records].sort((a, b) => {
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });

  return (
    <div className="card" style={{ height: '100%', overflowY: 'auto', padding: 24 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 24, position: 'relative' }}>
        <div style={{ position: 'absolute', left: 7, top: 0, bottom: 0, width: 2, background: 'var(--glass-border)' }} />
        
        {events.map((ev) => (
          <div key={ev.id} style={{ display: 'flex', gap: 16, position: 'relative', zIndex: 1 }}>
            <div style={{ 
              width: 16, height: 16, borderRadius: '50%', 
              background: ev.type === 'episode' ? '#8e8e93' : ev.type === 'task' ? '#34c759' : '#0a84ff',
              border: '4px solid var(--bg-color)',
              flexShrink: 0
            }} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: -2 }}>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                {new Date(ev.created_at).toLocaleString()} • <span style={{ textTransform: 'uppercase', fontSize: 10 }}>{ev.type}</span>
              </div>
              <div style={{ fontSize: 14, lineHeight: 1.5, color: ev.status === 'invalidated' ? 'var(--text-secondary)' : 'var(--text-primary)', textDecoration: ev.status === 'invalidated' ? 'line-through' : 'none' }}>
                {ev.content}
              </div>
              {ev.tags && ev.tags.length > 0 && (
                <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                  {ev.tags.map(t => (
                    <span key={t} style={{ fontSize: 10, background: 'rgba(128,128,128,0.1)', padding: '2px 6px', borderRadius: 4 }}>#{t}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
