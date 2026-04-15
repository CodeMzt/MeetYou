import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { AttachmentObjectView } from '../../types'
import AttachmentManagerPanel from './AttachmentManagerPanel'

const attachments: AttachmentObjectView[] = [
  {
    attachmentId: 'att_1',
    fileName: 'design-notes.md',
    kind: 'file',
    status: 'ready',
    sizeBytes: 2048,
    createdAt: '2026-04-14T09:30:00Z',
    updatedAt: '2026-04-14T10:15:00Z',
  },
]

describe('AttachmentManagerPanel', () => {
  it('renders attachment list with timestamps and actions', () => {
    const markup = renderToStaticMarkup(
      <AttachmentManagerPanel
        attachments={attachments}
        loading={false}
        error={null}
        workspaceTitle="个人工作区"
        deletingAttachmentId={null}
      />,
    )

    expect(markup).toContain('附件管理')
    expect(markup).toContain('design-notes.md')
    expect(markup).toContain('创建:')
    expect(markup).toContain('更新:')
    expect(markup).toContain('下载')
    expect(markup).toContain('删除')
    expect(markup).toContain('共 1 个')
  })
})
