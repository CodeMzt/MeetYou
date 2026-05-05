import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import WorkspaceWindow from './WorkspaceWindow'

describe('WorkspaceWindow', () => {
  it('renders the workspace management shell with topology and inspector regions', () => {
    const markup = renderToStaticMarkup(<WorkspaceWindow />)

    expect(markup).toContain('工作区')
    expect(markup).toContain('Endpoint Topology')
    expect(markup).toContain('搜索工作区或 Endpoint')
    expect(markup).toContain('Core')
    expect(markup).toContain('选择一个节点')
  })
})
