import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { execFileSync } from 'node:child_process'

function readGitValue(args: string[], fallback = 'unknown') {
  try {
    return execFileSync('git', args, { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'ignore'] }).trim() || fallback
  } catch {
    return fallback
  }
}

const uiGitCommit = process.env.MEETYOU_UI_GIT_COMMIT || readGitValue(['rev-parse', 'HEAD'])
const uiGitBranch = process.env.MEETYOU_UI_GIT_BRANCH || readGitValue(['rev-parse', '--abbrev-ref', 'HEAD'])
const uiBuildTime = process.env.MEETYOU_UI_BUILD_TIME || new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')

// https://vitejs.dev/config/
export default defineConfig(async () => {
  const plugins = [react()]
  if (!process.env.VITEST) {
    const loadModule = new Function('name', 'return import(name)') as <T>(name: string) => Promise<T>
    const [{ default: electron }, { default: renderer }] = await Promise.all([
      loadModule<any>('vite-plugin-electron'),
      loadModule<any>('vite-plugin-electron-renderer'),
    ])
    plugins.push(
      electron([
        {
          entry: 'electron/main.ts',
          vite: {
            build: {
              outDir: 'dist-electron',
              minify: false,
            },
          },
        },
        {
          entry: 'electron/preload.ts',
          onstart(options) {
            options.reload()
          },
          vite: {
            build: {
              outDir: 'dist-electron',
              minify: false,
            },
          },
        },
      ]),
      renderer(),
    )
  }

  return {
    define: {
      __MEETYOU_UI_GIT_COMMIT__: JSON.stringify(uiGitCommit),
      __MEETYOU_UI_GIT_BRANCH__: JSON.stringify(uiGitBranch),
      __MEETYOU_UI_BUILD_TIME__: JSON.stringify(uiBuildTime),
    },
    plugins,
  }
})
