import { app, BrowserWindow, dialog, ipcMain, screen } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
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
let danxiWin: BrowserWindow | null = null
let danxiAuthWin: BrowserWindow | null = null
const VITE_DEV_SERVER_URL = process.env['VITE_DEV_SERVER_URL']

let latestRuntimeDebugWindow = { sessionId: '', baseUrl: DEFAULT_BASE_URL }
let latestContextWindow = { usageSnapshot: null }
let latestWorkspaceWindow = null
let latestDanxiWindow = { baseUrl: DEFAULT_BASE_URL, preferredMode: 'general', workspaceTitle: '' }
let danxiAuthPromise: Promise<any> | null = null
let danxiAuthResolver: ((value: any) => void) | null = null

const DANXI_WEBVPN_LOGIN_URL = 'https://webvpn.fudan.edu.cn/login?cas_login=true'
const DANXI_WEBVPN_LOGIN_PREFIX = 'https://webvpn.fudan.edu.cn/login'
const DANXI_WEBVPN_HOST = 'webvpn.fudan.edu.cn'
const DANXI_LOGIN_PURPOSE = 'danxi.client.login.v1'
const DANXI_WEBVPN_PURPOSE = 'danxi.client.webvpn_cookie.v1'
const DANXI_AUTH_WINDOW_PARTITION = 'persist:danxi-auth'
const DANXI_AUTH_USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
const DESKTOP_BACKEND_READY_TIMEOUT_MS = 15000
const DEFAULT_DESKTOP_BRIDGE_HOST = '127.0.0.1'
const DEFAULT_DESKTOP_BRIDGE_PORT = 38951
const RUNTIME_ENV_KEYS = [
  'MEETYOU_CORE_BASE_URL',
  'MEETYOU_GATEWAY_ACCESS_TOKEN',
  'MEETYOU_CLIENT_ACCESS_TOKEN',
  'MEETYOU_CREDENTIAL_SECRET',
] as const
const RUNTIME_SECRET_ENV_KEYS = new Set([
  'MEETYOU_GATEWAY_ACCESS_TOKEN',
  'MEETYOU_CLIENT_ACCESS_TOKEN',
  'MEETYOU_CREDENTIAL_SECRET',
])
let desktopBackendProcess: ChildProcess | null = null
let desktopBridgeAccessToken = ''
let desktopBridgeBaseUrl = DEFAULT_BASE_URL

type DesktopBackendStatusPayload = {
  build_info?: {
    git_commit?: unknown
  }
}

type RuntimeEnvValues = Partial<Record<typeof RUNTIME_ENV_KEYS[number], string>>

function getWorkspaceRoot() {
  return path.resolve(app.getAppPath(), '..')
}

function getDesktopRuntimeRoot() {
  if (!app.isPackaged) {
    return getWorkspaceRoot()
  }
  return path.join(app.getPath('userData'), 'meetyou-runtime')
}

function getDesktopConfigPath() {
  const explicit = String(process.env.MEETYOU_DESKTOP_CLIENT_CONFIG || '').trim()
  if (explicit) {
    return explicit
  }
  return path.join(getDesktopRuntimeRoot(), 'user', 'desktop_client.json')
}

function readDesktopClientConfigValue<T = unknown>(key: string): T | null {
  const configPath = getDesktopConfigPath()
  try {
    const payload = JSON.parse(fs.readFileSync(configPath, 'utf-8')) as Record<string, unknown>
    return (payload[key] as T | undefined) ?? null
  } catch {
    return null
  }
}

function resolveCoreBaseUrl() {
  const processCoreBaseUrl = String(process.env.MEETYOU_CORE_BASE_URL || '').trim()
  const runtimeCoreBaseUrl = readWorkspaceEnvValue(['MEETYOU_CORE_BASE_URL'])
  if (
    app.isPackaged &&
    runtimeCoreBaseUrl &&
    (!processCoreBaseUrl || isLoopbackCoreUrl(processCoreBaseUrl))
  ) {
    return runtimeCoreBaseUrl
  }
  return String(
    processCoreBaseUrl ||
    runtimeCoreBaseUrl ||
    readDesktopClientConfigValue<string>('core_base_url') ||
    'http://127.0.0.1:8000',
  ).trim() || 'http://127.0.0.1:8000'
}

