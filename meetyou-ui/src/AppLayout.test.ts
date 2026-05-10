import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

function readCss(relativePath: string): string {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

describe('compact Electron layout CSS', () => {
  it('keeps the V5 control dock below the titlebar at 400px width', () => {
    const css = readCss('./App.module.css')

    expect(css).toContain('@media (max-width: 420px)')
    expect(css).toContain('top: 8px;')
    expect(css).toContain('left: 8px;')
    expect(css).toContain('right: 8px;')
    expect(css).toContain('flex-wrap: nowrap;')
    expect(css).toContain('padding-top: 48px;')
    expect(css).not.toContain('top: -36px;')
  })

  it('keeps original titlebar tools visible instead of replacing them with a compact menu', () => {
    const css = readCss('./components/layout/Titlebar.module.css')

    expect(css).toContain('.tools {\n  display: flex;')
    expect(css).not.toContain('.fullTool')
    expect(css).not.toContain('.compactToolsTrigger')
    expect(css).not.toContain('.tools {\n    display: none;')
  })

  it('uses 32px compact triggers for the V5 dock controls', () => {
    const projectCss = readCss('./components/project/ProjectPicker.module.css')
    const threadCss = readCss('./components/thread/ThreadPicker.module.css')
    const versionCss = readCss('./components/version/VersionControl.module.css')
    const sourcesCss = readCss('./components/project/ProjectSources.module.css')
    const artifactsCss = readCss('./components/project/ProjectArtifacts.module.css')

    for (const css of [projectCss, threadCss, versionCss, sourcesCss, artifactsCss]) {
      expect(css).toContain('flex: 0 0 auto;')
      expect(css).toContain('@media (max-width: 420px)')
      expect(css).toContain('height: 32px;')
    }
  })
})
