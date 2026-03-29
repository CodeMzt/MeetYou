import { app, BrowserWindow, ipcMain, screen } from 'electron'
import path from 'node:path'

process.env.DIST = path.join(__dirname, '../dist')
process.env.VITE_PUBLIC = app.isPackaged ? process.env.DIST : path.join(process.env.DIST, '../public')

let win: BrowserWindow | null
const VITE_DEV_SERVER_URL = process.env['VITE_DEV_SERVER_URL']

function createWindow() {
  const primaryDisplay = screen.getPrimaryDisplay()
  const { width, height } = primaryDisplay.workAreaSize

  win = new BrowserWindow({
    width: 360,
    height: 560,
    x: width - 380,
    y: height - 600,
    icon: path.join(process.env.VITE_PUBLIC, 'electron-vite.svg'),
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: true,
    minWidth: 300,
    minHeight: 400,
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
    win.loadFile(path.join(process.env.DIST, 'index.html'))
  }

  // Titlebar controls
  ipcMain.on('window-close', () => win?.close())
  ipcMain.on('window-minimize', () => win?.minimize())
  // Toggle always on top
  ipcMain.on('window-toggle-top', (e, isTop: boolean) => {
    win?.setAlwaysOnTop(isTop)
  })
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