function resolveDesktopBridgeBaseUrl() {
  const host = String(
    process.env.MEETYOU_DESKTOP_LOCAL_HOST ||
    readWorkspaceEnvValue(['MEETYOU_DESKTOP_LOCAL_HOST']) ||
    readDesktopClientConfigValue<string>('local_bridge_host') ||
    DEFAULT_DESKTOP_BRIDGE_HOST,
  ).trim() || DEFAULT_DESKTOP_BRIDGE_HOST

  const portText = String(
    process.env.MEETYOU_DESKTOP_LOCAL_PORT ||
    readWorkspaceEnvValue(['MEETYOU_DESKTOP_LOCAL_PORT']) ||
    readDesktopClientConfigValue<number>('local_bridge_port') ||
    DEFAULT_DESKTOP_BRIDGE_PORT,
  ).trim()
  const numericPort = Number.parseInt(portText, 10)
  const port = Number.isFinite(numericPort) && numericPort > 0 ? numericPort : DEFAULT_DESKTOP_BRIDGE_PORT
  return `http://${host}:${port}`
}

function setDesktopBridgeBaseUrl(baseUrl: string) {
  desktopBridgeBaseUrl = baseUrl
  process.env.MEETYOU_DESKTOP_BRIDGE_BASE_URL = desktopBridgeBaseUrl
  latestRuntimeDebugWindow = { ...latestRuntimeDebugWindow, baseUrl: desktopBridgeBaseUrl }
  latestDanxiWindow = { ...latestDanxiWindow, baseUrl: desktopBridgeBaseUrl }
}

function expectedUiGitCommit() {
  return String(
    typeof __MEETYOU_UI_GIT_COMMIT__ === 'string' ? __MEETYOU_UI_GIT_COMMIT__ : '',
  ).trim()
}

function desktopBackendGitCommit(status: DesktopBackendStatusPayload | null) {
  return String(status?.build_info?.git_commit || '').trim()
}

function isDesktopBackendBuildAligned(status: DesktopBackendStatusPayload | null) {
  const expected = expectedUiGitCommit()
  const actual = desktopBackendGitCommit(status)
  if (!expected || expected === 'unknown' || !actual || actual === 'unknown') {
    return true
  }
  return expected === actual
}

function parseDesktopBridgeHost(value: string) {
  try {
    return new URL(value).hostname || DEFAULT_DESKTOP_BRIDGE_HOST
  } catch {
    return DEFAULT_DESKTOP_BRIDGE_HOST
  }
}

function parseDesktopBridgePort(value: string) {
  try {
    const port = Number.parseInt(new URL(value).port || '', 10)
    return Number.isFinite(port) && port > 0 ? port : DEFAULT_DESKTOP_BRIDGE_PORT
  } catch {
    return DEFAULT_DESKTOP_BRIDGE_PORT
  }
}

function canBindDesktopBridge(host: string, port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer()
    let settled = false
    const finish = (available: boolean) => {
      if (settled) {
        return
      }
      settled = true
      resolve(available)
    }
    server.once('error', () => finish(false))
    server.listen(port, host, () => {
      server.close((error) => finish(!error))
    })
  })
}

function allocateDesktopBridgePort(host: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', reject)
    server.listen(0, host, () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close((error) => {
        if (error) {
          reject(error)
          return
        }
        if (!port) {
          reject(new Error('desktop_bridge_port_unavailable'))
          return
        }
        resolve(port)
      })
    })
  })
}

async function moveDesktopBridgeToAvailablePort(reason: string) {
  const host = parseDesktopBridgeHost(desktopBridgeBaseUrl)
  const port = await allocateDesktopBridgePort(host)
  process.env.MEETYOU_DESKTOP_LOCAL_HOST = host
  process.env.MEETYOU_DESKTOP_LOCAL_PORT = String(port)
  setDesktopBridgeBaseUrl(`http://${host}:${port}`)
  console.warn(`[desktop-backend] using alternate local bridge ${desktopBridgeBaseUrl}: ${reason}`)
}

