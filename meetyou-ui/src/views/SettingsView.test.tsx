import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SettingsView from './SettingsView'

const mocks = vi.hoisted(() => ({
  useConfig: vi.fn(),
}))

vi.mock('../hooks/useConfig', () => ({
  useConfig: mocks.useConfig,
}))

function makeConfigResult() {
  return {
    groupedFields: [
      {
        key: 'modes',
        title: '模式',
        description: '模式配置',
        commonFields: [
          {
            key: 'trusted_write_roots',
            schema: {
              key: 'trusted_write_roots',
              title: '可信写入目录',
              description: '无需额外放宽信任边界即可写入本地文档的目录列表。',
              group: 'modes',
              input: 'list',
              control: 'directory_list',
              help_text: '每项是一个允许写入的目录。',
              examples: ['E:\\Documents\\MeetYou'],
            },
            entry: {
              key: 'trusted_write_roots',
              value: ['E:\\Documents\\MeetYou'],
              is_secret: false,
              has_value: true,
              source: 'config',
              env_key: null,
            },
            value: 'E:\\Documents\\MeetYou',
            dirty: false,
            error: null,
          },
        ],
        advancedFields: [],
      },
    ],
    loading: false,
    saving: false,
    error: null,
    saveResult: null,
    dirtyKeys: [],
    hasDirtyChanges: false,
    updateField: vi.fn(),
    clearSecretField: vi.fn(),
    resetChanges: vi.fn(),
    refresh: vi.fn(),
    saveConfig: vi.fn(),
  }
}

describe('SettingsView', () => {
  const originalWindow = globalThis.window

  afterEach(() => {
    mocks.useConfig.mockReset()
    globalThis.window = originalWindow
  })

  it('falls back to manual list editing when directory IPC is unavailable', () => {
    mocks.useConfig.mockReturnValue(makeConfigResult())
    globalThis.window = undefined as unknown as Window & typeof globalThis

    const markup = renderToStaticMarkup(<SettingsView />)

    expect(markup).toContain('SKILL')
    expect(markup).toContain('可信写入目录')
    expect(markup).toContain('每项是一个允许写入的目录。')
    expect(markup).toContain('E:\\Documents\\MeetYou')
    expect(markup).toContain('textarea')
    expect(markup).toContain('一行一个值')
  })

  it('renders directory picker controls when Electron IPC is available', () => {
    mocks.useConfig.mockReturnValue(makeConfigResult())
    globalThis.window = Object.assign(globalThis.window || {}, {
      ipcRenderer: {
        invoke: vi.fn(),
      },
    }) as Window & typeof globalThis

    const markup = renderToStaticMarkup(<SettingsView />)

    expect(markup).toContain('添加目录')
    expect(markup).toContain('E:\\Documents\\MeetYou')
    expect(markup).not.toContain('textarea')
  })
})
