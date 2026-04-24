import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import StatusStrip from './StatusStrip'

describe('StatusStrip', () => {
  it('hides the default ready-state summary for an idle connected session', () => {
    const markup = renderToStaticMarkup(
      <StatusStrip
        connectionState="connected"
        runtimeSnapshot={null}
        healthSnapshot={null}
        turnActivities={[]}
      />,
    )

    expect(markup).toBe('')
  })

  it('still renders meaningful non-ready connection states', () => {
    const markup = renderToStaticMarkup(
      <StatusStrip
        connectionState="connecting"
        runtimeSnapshot={null}
        healthSnapshot={null}
        turnActivities={[]}
      />,
    )

    expect(markup).toContain('正在连接服务')
    expect(markup).toContain('正在建立桌面端与后端的连接')
  })
})
