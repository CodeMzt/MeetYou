import { app, BrowserWindow, ipcMain, screen } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import {
  DESKTOP_BRIDGE_STATUS_PATH,
  DEFAULT_BASE_URL,
  WINDOW_EVENT_CHANNEL,
  WINDOW_HASH_ROUTE,
  WINDOW_OPEN_CHANNEL,
  WINDOW_SYNC_CHANNEL,
} from '../src/windowBridge'

process.env.DIST = path.join(__dirname, '../dist')
process.env.VITE_PUBLIC = app.isPackaged ? process.env.DIST : path.join(process.env.DIST, '../public')

let win: BrowserWindow | null
let dashboardWin: BrowserWindow | null = null
let settingsWin: BrowserWindow | null = null
let runtimeDebugWin: BrowserWindow | null = null
let contextWin: BrowserWindow | null = null
let workspaceWin: BrowserWindow | null = null
let attachmentsWin: BrowserWindow | null = null
let danxiWin: BrowserWindow | null = null
let danxiAuthWin: BrowserWindow | null = null
const VITE_DEV_SERVER_URL = process.env['VITE_DEV_SERVER_URL']

let latestRuntimeDebugWindow = { sessionId: '', baseUrl: DEFAULT_BASE_URL }
let latestContextWindow = { usageSnapshot: null }
let latestWorkspaceWindow = null
let latestAttachmentsWindow = null
let latestDanxiWindow = { baseUrl: DEFAULT_BASE_URL, preferredMode: 'general', workspaceTitle: '' }
let danxiAuthPromise: Promise<any> | null = null
let danxiAuthResolver: ((value: any) => void) | null = null

const DANXI_WEBVPN_LOGIN_URL = 'https://webvpn.fudan.edu.cn/login?cas_login=true'
const DANXI_WEBVPN_LOGIN_PREFIX = 'https://webvpn.fudan.edu.cn/login'
const DANXI_LOGIN_PURPOSE = 'danxi.client.login.v1'
const DANXI_WEBVPN_PURPOSE = 'danxi.client.webvpn_cookie.v1'
const DESKTOP_BACKEND_READY_TIMEOUT_MS = 15000
const DEFAULT_DESKTOP_BRIDGE_HOST = '127.0.0.1'
const DEFAULT_DESKTOP_BRIDGE_PORT = 38951
let desktopBackendProcess: ChildProcess | null = null
let desktopBridgeAccessToken = ''
let desktopBridgeBaseUrl = DEFAULT_BASE_URL

function getWorkspaceRoot() {
  return path.resolve(app.getAppPath(), '..')
}

function readDesktopAgentConfigValue<T = unknown>(key: string): T | null {
  const configPath = path.join(getWorkspaceRoot(), 'user', 'desktop_agent.json')
  try {
    const payload = JSON.parse(fs.readFileSync(configPath, 'utf-8')) as Record<string, unknown>
    return (payload[key] as T | undefined) ?? null
  } catch {
    return null
  }
}

function resolveDesktopBridgeBaseUrl() {
  const host = String(
    process.env.MEETYOU_DESKTOP_LOCAL_HOST ||
    readWorkspaceEnvValue(['MEETYOU_DESKTOP_LOCAL_HOST']) ||
    readDesktopAgentConfigValue<string>('local_bridge_host') ||
    DEFAULT_DESKTOP_BRIDGE_HOST,
  ).trim() || DEFAULT_DESKTOP_BRIDGE_HOST

  const portText = String(
    process.env.MEETYOU_DESKTOP_LOCAL_PORT ||
    readWorkspaceEnvValue(['MEETYOU_DESKTOP_LOCAL_PORT']) ||
    readDesktopAgentConfigValue<number>('local_bridge_port') ||
    DEFAULT_DESKTOP_BRIDGE_PORT,
  ).trim()
  const numericPort = Number.parseInt(portText, 10)
  const port = Number.isFinite(numericPort) && numericPort > 0 ? numericPort : DEFAULT_DESKTOP_BRIDGE_PORT
  return `http://${host}:${port}`
}

