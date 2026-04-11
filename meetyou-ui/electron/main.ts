import { app, BrowserWindow, ipcMain, screen } from 'electron'
import fs from 'node:fs'
import path from 'node:path'

process.env.DIST = path.join(__dirname, '../dist')
process.env.VITE_PUBLIC = app.isPackaged ? process.env.DIST : path.join(process.env.DIST, '../public')

let win: BrowserWindow | null
let dashboardWin: BrowserWindow | null = null
let settingsWin: BrowserWindow | null = null
let devtoolsWin: BrowserWindow | null = null
const VITE_DEV_SERVER_URL = process.env['VITE_DEV_SERVER_URL']

let latestDevtools = { usageSnapshot: null, runtimeDebugSnapshot: null }

function getWorkspaceRoot() {
  return path.resolve(app.getAppPath(), '..')
}

function readGatewayAccessToken(): string {
  const envPath = path.join(getWorkspaceRoot(), '.env')
  try {
    const content = fs.readFileSync(envPath, 'utf-8')
    const match = content.match(/^MEETYOU_GATEWAY_ACCESS_TOKEN\s*=\s*['"]?([^'"\r\n]+)['"]?\s*$/m)
    return (match?.[1] || '').trim()
  } catch {
    return ''
  }
}

function createDevtoolsWindow() {
  if (devtoolsWin) {
    if (devtoolsWin.isMinimized()) devtoolsWin.restore()
    devtoolsWin.focus()
    return
  }

  const primaryDisplay = screen.getPrimaryDisplay()
  const { width, height } = primaryDisplay.workAreaSize

  const windowWidth = 420
  const windowHeight = 600

  devtoolsWin = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width / 2 - windowWidth / 2,
    y: height / 2 - windowHeight / 2,
    icon: path.join(process.env.VITE_PUBLIC || '', 'electron-vite.svg'),
    transparent: true,
    frame: false,
    resizable: true,
    minWidth: 380,
    minHeight: 500,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  if (process.platform === 'win32') {
    devtoolsWin.setBackgroundMaterial('mica')
  } else if (process.platform === 'darwin') {
    devtoolsWin.setVibrancy('popover')
  }

  if (VITE_DEV_SERVER_URL) {
    devtoolsWin.loadURL(`${VITE_DEV_SERVER_URL}#/devtools`)
  } else {
    devtoolsWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: 'devtools' })
  }

  devtoolsWin.on('closed', () => {
    devtoolsWin = null
  })
}

function createSettingsWindow() {
  if (settingsWin) {
    if (settingsWin.isMinimized()) settingsWin.restore()
    settingsWin.focus()
    return
  }

  const primaryDisplay = screen.getPrimaryDisplay()
  const { width, height } = primaryDisplay.workAreaSize

  const windowWidth = 520
  const windowHeight = 660

  settingsWin = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width / 2 - windowWidth / 2,
    y: height / 2 - windowHeight / 2,
    icon: path.join(process.env.VITE_PUBLIC || '', 'electron-vite.svg'),
    transparent: true,
    frame: false,
    resizable: true,
    minWidth: 560,
    minHeight: 620,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  if (process.platform === 'win32') {
    settingsWin.setBackgroundMaterial('mica')
  } else if (process.platform === 'darwin') {
    settingsWin.setVibrancy('popover')
  }

  if (VITE_DEV_SERVER_URL) {
    settingsWin.loadURL(`${VITE_DEV_SERVER_URL}#/settings`)
  } else {
    settingsWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: 'settings' })
  }

  settingsWin.on('closed', () => {
    settingsWin = null
  })
}

function createDashboardWindow() {
  if (dashboardWin) {
    if (dashboardWin.isMinimized()) dashboardWin.restore()
    dashboardWin.focus()
    return
  }

  const primaryDisplay = screen.getPrimaryDisplay()
  const { width, height } = primaryDisplay.workAreaSize

  const windowWidth = 800
  const windowHeight = 640

  dashboardWin = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width / 2 - windowWidth / 2,
    y: height / 2 - windowHeight / 2,
    icon: path.join(process.env.VITE_PUBLIC || '', 'electron-vite.svg'),
    transparent: true,
    frame: false,
    resizable: true,
    minWidth: 840,
    minHeight: 620,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  if (process.platform === 'win32') {
    dashboardWin.setBackgroundMaterial('mica')
  } else if (process.platform === 'darwin') {
    dashboardWin.setVibrancy('popover')
  }

  if (VITE_DEV_SERVER_URL) {
    dashboardWin.loadURL(`${VITE_DEV_SERVER_URL}#/dashboard`)
  } else {
    dashboardWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: 'dashboard' })
  }

  dashboardWin.on('closed', () => {
    dashboardWin = null
  })
}

function createWindow() {
  const primaryDisplay = screen.getPrimaryDisplay()
  const { width, height } = primaryDisplay.workAreaSize

  const windowWidth = 400
  const windowHeight = 620

  win = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width - windowWidth - 20,
    y: height - windowHeight - 40,
    icon: path.join(process.env.VITE_PUBLIC || '', 'electron-vite.svg'),
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: true,
    minWidth: 340,
    minHeight: 460,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      // Needed for some local assets and modules
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  // Enable OS native vibrant effects
  if (process.platform === 'win32') {
    win.setBackgroundMaterial('mica')
  } else if (process.platform === 'darwin') {
    win.setVibrancy('popover')
  }

  if (VITE_DEV_SERVER_URL) {
    win.loadURL(VITE_DEV_SERVER_URL)
  } else {
    win.loadFile(path.join(process.env.DIST || '', 'index.html'))
  }

  // Titlebar controls
  ipcMain.on('window-close', (e) => {
    const w = BrowserWindow.fromWebContents(e.sender)
    w?.close()
  })
  ipcMain.on('window-minimize', (e) => {
    const w = BrowserWindow.fromWebContents(e.sender)
    w?.minimize()
  })
  ipcMain.on('window-maximize', (e) => {
    const w = BrowserWindow.fromWebContents(e.sender)
    if (w?.isMaximized()) w.unmaximize()
    else w?.maximize()
  })
  // Toggle always on top
  ipcMain.on('window-toggle-top', (e, isTop: boolean) => {
    const w = BrowserWindow.fromWebContents(e.sender)
    w?.setAlwaysOnTop(isTop)
  })
  
  ipcMain.on('open-dashboard', () => {
    createDashboardWindow()
  })
  ipcMain.on('open-settings', () => {
    createSettingsWindow()
  })
  ipcMain.on('open-devtools', () => {
    createDevtoolsWindow()
  })
  ipcMain.on('update-devtools', (e, data) => {
    latestDevtools = data
    if (devtoolsWin) {
      devtoolsWin.webContents.send('devtools-updated', data)
    }
  })
  ipcMain.on('request-devtools', (e) => {
    e.sender.send('devtools-updated', latestDevtools)
  })
  ipcMain.on('open-stats', () => {
    createDevtoolsWindow()
  })
  ipcMain.on('update-stats', (e, data) => {
    latestDevtools = data
    if (devtoolsWin) {
      devtoolsWin.webContents.send('devtools-updated', data)
    }
  })
  ipcMain.on('request-stats', (e) => {
    e.sender.send('devtools-updated', latestDevtools)
  })
  ipcMain.removeHandler('get-gateway-access-token')
  ipcMain.handle('get-gateway-access-token', () => readGatewayAccessToken())
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
    win = null
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})

app.whenReady().then(createWindow)
