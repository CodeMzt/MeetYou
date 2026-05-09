import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import MarkdownRenderer from './MarkdownRenderer'

describe('MarkdownRenderer', () => {
  it('renders runtime artifact downloads as handled buttons', () => {
    const markup = renderToStaticMarkup(
      <MarkdownRenderer
        content="研究报告：[下载](/runtime/artifacts/art_report123/download)"
        onArtifactDownload={vi.fn()}
      />,
    )

    expect(markup).toContain('data-artifact-download-link="art_report123"')
    expect(markup).toContain('下载产物')
    expect(markup).toContain('下载')
    expect(markup).not.toContain('href="/runtime/artifacts/art_report123/download"')
  })

  it('keeps ordinary markdown links as browser links', () => {
    const markup = renderToStaticMarkup(
      <MarkdownRenderer content="[来源](https://example.com/source)" onArtifactDownload={vi.fn()} />,
    )

    expect(markup).toContain('href="https://example.com/source"')
    expect(markup).toContain('target="_blank"')
    expect(markup).not.toContain('data-artifact-download-link')
  })
})