function resolveWorkspacePython() {
  const envPython = String(process.env.MEETYOU_DESKTOP_PYTHON || '').trim()
  if (envPython) {
    return envPython
  }
  const candidates = [
    path.join(getWorkspaceRoot(), '.venv', 'Scripts', 'python.exe'),
    path.join(getWorkspaceRoot(), '.venv', 'bin', 'python'),
  ]
  const matched = candidates.find((candidate) => fs.existsSync(candidate))
  if (matched) {
    return matched
  }
  return process.platform === 'win32' ? 'python' : 'python3'
}

function resolveWorkspaceMainPy() {
  return path.join(getWorkspaceRoot(), 'main.py')
}

async function waitForDesktopBackend(timeoutMs = DESKTOP_BACKEND_READY_TIMEOUT_MS) {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(`${desktopBridgeBaseUrl}${DESKTOP_BRIDGE_STATUS_PATH}`)
      if (response.ok) {
        return true
      }
    } catch {
      // Retry until timeout.
    }
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  return false
}

async function ensureDesktopBackendStarted() {
  desktopBridgeBaseUrl = resolveDesktopBridgeBaseUrl()
  process.env.MEETYOU_DESKTOP_BRIDGE_BASE_URL = desktopBridgeBaseUrl
  latestRuntimeDebugWindow = { ...latestRuntimeDebugWindow, baseUrl: desktopBridgeBaseUrl }
  latestDanxiWindow = { ...latestDanxiWindow, baseUrl: desktopBridgeBaseUrl }
  if (await waitForDesktopBackend(500)) {
    desktopBridgeAccessToken = ''
    return
  }
  if (desktopBackendProcess && desktopBackendProcess.exitCode == null) {
    return
  }
  const mainPy = resolveWorkspaceMainPy()
  if (!fs.existsSync(mainPy)) {
    console.warn(`[desktop-backend] main.py not found: ${mainPy}`)
    return
  }
  desktopBridgeAccessToken = crypto.randomBytes(24).toString('hex')
  desktopBackendProcess = spawn(resolveWorkspacePython(), [mainPy, 'desktop-agent'], {
    cwd: getWorkspaceRoot(),
    env: {
      ...process.env,
      MEETYOU_DESKTOP_LOCAL_TOKEN: desktopBridgeAccessToken,
    },
    stdio: 'ignore',
    windowsHide: true,
  })
  desktopBackendProcess.once('error', (error) => {
    console.warn(`[desktop-backend] failed to start: ${error.message}`)
    desktopBackendProcess = null
    desktopBridgeAccessToken = ''
  })
  desktopBackendProcess.once('exit', (code, signal) => {
    console.warn(`[desktop-backend] exited code=${String(code)} signal=${String(signal)}`)
    desktopBackendProcess = null
    desktopBridgeAccessToken = ''
  })
  const ready = await waitForDesktopBackend()
  if (!ready) {
    console.warn('[desktop-backend] bridge did not become ready before timeout')
  }
}

function stopDesktopBackend() {
  if (desktopBackendProcess && desktopBackendProcess.exitCode == null) {
    desktopBackendProcess.kill()
  }
  desktopBackendProcess = null
  desktopBridgeAccessToken = ''
}

function readWorkspaceEnvValue(envNames: string[]): string {
  const envPath = path.join(getWorkspaceRoot(), '.env')
  try {
    const content = fs.readFileSync(envPath, 'utf-8')
    for (const envName of envNames) {
      const escaped = envName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const match = content.match(new RegExp(`^${escaped}\\s*=\\s*['"]?([^'"\\r\\n]+)['"]?\\s*$`, 'm'))
      const value = (match?.[1] || '').trim()
      if (value) {
        return value
      }
    }
    return ''
  } catch {
    return ''
  }
}

function readGatewayAccessToken(): string {
  return readWorkspaceEnvValue(['MEETYOU_GATEWAY_ACCESS_TOKEN'])
}

function resolveCredentialSecret(): string {
  return readWorkspaceEnvValue([
    'MEETYOU_CREDENTIAL_SECRET',
    'MEETYOU_GATEWAY_ACCESS_TOKEN',
    'MEETYOU_AGENT_ACCESS_TOKEN',
  ])
}

