const { contextBridge } = require('electron')

const listeners = new Map()

function emit(channel, data) {
  const callbacks = listeners.get(channel) || new Set()
  for (const callback of callbacks) {
    try {
      callback({}, data)
    } catch {
      // Visual QA should not fail because a mocked listener throws.
    }
  }
}

contextBridge.exposeInMainWorld('meetyouDesktopRuntime', {
  bridgeBaseUrl: process.env.MEETYOU_CHAT_VISUAL_API_BASE_URL || 'http://127.0.0.1:38951',
})

contextBridge.exposeInMainWorld('ipcRenderer', {
  on(channel, callback) {
    if (!listeners.has(channel)) {
      listeners.set(channel, new Set())
    }
    listeners.get(channel).add(callback)
  },
  off(channel, callback) {
    listeners.get(channel)?.delete(callback)
  },
  send(channel, data) {
    if (channel === 'request-context-window') {
      setTimeout(() => emit('context-window-updated', data || null), 0)
    }
  },
  invoke(channel) {
    if (channel === 'get-desktop-bridge-access-token' || channel === 'get-gateway-access-token') {
      return Promise.resolve('')
    }
    return Promise.resolve(null)
  },
})
