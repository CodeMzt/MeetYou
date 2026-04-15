import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import StatusStrip from './StatusStrip'

describe('StatusStrip', () => {
  it('renders the ready-state summary for an idle connected session', () => {
    const markup = renderToStaticMarkup(
      <StatusStrip
        connectionState="connected"
        runtimeSnapshot={null}
        healthSnapshot={null}
        turnActivities={[]}
      />,
    )

    expect(markup).toContain('已就绪')
    expect(markup).toContain('随时可以开始对话')
  })
})