async function ensureDesktopBridgeAddressAvailable() {
  const host = parseDesktopBridgeHost(desktopBridgeBaseUrl)
  const port = parseDesktopBridgePort(desktopBridgeBaseUrl)
  if (await canBindDesktopBridge(host, port)) {
    return
  }
  await moveDesktopBridgeToAvailablePort(`configured bridge ${desktopBridgeBaseUrl} is already in use`)
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

function resolvePackagedBackendExecutable() {
  const binaryName = process.platform === 'win32' ? 'desktop_client.exe' : 'desktop_client'
  return path.join(process.resourcesPath, 'desktop-backend', 'desktop_client', binaryName)
}

function ensureJsonFile(filePath: string, payload: Record<string, unknown>) {
  if (fs.existsSync(filePath)) {
    return
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, 'utf-8')
}

function copyFileIfMissing(source: string, destination: string) {
  if (!fs.existsSync(source) || fs.existsSync(destination)) {
    return
  }
  fs.mkdirSync(path.dirname(destination), { recursive: true })
  fs.copyFileSync(source, destination)
}

function parseEnvLine(line: string): { key: string; value: string } | null {
  const match = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/)
  if (!match) {
    return null
  }
  let value = String(match[2] || '').trim()
  if (
    value.length >= 2 &&
    ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'")))
  ) {
    value = value.slice(1, -1)
  }
  return { key: match[1], value }
}

function readEnvFileValues(envPath: string, keys: readonly string[] = RUNTIME_ENV_KEYS): RuntimeEnvValues {
  const wanted = new Set(keys)
  const values: RuntimeEnvValues = {}
  try {
    const lines = fs.readFileSync(envPath, 'utf-8').split(/\r?\n/)
    for (const line of lines) {
      const parsed = parseEnvLine(line)
      if (!parsed || !wanted.has(parsed.key)) {
        continue
      }
      values[parsed.key as keyof RuntimeEnvValues] = parsed.value
    }
  } catch {
    // Missing runtime env files are valid on first packaged launch.
  }
  return values
}

function writeEnvFileValues(envPath: string, updates: RuntimeEnvValues) {
  const entries = Object.entries(updates).filter(([, value]) => String(value || '').trim())
  if (!entries.length) {
    return
  }
  const updateMap = new Map(entries.map(([key, value]) => [key, String(value).trim()]))
  const lines = fs.existsSync(envPath) ? fs.readFileSync(envPath, 'utf-8').split(/\r?\n/) : []
  const seen = new Set<string>()
  const nextLines = lines.map((line) => {
    const parsed = parseEnvLine(line)
    if (!parsed || !updateMap.has(parsed.key)) {
      return line
    }
    seen.add(parsed.key)
    return `${parsed.key}=${updateMap.get(parsed.key)}`
  })
  for (const [key, value] of updateMap.entries()) {
    if (!seen.has(key)) {
      nextLines.push(`${key}=${value}`)
    }
  }
  fs.mkdirSync(path.dirname(envPath), { recursive: true })
  fs.writeFileSync(envPath, `${nextLines.filter((line, index) => line || index < nextLines.length - 1).join('\n')}\n`, 'utf-8')
}

function readJsonFile(filePath: string): Record<string, unknown> | null {
  try {
    const payload = JSON.parse(fs.readFileSync(filePath, 'utf-8'))
    return payload && typeof payload === 'object' && !Array.isArray(payload) ? payload as Record<string, unknown> : null
  } catch {
    return null
  }
}

function writeJsonFile(filePath: string, payload: Record<string, unknown>) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, 'utf-8')
}

function getPackagedRuntimeTemplateRoot() {
  return path.join(process.resourcesPath, 'runtime-template')
}

function isLoopbackCoreUrl(value: unknown) {
  const text = String(value || '').trim()
  return /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/?$/i.test(text)
}

