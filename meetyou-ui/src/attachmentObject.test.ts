import { describe, expect, it } from 'vitest'
import { normalizeAttachmentObject, normalizeAttachmentObjects } from './attachmentObject'

describe('attachmentObject', () => {
  it('normalizes snake_case attachment payloads into shared object views', () => {
    expect(
      normalizeAttachmentObject({
        attachment_id: 'att_1',
        kind: 'file',
        file_name: 'report.txt',
        mime_type: 'text/plain',
        size_bytes: 42,
        status: 'ready',
        download_url: 'http://127.0.0.1:8000/download',
      }),
    ).toEqual({
      attachmentId: 'att_1',
      kind: 'file',
      fileName: 'report.txt',
      mimeType: 'text/plain',
      sizeBytes: 42,
      status: 'ready',
      downloadUrl: 'http://127.0.0.1:8000/download',
    })
  })

  it('keeps camelCase attachments and filters invalid entries', () => {
    expect(
      normalizeAttachmentObjects([
        {
          attachmentId: 'att_2',
          fileName: 'image.png',
          mimeType: 'image/png',
        },
        { fileName: 'missing-id.txt' },
      ]),
    ).toEqual([
      {
        attachmentId: 'att_2',
        kind: 'file',
        fileName: 'image.png',
        mimeType: 'image/png',
        sizeBytes: undefined,
        status: undefined,
        downloadUrl: undefined,
      },
    ])
  })
})