function deriveCredentialKey(secret: string, purpose: string): Buffer {
  const prk = crypto.createHmac('sha256', Buffer.from('MeetYouCredentialTransportV1', 'utf-8')).update(secret, 'utf-8').digest()
  return crypto.createHmac('sha256', prk).update(`${purpose}\x01`, 'utf-8').digest()
}

function encryptCredentialPayload(payload: Record<string, unknown>, purpose: string) {
  const secret = resolveCredentialSecret()
  if (!secret) {
    throw new Error('缺少凭证加密密钥，请在 .env 中设置 MEETYOU_CREDENTIAL_SECRET。')
  }
  const iv = crypto.randomBytes(12)
  const cipher = crypto.createCipheriv('aes-256-gcm', deriveCredentialKey(secret, purpose), iv)
  cipher.setAAD(Buffer.from(purpose, 'utf-8'))
  const plaintext = Buffer.from(JSON.stringify(payload || {}), 'utf-8')
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()])
  const tag = cipher.getAuthTag()
  return {
    version: 'v1',
    alg: 'aes-256-gcm',
    purpose,
    iv: iv.toString('base64'),
    ciphertext: ciphertext.toString('base64'),
    tag: tag.toString('base64'),
  }
}

function buildCookieHeader(cookies: Array<{ name: string; value: string }>) {
  return cookies
    .filter((item) => item?.name)
    .map((item) => `${item.name}=${item.value}`)
    .join('; ')
}

async function tryResolveDanxiAuth(windowRef: BrowserWindow | null) {
  if (!windowRef || !danxiAuthResolver) {
    return false
  }
  const currentUrl = windowRef.webContents.getURL() || ''
  if (currentUrl.startsWith(DANXI_WEBVPN_LOGIN_PREFIX)) {
    return false
  }
  const cookies = await windowRef.webContents.session.cookies.get({ url: 'https://webvpn.fudan.edu.cn' })
  if (!cookies.length) {
    return false
  }
  const payload = {
    cookie_header: buildCookieHeader(cookies),
    detected_transport: 'webvpn',
    captured_at: new Date().toISOString(),
    source: 'interactive_auth_window',
    current_url: currentUrl,
  }
  danxiAuthResolver(payload)
  danxiAuthResolver = null
  danxiAuthPromise = null
  if (win) {
    win.webContents.send(WINDOW_EVENT_CHANNEL.danxiAuthUpdated, payload)
  }
  if (danxiWin) {
    danxiWin.webContents.send(WINDOW_EVENT_CHANNEL.danxiAuthUpdated, payload)
  }
  windowRef.close()
  return true
}

function createRuntimeDebugWindow() {
  if (runtimeDebugWin) {
    if (runtimeDebugWin.isMinimized()) runtimeDebugWin.restore()
    runtimeDebugWin.focus()
    return
  }

  const primaryDisplay = screen.getPrimaryDisplay()
  const { width, height } = primaryDisplay.workAreaSize

  const windowWidth = 420
  const windowHeight = 600

  runtimeDebugWin = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width / 2 - windowWidth / 2,
    y: height / 2 - windowHeight / 2,
    icon: path.join(process.env.VITE_PUBLIC || '', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
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
    runtimeDebugWin.setBackgroundMaterial('mica')
  } else if (process.platform === 'darwin') {
    runtimeDebugWin.setVibrancy('popover')
  }

  if (VITE_DEV_SERVER_URL) {
    runtimeDebugWin.loadURL(`${VITE_DEV_SERVER_URL}${WINDOW_HASH_ROUTE.runtimeDebug}`)
  } else {
    runtimeDebugWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.runtimeDebug.slice(2) })
  }

  runtimeDebugWin.on('closed', () => {
    runtimeDebugWin = null
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
    icon: path.join(process.env.VITE_PUBLIC || '', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
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
    settingsWin.loadURL(`${VITE_DEV_SERVER_URL}${WINDOW_HASH_ROUTE.settings}`)
  } else {
    settingsWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.settings.slice(2) })
  }

  settingsWin.on('closed', () => {
    settingsWin = null
  })
}