function resolveTemplateCoreBaseUrl(templateConfigPath: string, templateEnvPath: string) {
  const templateEnv = readEnvFileValues(templateEnvPath)
  const envCoreUrl = String(templateEnv.MEETYOU_CORE_BASE_URL || '').trim()
  if (envCoreUrl && !isLoopbackCoreUrl(envCoreUrl)) {
    return envCoreUrl
  }
  const template = readJsonFile(templateConfigPath)
  const templateCoreUrl = String(template?.core_base_url || '').trim()
  return templateCoreUrl && !isLoopbackCoreUrl(templateCoreUrl) ? templateCoreUrl : ''
}

function syncRuntimeEnvFromTemplate(runtimeEnvPath: string, templateEnvPath: string) {
  const template = readEnvFileValues(templateEnvPath)
  const current = readEnvFileValues(runtimeEnvPath)
  const templateCoreUrl = String(template.MEETYOU_CORE_BASE_URL || '').trim()
  const currentCoreUrl = String(current.MEETYOU_CORE_BASE_URL || '').trim()
  const replacingLoopbackCoreUrl = Boolean(
    templateCoreUrl &&
    !isLoopbackCoreUrl(templateCoreUrl) &&
    (!currentCoreUrl || isLoopbackCoreUrl(currentCoreUrl)),
  )
  const updates: RuntimeEnvValues = {}
  if (replacingLoopbackCoreUrl) {
    updates.MEETYOU_CORE_BASE_URL = templateCoreUrl
  }
  for (const key of RUNTIME_ENV_KEYS) {
    if (key === 'MEETYOU_CORE_BASE_URL') {
      continue
    }
    const templateValue = String(template[key] || '').trim()
    if (!templateValue) {
      continue
    }
    const currentValue = String(current[key] || '').trim()
    if (!currentValue || (replacingLoopbackCoreUrl && RUNTIME_SECRET_ENV_KEYS.has(key))) {
      updates[key] = templateValue
    }
  }
  writeEnvFileValues(runtimeEnvPath, updates)
}

function maybeMigrateDefaultCoreUrlFromTemplate(configPath: string, templateConfigPath: string, templateEnvPath: string) {
  const current = readJsonFile(configPath)
  const templateCoreUrl = resolveTemplateCoreBaseUrl(templateConfigPath, templateEnvPath)
  if (!current || !templateCoreUrl) {
    return
  }
  if (!current.core_base_url || isLoopbackCoreUrl(current.core_base_url)) {
    current.core_base_url = templateCoreUrl
    writeJsonFile(configPath, current)
  }
}

function ensurePackagedRuntimeFiles() {
  if (!app.isPackaged) {
    return
  }
  const runtimeRoot = getDesktopRuntimeRoot()
  const userDir = path.join(runtimeRoot, 'user')
  const templateRoot = getPackagedRuntimeTemplateRoot()
  const templateUserDir = path.join(templateRoot, 'user')
  const runtimeEnvPath = path.join(runtimeRoot, '.env')
  const templateEnvPath = path.join(templateRoot, '.env')
  fs.mkdirSync(userDir, { recursive: true })
  copyFileIfMissing(templateEnvPath, runtimeEnvPath)
  syncRuntimeEnvFromTemplate(runtimeEnvPath, templateEnvPath)
  copyFileIfMissing(path.join(templateUserDir, 'cmd_policy.json'), path.join(userDir, 'cmd_policy.json'))
  copyFileIfMissing(path.join(templateUserDir, 'mcp_servers.json'), path.join(userDir, 'mcp_servers.json'))
  copyFileIfMissing(path.join(templateUserDir, 'desktop_client.json'), getDesktopConfigPath())
  ensureJsonFile(path.join(userDir, 'cmd_policy.json'), {
    mode: 'blacklist',
    blacklist_patterns: [],
  })
  ensureJsonFile(path.join(userDir, 'mcp_servers.json'), {})
  ensureJsonFile(getDesktopConfigPath(), {
    core_base_url: resolveCoreBaseUrl(),
    client_id: 'desktop-app',
    client_type: 'desktop',
    display_name: 'Desktop App',
    workspace_ids: ['personal', 'desktop-main', 'study'],
    read_roots: [runtimeRoot],
    trusted_write_roots: [runtimeRoot],
    cmd_policy_path: 'user/cmd_policy.json',
    mcp_servers_path: 'user/mcp_servers.json',
    local_bridge_enabled: true,
    local_bridge_host: DEFAULT_DESKTOP_BRIDGE_HOST,
    local_bridge_port: DEFAULT_DESKTOP_BRIDGE_PORT,
  })
  maybeMigrateDefaultCoreUrlFromTemplate(getDesktopConfigPath(), path.join(templateUserDir, 'desktop_client.json'), templateEnvPath)
}

