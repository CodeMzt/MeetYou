const { contextBridge } = require('electron')

const bridgeBaseUrl = process.env.MEETYOU_SETTINGS_VISUAL_API_URL || 'http://127.0.0.1:5185'

contextBridge.exposeInMainWorld('meetyouDesktopRuntime', {
  bridgeBaseUrl,
})

contextBridge.exposeInMainWorld('ipcRenderer', {
  on() {
    return () => {}
  },
  off() {},
  send() {},
  invoke(channel, ...args) {
    if (channel === 'get-desktop-bridge-access-token') {
      return Promise.resolve('')
    }
    if (channel === 'select-local-directories') {
      return Promise.resolve({
        canceled: false,
        paths: ['E:\\Visual\\Trusted', 'D:\\Reports\\MeetYou'],
      })
    }
    if (channel === 'open-local-path') {
      const targetPath = String(args[0] || '')
      return Promise.resolve({
        ok: false,
        path: targetPath,
        error: '本机不存在该路径。',
      })
    }
    return Promise.resolve(null)
  },
})