function createWorkspaceWindow() {
  if (workspaceWin) {
    if (workspaceWin.isMinimized()) workspaceWin.restore()
    workspaceWin.focus()
    return
  }

  const primaryDisplay = screen.getPrimaryDisplay()
  const { width, height } = primaryDisplay.workAreaSize

  const windowWidth = 560
  const windowHeight = 700

  workspaceWin = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width / 2 - windowWidth / 2,
    y: height / 2 - windowHeight / 2,
    icon: path.join(process.env.VITE_PUBLIC || '', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
    transparent: true,
    frame: false,
    resizable: true,
    minWidth: 520,
    minHeight: 620,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  if (process.platform === 'win32') {
    workspaceWin.setBackgroundMaterial('mica')
  } else if (process.platform === 'darwin') {
    workspaceWin.setVibrancy('popover')
  }

  if (VITE_DEV_SERVER_URL) {
    workspaceWin.loadURL(`${VITE_DEV_SERVER_URL}${WINDOW_HASH_ROUTE.workspace}`)
  } else {
    workspaceWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.workspace.slice(2) })
  }

  workspaceWin.on('closed', () => {
    workspaceWin = null
  })
}

function createAttachmentsWindow() {
  if (attachmentsWin) {
    if (attachmentsWin.isMinimized()) attachmentsWin.restore()
    attachmentsWin.focus()
    return
  }

  const primaryDisplay = screen.getPrimaryDisplay()
  const { width, height } = primaryDisplay.workAreaSize

  const windowWidth = 720
  const windowHeight = 700

  attachmentsWin = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width / 2 - windowWidth / 2,
    y: height / 2 - windowHeight / 2,
    icon: path.join(process.env.VITE_PUBLIC || '', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
    transparent: true,
    frame: false,
    resizable: true,
    minWidth: 620,
    minHeight: 620,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  if (process.platform === 'win32') {
    attachmentsWin.setBackgroundMaterial('mica')
  } else if (process.platform === 'darwin') {
    attachmentsWin.setVibrancy('popover')
  }

  if (VITE_DEV_SERVER_URL) {
    attachmentsWin.loadURL(`${VITE_DEV_SERVER_URL}${WINDOW_HASH_ROUTE.attachments}`)
  } else {
    attachmentsWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.attachments.slice(2) })
  }

  attachmentsWin.on('closed', () => {
    attachmentsWin = null
  })
}

function createDanxiWindow() {
  if (danxiWin) {
    if (danxiWin.isMinimized()) danxiWin.restore()
    danxiWin.focus()
    return
  }

  const primaryDisplay = screen.getPrimaryDisplay()
  const { width, height } = primaryDisplay.workAreaSize
  const windowWidth = 960
  const windowHeight = 760

  danxiWin = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width / 2 - windowWidth / 2,
    y: height / 2 - windowHeight / 2,
    icon: path.join(process.env.VITE_PUBLIC || '', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
    transparent: true,
    frame: false,
    resizable: true,
    minWidth: 760,
    minHeight: 620,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  if (process.platform === 'win32') {
    danxiWin.setBackgroundMaterial('mica')
  } else if (process.platform === 'darwin') {
    danxiWin.setVibrancy('popover')
  }

  if (VITE_DEV_SERVER_URL) {
    danxiWin.loadURL(`${VITE_DEV_SERVER_URL}${WINDOW_HASH_ROUTE.danxi}`)
  } else {
    danxiWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.danxi.slice(2) })
  }

  danxiWin.on('closed', () => {
    danxiWin = null
  })
}