async function fetchDesktopBackendStatus(timeoutMs: number) {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), Math.max(50, timeoutMs))
  try {
    const response = await fetch(`${desktopBridgeBaseUrl}${DESKTOP_BRIDGE_STATUS_PATH}`, {
      signal: controller.signal,
    })
    if (!response.ok) {
      return null
    }
    const payload = await response.json().catch(() => null)
    return payload && typeof payload === 'object' && !Array.isArray(payload)
      ? payload as DesktopBackendStatusPayload
      : {}
  } catch {
    return null
  } finally {
    clearTimeout(timeoutId)
  }
}

async function waitForDesktopBackend(timeoutMs = DESKTOP_BACKEND_READY_TIMEOUT_MS) {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    const status = await fetchDesktopBackendStatus(1000)
    if (status) {
      return status
    }
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  return null
}

async function ensureDesktopBackendStarted() {
  ensurePackagedRuntimeFiles()
  setDesktopBridgeBaseUrl(resolveDesktopBridgeBaseUrl())
  const existingStatus = await waitForDesktopBackend(500)
  if (existingStatus && !app.isPackaged && isDesktopBackendBuildAligned(existingStatus)) {
    desktopBridgeAccessToken = ''
    return
  }
  if (existingStatus) {
    const actualCommit = desktopBackendGitCommit(existingStatus) || 'unknown'
    const expectedCommit = expectedUiGitCommit() || 'unknown'
    await moveDesktopBridgeToAvailablePort(`existing bridge is not owned by this process (ui=${expectedCommit}, backend=${actualCommit})`)
  } else {
    try {
      await ensureDesktopBridgeAddressAvailable()
    } catch (error) {
      console.warn(`[desktop-backend] failed to probe local bridge port: ${error instanceof Error ? error.message : String(error)}`)
    }
  }
  if (desktopBackendProcess && desktopBackendProcess.exitCode == null) {
    return
  }
  if (app.isPackaged) {
    const backendExecutable = resolvePackagedBackendExecutable()
    if (!fs.existsSync(backendExecutable)) {
      const message = `Packaged desktop backend executable not found: ${backendExecutable}. Rebuild the installer with npm run build so resources/desktop-backend is included.`
      console.warn(`[desktop-backend] ${message}`)
      dialog.showErrorBox('MeetYou desktop backend missing', message)
      return
    }
    desktopBridgeAccessToken = crypto.randomBytes(24).toString('hex')
    const runtimeRoot = getDesktopRuntimeRoot()
    const runtimeEnvOverrides = readEnvFileValues(path.join(runtimeRoot, '.env'))
    desktopBackendProcess = spawn(backendExecutable, [], {
      cwd: runtimeRoot,
      env: {
        ...process.env,
        ...runtimeEnvOverrides,
        MEETYOU_DESKTOP_LOCAL_TOKEN: desktopBridgeAccessToken,
        MEETYOU_DESKTOP_CLIENT_CONFIG: getDesktopConfigPath(),
      },
      stdio: 'ignore',
      windowsHide: true,
    })
    desktopBackendProcess.once('error', (error) => {
      console.warn(`[desktop-backend] failed to start packaged backend: ${error.message}`)
      desktopBackendProcess = null
      desktopBridgeAccessToken = ''
    })
    desktopBackendProcess.once('exit', (code, signal) => {
      console.warn(`[desktop-backend] packaged backend exited code=${String(code)} signal=${String(signal)}`)
      desktopBackendProcess = null
      desktopBridgeAccessToken = ''
    })
    const ready = await waitForDesktopBackend()
    if (!ready) {
      console.warn('[desktop-backend] packaged bridge did not become ready before timeout')
    }
    return
  }
  const mainPy = resolveWorkspaceMainPy()
  if (!fs.existsSync(mainPy)) {
    console.warn(`[desktop-backend] main.py not found: ${mainPy}`)
    return
  }
  desktopBridgeAccessToken = crypto.randomBytes(24).toString('hex')
  desktopBackendProcess = spawn(resolveWorkspacePython(), [mainPy, 'desktop-client'], {
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
  const envPath = path.join(getDesktopRuntimeRoot(), '.env')
  const values = readEnvFileValues(envPath, envNames)
  for (const envName of envNames) {
    const value = String(values[envName as keyof RuntimeEnvValues] || '').trim()
    if (value) {
      return value
    }
  }
  return ''
}

function readGatewayAccessToken(): string {
  return readWorkspaceEnvValue(['MEETYOU_GATEWAY_ACCESS_TOKEN'])
}

function resolveCredentialSecret(): string {
  return readWorkspaceEnvValue([
    'MEETYOU_CREDENTIAL_SECRET',
    'MEETYOU_GATEWAY_ACCESS_TOKEN',
    'MEETYOU_CLIENT_ACCESS_TOKEN',
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

function isDanxiAuthCaptureReady(currentUrl: string) {
  if (!currentUrl) {
    return false
  }
  try {
    const parsed = new URL(currentUrl)
    if (parsed.hostname !== DANXI_WEBVPN_HOST) {
      return false
    }
    return parsed.pathname !== '/login'
  } catch {
    return false
  }
}

async function tryResolveDanxiAuth(windowRef: BrowserWindow | null) {
  if (!windowRef || !danxiAuthResolver) {
    return false
  }
  const currentUrl = windowRef.webContents.getURL() || ''
  if (!isDanxiAuthCaptureReady(currentUrl)) {
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
    runtimeDebugWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.runtimeDebug.slice(1) })
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

  const windowWidth = 560
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
    settingsWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.settings.slice(1) })
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

  const windowWidth = 1180
  const windowHeight = 760

  workspaceWin = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width / 2 - windowWidth / 2,
    y: height / 2 - windowHeight / 2,
    icon: path.join(process.env.VITE_PUBLIC || '', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
    transparent: true,
    frame: false,
    resizable: true,
    minWidth: 900,
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
    workspaceWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.workspace.slice(1) })
  }

  workspaceWin.on('closed', () => {
    workspaceWin = null
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
    danxiWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.danxi.slice(1) })
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
    backgroundColor: '#ffffff',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      partition: DANXI_AUTH_WINDOW_PARTITION,
    },
  })
  danxiAuthWin.show()
  danxiAuthWin.focus()

  danxiAuthWin.webContents.setUserAgent(DANXI_AUTH_USER_AGENT)
  danxiAuthWin.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL, isMainFrame) => {
    console.warn(
      `[danxi-auth] did-fail-load code=${String(errorCode)} mainFrame=${String(isMainFrame)} url=${validatedURL} error=${errorDescription}`,
    )
  })
  danxiAuthWin.webContents.on('render-process-gone', (_event, details) => {
    console.warn(`[danxi-auth] render-process-gone reason=${details.reason} exitCode=${String(details.exitCode)}`)
  })
  danxiAuthWin.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    if (level >= 2) {
      console.warn(`[danxi-auth] console level=${String(level)} line=${String(line)} source=${sourceId} message=${message}`)
    }
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
    contextWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.context.slice(1) })
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

  const windowWidth = 840
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
    dashboardWin.loadFile(path.join(process.env.DIST || '', 'index.html'), { hash: WINDOW_HASH_ROUTE.dashboard.slice(1) })
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
  ipcMain.handle('get-gateway-access-token', () => readGatewayAccessToken())
  ipcMain.removeHandler('select-local-directories')
  ipcMain.handle('select-local-directories', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openDirectory', 'multiSelections', 'createDirectory'],
    })
    return {
      canceled: result.canceled,
      paths: result.filePaths.map((item) => path.resolve(item)),
    }
  })
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
