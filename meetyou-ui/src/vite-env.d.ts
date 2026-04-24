/// <reference types="vite/client" />

declare const __MEETYOU_UI_GIT_COMMIT__: string
declare const __MEETYOU_UI_GIT_BRANCH__: string
declare const __MEETYOU_UI_BUILD_TIME__: string

interface Window {
  meetyouDesktopRuntime?: {
    bridgeBaseUrl?: string
  }
  ipcRenderer: {
    send: (channel: string, ...args: any[]) => void
    on: (channel: string, listener: (event: any, ...args: any[]) => void) => () => void
    off: (channel: string, listener: (event: any, ...args: any[]) => void) => void
    invoke: (channel: string, ...args: any[]) => Promise<any>
  }
}
