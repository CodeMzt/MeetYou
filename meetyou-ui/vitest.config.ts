import { defineConfig } from 'vitest/config'

export default defineConfig({
  define: {
    __MEETYOU_UI_GIT_COMMIT__: JSON.stringify('test'),
    __MEETYOU_UI_GIT_BRANCH__: JSON.stringify('test'),
    __MEETYOU_UI_BUILD_TIME__: JSON.stringify('2026-04-24T00:00:00Z'),
  },
  test: {
    environment: 'node',
  },
})