function createDanxiAuthWindow() {
  if (danxiAuthWin) {
    if (danxiAuthWin.isMinimized()) danxiAuthWin.restore()
    danxiAuthWin.focus()
    return
  }

  const primaryDisplay = screen.getPrimaryDisplay()
  const { width, height } = primaryDisplay.workAreaSize
  const windowWidth = 1080
  const windowHeight = 820

  danxiAuthWin = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width / 2 - windowWidth / 2,
    y: height / 2 - windowHeight / 2,
    icon: path.join(process.env.VITE_PUBLIC || '', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
    autoHideMenuBar: true,
    title: 'Danxi WebVPN 登录',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  danxiAuthWin.loadURL(DANXI_WEBVPN_LOGIN_URL)

  const tryCapture = () => {
    void tryResolveDanxiAuth(danxiAuthWin)
  }

  danxiAuthWin.webContents.on('did-navigate', tryCapture)
  danxiAuthWin.webContents.on('did-navigate-in-page', tryCapture)
  danxiAuthWin.webContents.on('did-finish-load', tryCapture)

  danxiAuthWin.on('closed', () => {
    if (danxiAuthResolver) {
      danxiAuthResolver({ cancelled: true, source: 'interactive_auth_window' })
      danxiAuthResolver = null
      danxiAuthPromise = null
    }
    danxiAuthWin = null
  })
}

function createContextWindow() {
  if (contextWin) {
    if (contextWin.isMinimized()) contextWin.restore()
    contextWin.focus()
    return
  }

  const primaryDisplay = screen.getPrimaryDisplay()
  const { width, height } = primaryDisplay.workAreaSize

  const windowWidth = 460
  const windowHeight = 620

  contextWin = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width / 2 - windowWidth / 2,
    y: height / 2 - windowHeight / 2,
    icon: path.join(process.env.VITE_PUBLIC || '', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
    transparent: true,
    frame: false,
    resizable: true,
    minWidth: 420,
    minHeight: 520,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  if (process.platform === 'win32') {
    contextWin.setBackgroundMaterial('mica')
  } else if (process.platform === 'darwin') {
    contextWin.setVibrancy('popover')
  }

  if (VITE_DEV_SERVER_URL) {
    contextWin.loadURL(`${VITE_DEV_SERVER_URL}${WINDOW_HASH_ROUTE.context}`)
  } else {
    contextWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.context.slice(2) })
  }

  contextWin.on('closed', () => {
    contextWin = null
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
    icon: path.join(process.env.VITE_PUBLIC || '', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
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
    dashboardWin.loadURL(`${VITE_DEV_SERVER_URL}${WINDOW_HASH_ROUTE.dashboard}`)
  } else {
    dashboardWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.dashboard.slice(2) })
  }

  dashboardWin.on('closed', () => {
    dashboardWin = null
  })
}

