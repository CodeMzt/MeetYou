const fs = require('fs')
const http = require('http')
const path = require('path')
const { spawn, spawnSync } = require('child_process')
const { app, BrowserWindow } = require('electron')

const appRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(appRoot, '..')
const port = Number(process.env.MEETYOU_VISUAL_PORT || 5173)
const mockBridgeUrl = process.env.MEETYOU_VISUAL_MOCK_BASE_URL || 'http://127.0.0.1:38981'
const visualUrl = process.env.MEETYOU_VISUAL_URL || `http://127.0.0.1:${port}/#/workspace`
const outputDir = process.env.MEETYOU_VISUAL_OUTPUT_DIR || path.join(repoRoot, 'docs', '_local', 'workspace-topology-visual')
const sizes = [
  { name: 'workspace-topology-wide', width: 1180, height: 760 },
  { name: 'workspace-topology-compact', width: 900, height: 640 },
]
const states = [
  {
    name: 'overview',
    visibleTexts: ['工作区', 'Endpoint Topology', 'Core', 'Desktop Main', '个人工作区'],
    script: 'window.scrollTo(0, 0)',
  },
  {
    name: 'endpoint-selected',
    minWidth: 1081,
    visibleTexts: ['Desktop Main', '工作区归属', 'CAPABILITIES', 'ENDPOINTADDRESS'],
    script: `
      (() => {
        const button = Array.from(document.querySelectorAll('button')).find((item) => item.innerText.includes('Desktop Main'))
        if (button) button.click()
      })()
    `,
  },
]

const topologyPayload = {
  workspaces: [
    {
      workspace_id: 'personal',
      title: '个人工作区',
      status: 'active',
      base_mode: 'general',
      description: '本机默认运行边界',
      endpoint_count: 2,
      online_endpoint_count: 1,
    },
    {
      workspace_id: 'study',
      title: '学习研究',
      status: 'active',
      base_mode: 'automation',
      description: '课程、论文和资料整理',
      endpoint_count: 1,
      online_endpoint_count: 1,
    },
    {
      workspace_id: 'archive-lab',
      title: '归档实验',
      status: 'archived',
      base_mode: 'general',
      description: '隐藏但可恢复的工作区',
      endpoint_count: 0,
      online_endpoint_count: 0,
    },
  ],
  endpoints: [
    {
      endpoint_id: 'desktop.main.executor',
      display_name: 'Desktop Main',
      endpoint_type: 'desktop_executor',
      provider_type: 'desktop',
      transport_type: 'websocket',
      status: 'online',
      connected: true,
      connection_count: 1,
      workspace_ids: ['personal', 'study'],
      primary_workspace_id: 'personal',
      provider_declared_workspace_ids: ['personal'],
      capability_count: 3,
      executable_tools: ['shell.exec', 'filesystem.read', 'desktop.notify'],
      labels: ['local_tools'],
      last_seen_at: '2026-05-05T00:00:00Z',
      core_owned: false,
      memberships: [
        { workspace_id: 'personal', primary: true, role: 'member', enabled: true, source: 'core' },
        { workspace_id: 'study', primary: false, role: 'member', enabled: true, source: 'core' },
      ],
    },
    {
      endpoint_id: 'core.local',
      display_name: 'Core Local',
      endpoint_type: 'core_local',
      provider_type: 'core',
      transport_type: 'inproc',
      status: 'offline',
      connected: false,
      connection_count: 0,
      workspace_ids: ['personal'],
      primary_workspace_id: 'personal',
      provider_declared_workspace_ids: [],
      capability_count: 1,
      executable_tools: ['core.workflow.scheduled_workflow'],
      labels: ['core'],
      last_seen_at: '',
      core_owned: true,
      memberships: [{ workspace_id: 'personal', primary: true, role: 'member', enabled: true, source: 'core' }],
    },
  ],
  addresses: [
    {
      address_id: 'addr.desktop.direct.self',
      endpoint_id: 'desktop.main.executor',
      display_name: 'Desktop Direct',
      provider_type: 'desktop',
      address_type: 'direct',
      status: 'sendable',
      workspace_ids: ['personal'],
      primary_workspace_id: 'personal',
      capabilities: ['delivery.notice'],
      memberships: [{ workspace_id: 'personal', primary: true, role: 'member', enabled: true, source: 'core' }],
    },
  ],
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function jsonResponse(response, statusCode, payload) {
  response.writeHead(statusCode, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS',
    'Content-Type': 'application/json',
  })
  response.end(JSON.stringify(payload))
}

