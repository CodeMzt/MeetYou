import { MemorySnapshot } from '../hooks/useMemory'

export default function TimelineView({ snapshot }: { snapshot: MemorySnapshot | null }) {
  if (!snapshot) {
    return <div>正在加载时间线...</div>
  }

  const events = [...snapshot.records].sort((left, right) => {
    return new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
  })

  return (
    <div className="card scroll-surface" style={{ height: '100%', overflowY: 'auto', padding: 'var(--spacing-lg)' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-lg)', position: 'relative' }}>
        <div
          style={{
            position: 'absolute',
            left: 7,
            top: 0,
            bottom: 0,
            width: 2,
            background: 'var(--glass-border)',
          }}
        />

        {events.map((event) => (
          <div key={event.id} style={{ display: 'flex', gap: 14, position: 'relative', zIndex: 1 }}>
            <div
              style={{
                width: 16,
                height: 16,
                borderRadius: 'var(--radius-full)',
                background:
                  event.type === 'episode' ? 'var(--text-tertiary)' : event.type === 'fact' ? 'var(--text-success)' : 'var(--text-accent)',
                border: '4px solid var(--bg-card)',
                flexShrink: 0,
              }}
            />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: -2 }}>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                {new Date(event.created_at).toLocaleString()} ·{' '}
                <span style={{ textTransform: 'uppercase', fontSize: 10 }}>{event.type}</span>
              </div>
              <div
                style={{
                  fontSize: 13,
                  lineHeight: 1.55,
                  color: event.status === 'invalidated' ? 'var(--text-secondary)' : 'var(--text-primary)',
                  textDecoration: event.status === 'invalidated' ? 'line-through' : 'none',
                }}
              >
                {event.content}
              </div>
              {event.tags && event.tags.length > 0 ? (
                <div style={{ display: 'flex', gap: 6, marginTop: 3, flexWrap: 'wrap' }}>
                  {event.tags.map((tag) => (
                    <span
                      key={tag}
                      style={{
                        fontSize: 10,
                        background: 'var(--border-subtle)',
                        padding: '2px 6px',
                        borderRadius: 'var(--radius-sm)',
                      }}
                    >
                      #{tag}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