function forwardWindowState(windowRef: BrowserWindow | null, channel: string, data: unknown) {
  if (windowRef) {
    windowRef.webContents.send(channel, data)
  }
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
    icon: path.join(process.env.VITE_PUBLIC || '', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
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
  
  ipcMain.on(WINDOW_OPEN_CHANNEL.dashboard, () => {
    createDashboardWindow()
  })
  ipcMain.on(WINDOW_OPEN_CHANNEL.settings, () => {
    createSettingsWindow()
  })
  ipcMain.on(WINDOW_OPEN_CHANNEL.workspace, () => {
    createWorkspaceWindow()
  })
  ipcMain.on(WINDOW_OPEN_CHANNEL.attachments, () => {
    createAttachmentsWindow()
  })
  ipcMain.on(WINDOW_OPEN_CHANNEL.danxi, () => {
    createDanxiWindow()
  })
  ipcMain.on(WINDOW_OPEN_CHANNEL.runtimeDebug, () => {
    createRuntimeDebugWindow()
  })
  ipcMain.on(WINDOW_SYNC_CHANNEL.runtimeDebug.update, (_e, data) => {
    latestRuntimeDebugWindow = data
    forwardWindowState(runtimeDebugWin, WINDOW_SYNC_CHANNEL.runtimeDebug.update, data)
  })
  ipcMain.on(WINDOW_SYNC_CHANNEL.runtimeDebug.request, (e) => {
    e.sender.send(WINDOW_SYNC_CHANNEL.runtimeDebug.update, latestRuntimeDebugWindow)
  })
  ipcMain.on(WINDOW_SYNC_CHANNEL.context.update, (_e, data) => {
    latestContextWindow = data
    forwardWindowState(contextWin, WINDOW_SYNC_CHANNEL.context.update, data)
  })
  ipcMain.on(WINDOW_SYNC_CHANNEL.context.request, (e) => {
    e.sender.send(WINDOW_SYNC_CHANNEL.context.update, latestContextWindow)
  })
  ipcMain.on(WINDOW_SYNC_CHANNEL.workspace.update, (_e, data) => {
    latestWorkspaceWindow = data
    forwardWindowState(workspaceWin, WINDOW_SYNC_CHANNEL.workspace.update, data)
  })
  ipcMain.on(WINDOW_SYNC_CHANNEL.workspace.request, (e) => {
    e.sender.send(WINDOW_SYNC_CHANNEL.workspace.update, latestWorkspaceWindow)
  })
  ipcMain.on(WINDOW_SYNC_CHANNEL.attachments.update, (_e, data) => {
    latestAttachmentsWindow = data
    forwardWindowState(attachmentsWin, WINDOW_SYNC_CHANNEL.attachments.update, data)
  })
  ipcMain.on(WINDOW_SYNC_CHANNEL.attachments.request, (e) => {
    e.sender.send(WINDOW_SYNC_CHANNEL.attachments.update, latestAttachmentsWindow)
  })
  ipcMain.on(WINDOW_SYNC_CHANNEL.danxi.update, (_e, data) => {
    latestDanxiWindow = data
    forwardWindowState(danxiWin, WINDOW_SYNC_CHANNEL.danxi.update, data)
  })
  ipcMain.on(WINDOW_SYNC_CHANNEL.danxi.request, (e) => {
    e.sender.send(WINDOW_SYNC_CHANNEL.danxi.update, latestDanxiWindow)
  })
  ipcMain.on(WINDOW_EVENT_CHANNEL.workspaceGovernanceUpdated, (_e, data) => {
    if (win) {
      win.webContents.send(WINDOW_EVENT_CHANNEL.workspaceGovernanceUpdated, data)
    }
    if (workspaceWin) {
      workspaceWin.webContents.send(WINDOW_EVENT_CHANNEL.workspaceGovernanceUpdated, data)
    }
  })
  ipcMain.on(WINDOW_OPEN_CHANNEL.context, () => {
    createContextWindow()
  })
  ipcMain.on('cancel-danxi-auth-window', () => {
    danxiAuthWin?.close()
  })
  ipcMain.removeHandler('get-desktop-bridge-base-url')
  ipcMain.handle('get-desktop-bridge-base-url', () => desktopBridgeBaseUrl)
  ipcMain.removeHandler('get-desktop-bridge-access-token')
  ipcMain.handle('get-desktop-bridge-access-token', () => desktopBridgeAccessToken)
  ipcMain.removeHandler('get-gateway-access-token')
  ipcMain.handle('get-gateway-access-token', () => desktopBridgeAccessToken)
  ipcMain.removeHandler('encrypt-danxi-credentials')
  ipcMain.handle('encrypt-danxi-credentials', (_event, payload: Record<string, unknown>) => {
    const purpose = String(payload?.purpose || '').trim()
    const data = payload && typeof payload === 'object' && payload.data && typeof payload.data === 'object' ? payload.data : {}
    if (purpose === DANXI_LOGIN_PURPOSE || purpose === DANXI_WEBVPN_PURPOSE) {
      return encryptCredentialPayload(data as Record<string, unknown>, purpose)
    }
    throw new Error('不支持的 Danxi 凭证加密用途。')
  })
  ipcMain.removeHandler('open-danxi-auth-window')
  ipcMain.handle('open-danxi-auth-window', async () => {
    if (!danxiAuthPromise) {
      danxiAuthPromise = new Promise((resolve) => {
        danxiAuthResolver = resolve
      })
      createDanxiAuthWindow()
    } else {
      createDanxiAuthWindow()
    }
    return danxiAuthPromise
  })
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
    win = null
  }
})

app.on('before-quit', () => {
  stopDesktopBackend()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})

if (process.platform === 'win32') {
  app.setAppUserModelId('com.meetyou.app')
}

app.whenReady().then(async () => {
  await ensureDesktopBackendStarted()
  createWindow()
})