function startMockBridge() {
  const url = new URL(mockBridgeUrl)
  const server = http.createServer((request, response) => {
    if (request.method === 'OPTIONS') {
      jsonResponse(response, 200, { ok: true })
      return
    }
    if (request.url && request.url.startsWith('/desktop/workspace-topology')) {
      jsonResponse(response, 200, topologyPayload)
      return
    }
    if (request.url && request.url.startsWith('/desktop/workspaces')) {
      jsonResponse(response, 200, {
        workspace_id: 'personal',
        title: '个人工作区',
        status: 'active',
        base_mode: 'general',
        description: '本机默认运行边界',
        prompt_overlay: '',
        default_execution_target: 'core.local',
        tool_policy: 'allow_all',
        allowed_tool_ids: [],
        preferred_target_endpoint_ids: [],
        preferred_endpoint_provider_types: [],
        preferred_source_profiles: [],
        tool_target_routing_policy: 'balanced',
        memory_ranking_policy: 'workspace_first',
        tool_routing_overrides: {},
      })
      return
    }
    jsonResponse(response, 404, { detail: 'not found' })
  })
  return new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(Number(url.port), url.hostname, () => resolve(server))
  })
}

function waitForHttp(url, timeoutMs = 30000) {
  const startedAt = Date.now()
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const request = http.get(url, (response) => {
        response.resume()
        if (response.statusCode && response.statusCode < 500) {
          resolve()
          return
        }
        retry()
      })
      request.on('error', retry)
      request.setTimeout(3000, () => {
        request.destroy()
        retry()
      })
    }
    const retry = () => {
      if (Date.now() - startedAt > timeoutMs) {
        reject(new Error(`Timed out waiting for ${url}`))
        return
      }
      setTimeout(attempt, 500)
    }
    attempt()
  })
}

function startVite() {
  const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm'
  const child = spawn(
    npmCommand,
    ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(port), '--strictPort'],
    {
      cwd: appRoot,
      env: { ...process.env, BROWSER: 'none', MEETYOU_VISUAL_MOCK_BASE_URL: mockBridgeUrl },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    },
  )
  child.stdout.on('data', (chunk) => process.stdout.write(chunk))
  child.stderr.on('data', (chunk) => process.stderr.write(chunk))
  return child
}

function killProcessTree(child) {
  if (!child || child.killed || !child.pid) {
    return
  }
  if (process.platform !== 'win32') {
    child.kill('SIGTERM')
    return
  }
  spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], {
    stdio: 'ignore',
    windowsHide: true,
  })
}

async function waitForText(win, expectedText, timeoutMs = 15000) {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    const found = await win.webContents.executeJavaScript(
      `document.body && document.body.innerText.includes(${JSON.stringify(expectedText)})`,
    )
    if (found) {
      return
    }
    await wait(250)
  }
  throw new Error(`Timed out waiting for text: ${expectedText}`)
}

async function collectLayoutReport(win, size, state) {
  return win.webContents.executeJavaScript(`
(() => {
  const requiredTexts = ['工作区', 'Endpoint Topology', 'Core', 'Desktop Main']
  const requiredVisibleTexts = ${JSON.stringify(state.visibleTexts)}
  const bodyText = document.body.innerText || ''
  const missingTexts = requiredTexts.filter((text) => !bodyText.includes(text))
  const bodyOverflowX = document.documentElement.scrollWidth - window.innerWidth
  const visibleElements = Array.from(document.querySelectorAll('body *')).filter((element) => {
    const style = window.getComputedStyle(element)
    const rect = element.getBoundingClientRect()
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
  })
  const horizontalOverflowElements = visibleElements
    .filter((element) => {
      if (element.closest('[class*="boardScroll"]')) return false
      const rect = element.getBoundingClientRect()
      return rect.left < -1 || rect.right > window.innerWidth + 1
    })
    .slice(0, 12)
    .map((element) => {
      const rect = element.getBoundingClientRect()
      return {
        tag: element.tagName.toLowerCase(),
        className: String(element.className || ''),
        text: String(element.innerText || element.textContent || '').trim().slice(0, 80),
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
      }
    })
  const controls = Array.from(document.querySelectorAll('button, select, textarea, input'))
  const clippedControls = controls
    .filter((element) => {
      if (element.closest('[class*="boardScroll"]')) return false
      const style = window.getComputedStyle(element)
      const rect = element.getBoundingClientRect()
      if (style.display === 'none' || style.visibility === 'hidden' || rect.width === 0 || rect.height === 0) return false
      return rect.width < 16 || rect.height < 14 || rect.left < -1 || rect.right > window.innerWidth + 1
    })
    .map((element) => {
      const rect = element.getBoundingClientRect()
      return {
        tag: element.tagName.toLowerCase(),
        text: String(element.innerText || element.value || '').trim().slice(0, 80),
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      }
    })
  const visibleTextMissing = requiredVisibleTexts.filter((text) => {
    return !visibleElements.some((element) => {
      const rect = element.getBoundingClientRect()
      const value = String(element.innerText || element.textContent || '')
      return value.includes(text) && rect.bottom > 0 && rect.top < window.innerHeight
    })
  })
  return {
    name: ${JSON.stringify(size.name)},
    state: ${JSON.stringify(state.name)},
    viewport: { width: window.innerWidth, height: window.innerHeight },
    bodyOverflowX,
    missingTexts,
    visibleTextMissing,
    horizontalOverflowElements,
    clippedControls,
    scrollHeight: document.documentElement.scrollHeight,
  }
})()
`)
}

async function runVisualCheck() {
  fs.mkdirSync(outputDir, { recursive: true })
  process.env.MEETYOU_VISUAL_MOCK_BASE_URL = mockBridgeUrl
  app.commandLine.appendSwitch('disable-gpu')
  await app.whenReady()

  const win = new BrowserWindow({
    width: sizes[0].width,
    height: sizes[0].height,
    show: false,
    frame: false,
    transparent: true,
    webPreferences: {
      preload: path.join(__dirname, 'workspace-governance-visual-preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  await win.loadURL(visualUrl)
  await waitForText(win, 'Endpoint Topology')
  await waitForText(win, 'Desktop Main')
  const reports = []
  for (const size of sizes) {
    win.setSize(size.width, size.height)
    await wait(500)
    for (const state of states) {
      if (state.minWidth && size.width < state.minWidth) {
        continue
      }
      await win.webContents.executeJavaScript(state.script)
      await wait(350)
      const report = await collectLayoutReport(win, size, state)
      const image = await win.webContents.capturePage()
      const screenshotPath = path.join(outputDir, `${size.name}-${state.name}-${size.width}x${size.height}.png`)
      fs.writeFileSync(screenshotPath, image.toPNG())
      reports.push({ ...report, screenshotPath })
    }
  }

  const reportPath = path.join(outputDir, 'workspace-topology-visual-report.json')
  fs.writeFileSync(reportPath, JSON.stringify({ visualUrl, mockBridgeUrl, reports }, null, 2))
  const failures = reports.flatMap((report) => {
    const items = []
    if (report.missingTexts.length > 0) {
      items.push(`${report.name}: missing text ${report.missingTexts.join(', ')}`)
    }
    if (report.visibleTextMissing.length > 0) {
      items.push(`${report.name}/${report.state}: missing visible text ${report.visibleTextMissing.join(', ')}`)
    }
    if (report.bodyOverflowX > 1 || report.horizontalOverflowElements.length > 0) {
      items.push(`${report.name}: horizontal overflow`)
    }
    if (report.clippedControls.length > 0) {
      items.push(`${report.name}: clipped controls`)
    }
    return items
  })
  console.log(JSON.stringify({ ok: failures.length === 0, reportPath, reports }, null, 2))
  if (failures.length > 0) {
    win.destroy()
    throw new Error(failures.join('; '))
  }
  win.destroy()
}

let viteProcess = null
let mockServer = null

async function main() {
  mockServer = await startMockBridge()
  if (!process.env.MEETYOU_VISUAL_URL) {
    try {
      await waitForHttp(`http://127.0.0.1:${port}/`, 1000)
    } catch {
      viteProcess = startVite()
    }
    await waitForHttp(`http://127.0.0.1:${port}/`)
  }
  try {
    await runVisualCheck()
  } finally {
    killProcessTree(viteProcess)
    if (mockServer) {
      mockServer.close()
    }
    app.exit(0)
  }
}

main().catch((error) => {
  console.error(error)
  killProcessTree(viteProcess)
  if (mockServer) {
    mockServer.close()
  }
  app.exit(1)
})
