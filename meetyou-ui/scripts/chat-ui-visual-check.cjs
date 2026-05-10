const crypto = require('crypto')
const fs = require('fs')
const http = require('http')
const os = require('os')
const path = require('path')
const { spawn, spawnSync } = require('child_process')
const { app, BrowserWindow } = require('electron')

const appRoot = path.resolve(__dirname, '..')
const vitePort = Number(process.env.MEETYOU_CHAT_VISUAL_PORT || 5174)
const visualUrl = process.env.MEETYOU_CHAT_VISUAL_URL || `http://127.0.0.1:${vitePort}/`
const outputDir = process.env.MEETYOU_CHAT_VISUAL_OUTPUT_DIR || path.join(os.tmpdir(), 'meetyou-chat-ui-visual')
const visualUsageReady = process.env.MEETYOU_CHAT_VISUAL_USAGE_READY === 'true'
const wsClients = new Set()
const threadId = 'thread_visual_chat'
const sessionId = 'session_visual_chat'
const workspaceId = 'personal'
const endpointId = 'desktop-app'
const userPrompt = 'Danxi最近人们在哪些话题？'
const assistantAnswer = '这是助手回复第一行。'

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function nowIso() {
  return new Date().toISOString()
}

function usageSnapshot() {
  return {
    session_id: sessionId,
    usage_ready: visualUsageReady,
    context_limit_tokens: 128000,
    context_limit_source: 'visual_fixture',
    context_limit_model: 'gpt-5.4',
    context_limit_confidence: 'high',
    current_context_tokens_estimated: 4096,
    context_breakdown: {
      system: 256,
      history: 2048,
      tool_history: 128,
      context_pool: 128,
      memory_context: 512,
      policy: 64,
      current_input: 512,
      proprioception: 64,
      total: 3712,
    },
    last_turn_usage: {
      prompt_tokens: 1200,
      completion_tokens: 180,
      reasoning_tokens: 60,
      total_tokens: 1440,
    },
    session_totals: {
      prompt_tokens: 1200,
      completion_tokens: 180,
      reasoning_tokens: 60,
      total_tokens: 1440,
      turn_count: 1,
    },
    usage_source: 'visual_fixture',
    updated_at: nowIso(),
  }
}

const workspace = {
  workspace_id: workspaceId,
  title: '个人工作区',
  status: 'active',
  base_mode: 'general',
  description: '用于主窗口视觉验收的工作区。',
  prompt_overlay: '',
  default_execution_target: 'workspace_any_endpoint',
  tool_policy: 'allow_all',
  allowed_tool_ids: [],
  preferred_target_endpoint_ids: [],
  preferred_endpoint_provider_types: ['desktop'],
  preferred_source_profiles: ['workspace_local'],
  tool_target_routing_policy: 'balanced',
  memory_ranking_policy: 'workspace_first',
  tool_routing_overrides: {},
}

const thread = {
  thread_id: threadId,
  home_workspace_id: workspaceId,
  workspace_id: workspaceId,
  title: '桌面聊天',
  status: 'active',
  summary: '',
}

const branch = {
  branch_id: 'branch_visual_default',
  thread_id: threadId,
  parent_branch_id: '',
  title: '主分支',
  status: 'active',
  current_leaf_message_id: '',
  metadata: { is_active: true },
  created_at: nowIso(),
  updated_at: nowIso(),
}

const checkpoint = {
  checkpoint_id: 'checkpoint_visual_auto',
  thread_id: threadId,
  branch_id: branch.branch_id,
  message_id: '',
  checkpoint_type: 'auto',
  title: '自动检查点',
  state: {},
  status: 'active',
  metadata: { automatic: true },
  created_at: nowIso(),
  updated_at: nowIso(),
}

const session = {
  session_id: sessionId,
  thread_id: threadId,
  active_workspace_id: workspaceId,
  workspace_id: workspaceId,
  endpoint_id: endpointId,
  status: 'active',
}

function writeJson(response, payload, statusCode = 200) {
  const body = JSON.stringify(payload)
  response.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'authorization, content-type',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS',
  })
  response.end(body)
}

function readBody(request) {
  return new Promise((resolve) => {
    const chunks = []
    request.on('data', (chunk) => chunks.push(chunk))
    request.on('end', () => {
      const text = Buffer.concat(chunks).toString('utf-8')
      try {
        resolve(text ? JSON.parse(text) : {})
      } catch {
        resolve({})
      }
    })
  })
}

function createWsFrame(payload) {
  const data = Buffer.from(JSON.stringify(payload), 'utf-8')
  if (data.length < 126) {
    return Buffer.concat([Buffer.from([0x81, data.length]), data])
  }
  if (data.length < 65536) {
    const header = Buffer.alloc(4)
    header[0] = 0x81
    header[1] = 126
    header.writeUInt16BE(data.length, 2)
    return Buffer.concat([header, data])
  }
  const header = Buffer.alloc(10)
  header[0] = 0x81
  header[1] = 127
  header.writeBigUInt64BE(BigInt(data.length), 2)
  return Buffer.concat([header, data])
}

function sendWs(payload) {
  const frame = createWsFrame(payload)
  for (const socket of wsClients) {
    if (!socket.destroyed) {
      socket.write(frame)
    }
  }
}

function sendConnectionAck() {
  sendWs({
    schema: 'meetyou.endpoint.ws.v4',
    type: 'endpoint.hello.ack',
    payload: {
      accepted: true,
      target_id: threadId,
      status: 'connected',
    },
  })
  sendWs({
    schema: 'meetyou.endpoint.ws.v4',
    type: 'subscription.ack',
    payload: {
      action: 'start',
      subscription_id: `sub-${threadId}`,
      target_type: 'thread',
      target_id: threadId,
      active: true,
    },
  })
}

function sendAssistantRaceFrames() {
  const streamId = 'stream_visual_chat'
  const turnId = 'turn_visual_chat'
  setTimeout(() => {
    sendWs({
      kind: 'event',
      event: {
        type: 'runtime.state',
        thread_id: threadId,
        session_id: sessionId,
        snapshot: {
          session_id: sessionId,
          status: 'answering',
          detail: '正在回复...',
          active_tools: [],
          current_mode: 'danxi',
          route_reason: '',
          action_risk: 'read',
          source_profile: 'workspace_local',
          stream_id: streamId,
          turn_id: turnId,
          updated_at: nowIso(),
        },
      },
    })
  }, 20)
  setTimeout(() => {
    sendWs({
      kind: 'event',
      event: {
        type: 'message.delta',
        thread_id: threadId,
        session_id: sessionId,
        stream_id: streamId,
        turn_id: turnId,
        delta: `\n\n${assistantAnswer}`,
      },
    })
  }, 45)
  setTimeout(() => {
    sendWs({
      kind: 'event',
      event: {
        type: 'message.completed',
        thread_id: threadId,
        session_id: sessionId,
        stream_id: streamId,
        turn_id: turnId,
        message: {
          message_id: 'msg_visual_assistant',
          thread_id: threadId,
          session_id: sessionId,
          active_workspace_id: workspaceId,
          workspace_id: workspaceId,
          endpoint_id: '',
          role: 'assistant',
          content: `\n\n${assistantAnswer}\n\n`,
          status: 'completed',
          channel: 'message',
          created_at: nowIso(),
        },
      },
    })
  }, 95)
  setTimeout(() => {
    sendWs({
      kind: 'event',
      event: {
        type: 'runtime.state',
        thread_id: threadId,
        session_id: sessionId,
        snapshot: {
          session_id: sessionId,
          status: 'idle',
          detail: '',
          active_tools: [],
          current_mode: 'danxi',
          route_reason: '',
          action_risk: 'read',
          source_profile: 'workspace_local',
          stream_id: streamId,
          turn_id: turnId,
          updated_at: nowIso(),
        },
      },
    })
  }, 130)
}

async function handleRequest(request, response) {
  const url = new URL(request.url, 'http://127.0.0.1')
  if (request.method === 'OPTIONS') {
    writeJson(response, {})
    return
  }
  if (request.method === 'GET' && url.pathname === '/desktop/workspaces') {
    writeJson(response, [workspace])
    return
  }
  if (request.method === 'GET' && url.pathname === '/desktop/projects') {
    writeJson(response, [])
    return
  }
  if (request.method === 'POST' && url.pathname === '/desktop/threads/default') {
    writeJson(response, thread)
    return
  }
  if (request.method === 'GET' && url.pathname === '/desktop/threads') {
    writeJson(response, [thread])
    return
  }
  if (request.method === 'GET' && url.pathname === `/desktop/threads/${threadId}/branches`) {
    writeJson(response, [branch])
    return
  }
  if (request.method === 'GET' && url.pathname === `/desktop/threads/${threadId}/checkpoints`) {
    writeJson(response, [checkpoint])
    return
  }
  if (request.method === 'POST' && url.pathname === `/desktop/threads/${threadId}/checkpoints`) {
    writeJson(response, checkpoint)
    return
  }
  if (request.method === 'GET' && url.pathname === '/desktop/research-tasks') {
    writeJson(response, [])
    return
  }
  if (request.method === 'POST' && url.pathname === '/desktop/sessions') {
    writeJson(response, session)
    return
  }
  if (request.method === 'GET' && url.pathname === `/desktop/threads/${threadId}/messages`) {
    writeJson(response, [])
    return
  }
  if (request.method === 'GET' && url.pathname === `/desktop/workspaces/${workspaceId}/endpoints`) {
    writeJson(response, [
      {
        endpoint_id: endpointId,
        endpoint_type: 'desktop_ui',
        provider_type: 'desktop',
        display_name: '桌面应用',
        transport_profile: 'desktop_ui_bridge',
        status: 'online',
        workspace_ids: [workspaceId],
        available_tools: ['file.read', 'shell.exec'],
        executable_tools: ['file.read', 'shell.exec'],
        membership_role: 'member',
        enabled: true,
      },
    ])
    return
  }
  if (request.method === 'GET' && url.pathname === '/desktop/health') {
    writeJson(response, {
      kind: 'health',
      health: {
        service: 'desktop-visual',
        version: 'visual',
        status: 'ok',
        live: true,
        ready: true,
        degraded: false,
        components: [],
        errors: [],
        updated_at: nowIso(),
      },
    })
    return
  }
  if (request.method === 'GET' && url.pathname === '/desktop/runtime/usage') {
    writeJson(response, {
      kind: 'runtime',
      runtime: {
        resource: 'usage',
        session_id: sessionId,
        usage: usageSnapshot(),
      },
    })
    return
  }
  if (request.method === 'POST' && url.pathname === '/desktop/messages') {
    const payload = await readBody(request)
    sendAssistantRaceFrames()
    setTimeout(() => {
      writeJson(response, {
        message_id: 'msg_visual_user',
        thread_id: threadId,
        session_id: sessionId,
        active_workspace_id: workspaceId,
        workspace_id: workspaceId,
        endpoint_id: endpointId,
        role: 'user',
        content: String(payload.content || userPrompt),
        status: 'completed',
        channel: 'message',
        created_at: nowIso(),
      })
    }, 180)
    return
  }
  writeJson(response, { kind: 'error', error: { code: 'not_found', message: url.pathname } }, 404)
}

function startFixtureServer() {
  const server = http.createServer((request, response) => {
    handleRequest(request, response).catch((error) => {
      writeJson(response, { kind: 'error', error: { code: 'fixture_error', message: error.message } }, 500)
    })
  })
  server.on('upgrade', (request, socket) => {
    const url = new URL(request.url, 'http://127.0.0.1')
    if (url.pathname !== '/desktop/ws') {
      socket.destroy()
      return
    }
    const key = String(request.headers['sec-websocket-key'] || '')
    const accept = crypto
      .createHash('sha1')
      .update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
      .digest('base64')
    socket.write([
      'HTTP/1.1 101 Switching Protocols',
      'Upgrade: websocket',
      'Connection: Upgrade',
      `Sec-WebSocket-Accept: ${accept}`,
      '',
      '',
    ].join('\r\n'))
    wsClients.add(socket)
    socket.on('close', () => wsClients.delete(socket))
    socket.on('error', () => wsClients.delete(socket))
    socket.on('data', () => {})
    setTimeout(sendConnectionAck, 30)
  })
  return new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      resolve({ server, baseUrl: `http://127.0.0.1:${address.port}` })
    })
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
    ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'],
    {
      cwd: appRoot,
      env: { ...process.env, BROWSER: 'none' },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    },
  )
  child.stdout.on('data', (chunk) => process.stdout.write(chunk))
  child.stderr.on('data', (chunk) => process.stderr.write(chunk))
  return child
}

function stopProcessTree(child) {
  if (!child || child.killed) {
    return
  }
  if (process.platform === 'win32' && child.pid) {
    spawnSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], {
      stdio: 'ignore',
      windowsHide: true,
    })
    return
  }
  child.kill()
}

async function waitForCondition(win, expression, label, timeoutMs = 15000) {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    const matched = await win.webContents.executeJavaScript(`Boolean(${expression})`)
    if (matched) {
      return
    }
    await wait(250)
  }
  throw new Error(`Timed out waiting for ${label}`)
}

async function capture(win, name) {
  const image = await win.webContents.capturePage()
  const screenshotPath = path.join(outputDir, `${name}.png`)
  fs.writeFileSync(screenshotPath, image.toPNG())
  return screenshotPath
}

async function collectIslandReport(win) {
  return win.webContents.executeJavaScript(`
(() => new Promise((resolve) => {
  const pill = document.querySelector('[class*="islandPill"]')
  if (!pill) {
    resolve({ ok: false, reason: 'missing-island-pill' })
    return
  }
  pill.click()
  window.setTimeout(() => {
    const dropdown = document.querySelector('[class*="usageDropdown"]')
    if (!dropdown) {
      resolve({ ok: false, reason: 'missing-usage-dropdown' })
      return
    }
    const rect = dropdown.getBoundingClientRect()
    const style = window.getComputedStyle(dropdown)
    resolve({
      ok: true,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      rect: {
        left: Math.round(rect.left),
        top: Math.round(rect.top),
        right: Math.round(rect.right),
        bottom: Math.round(rect.bottom),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      clipped: rect.left < 0 || rect.top < 0 || rect.right > window.innerWidth || rect.bottom > window.innerHeight,
      maxHeight: style.maxHeight,
      overflowY: style.overflowY,
      text: dropdown.innerText,
    })
  }, 260)
}))()
`)
}

async function sendChatPrompt(win) {
  await win.webContents.executeJavaScript(`
(() => {
  const textarea = document.querySelector('textarea')
  if (!textarea) throw new Error('textarea missing')
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set
  setter.call(textarea, ${JSON.stringify(userPrompt)})
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
  textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true }))
})()
`)
}

async function collectChatReport(win) {
  return win.webContents.executeJavaScript(`
(() => {
  const wrappers = Array.from(document.querySelectorAll('[class*="messageWrapper"]'))
  const rows = wrappers.map((element) => ({
    text: String(element.innerText || element.textContent || '').trim(),
    className: String(element.className || ''),
    rect: (() => {
      const rect = element.getBoundingClientRect()
      return { top: Math.round(rect.top), bottom: Math.round(rect.bottom), height: Math.round(rect.height) }
    })(),
  }))
  const userIndex = rows.findIndex((row) => row.text.includes(${JSON.stringify(userPrompt)}))
  const assistantIndex = rows.findIndex((row) => row.text.includes(${JSON.stringify(assistantAnswer)}))
  const container = document.querySelector('[class*="scrollContainer"]')
  const lastMessage = wrappers[wrappers.length - 1] || null
  const children = container ? Array.from(container.children).filter((element) => {
    const style = window.getComputedStyle(element)
    const rect = element.getBoundingClientRect()
    return style.display !== 'none' && rect.height > 0
  }) : []
  const lastChild = children[children.length - 1] || null
  const lastMessageChildIndex = lastMessage ? children.indexOf(lastMessage) : -1
  const trailingChildCount = lastMessageChildIndex >= 0 ? children.length - lastMessageChildIndex - 1 : -1
  const assistantWrapper = assistantIndex >= 0 ? wrappers[assistantIndex] : null
  const assistantBubble = assistantWrapper?.querySelector('[class*="messageInner"]') || null
  const paragraph = assistantWrapper?.querySelector('[class*="markdownBody"] p') || null
  const paragraphMarginBottom = paragraph ? window.getComputedStyle(paragraph).marginBottom : ''
  const textNode = paragraph ? Array.from(paragraph.childNodes).find((node) => node.nodeType === Node.TEXT_NODE && String(node.textContent || '').trim()) : null
  let assistantBottomGap = -1
  if (assistantBubble && textNode) {
    const range = document.createRange()
    range.selectNodeContents(textNode)
    const textRects = Array.from(range.getClientRects())
    range.detach()
    const lastTextRect = textRects[textRects.length - 1]
    const bubbleRect = assistantBubble.getBoundingClientRect()
    if (lastTextRect) {
      assistantBottomGap = Math.round(bubbleRect.bottom - lastTextRect.bottom)
    }
  }
  return {
    rows,
    userIndex,
    assistantIndex,
    orderOk: userIndex !== -1 && assistantIndex !== -1 && userIndex < assistantIndex,
    lastChildClassName: String(lastChild?.className || ''),
    lastChildIsMessage: Boolean(lastChild && String(lastChild.className || '').includes('messageWrapper')),
    trailingChildCount,
    paragraphMarginBottom,
    assistantBottomGap,
    bodyText: document.body.innerText,
  }
})()
`)
}

async function collectTopControlsReport(win) {
  return win.webContents.executeJavaScript(`
(() => {
  const titlebar = document.querySelector('[class*="titlebar"]')
  const topDock = document.querySelector('[class*="topDock"]')
  const tools = Array.from(document.querySelectorAll('[data-titlebar-tool]')).map((element) => {
    const rect = element.getBoundingClientRect()
    const style = window.getComputedStyle(element)
    return {
      key: element.getAttribute('data-titlebar-tool'),
      title: element.getAttribute('title'),
      display: style.display,
      visible: style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0,
      rect: {
        left: Math.round(rect.left),
        top: Math.round(rect.top),
        right: Math.round(rect.right),
        bottom: Math.round(rect.bottom),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
    }
  })
  const dockControls = [
    '[data-project-picker-trigger="true"]',
    '[data-thread-picker-trigger="true"]',
    '[data-version-control-trigger="true"]',
    '[data-project-sources-trigger="true"]',
    '[data-project-artifacts-trigger="true"]',
  ].map((selector) => {
    const element = document.querySelector(selector)
    if (!element) {
      return { selector, visible: false, rect: null }
    }
    const rect = element.getBoundingClientRect()
    const style = window.getComputedStyle(element)
    return {
      selector,
      visible: style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0,
      rect: {
        left: Math.round(rect.left),
        top: Math.round(rect.top),
        right: Math.round(rect.right),
        bottom: Math.round(rect.bottom),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
    }
  })
  const titlebarRect = titlebar ? titlebar.getBoundingClientRect() : null
  const topDockRect = topDock ? topDock.getBoundingClientRect() : null
  const dockTops = dockControls
    .filter((item) => item.visible && item.rect)
    .map((item) => item.rect.top)
  const uniqueDockTops = Array.from(new Set(dockTops))
  return {
    viewport: { width: window.innerWidth, height: window.innerHeight },
    titlebar: titlebarRect ? {
      left: Math.round(titlebarRect.left),
      top: Math.round(titlebarRect.top),
      right: Math.round(titlebarRect.right),
      bottom: Math.round(titlebarRect.bottom),
      width: Math.round(titlebarRect.width),
      height: Math.round(titlebarRect.height),
    } : null,
    topDock: topDockRect ? {
      left: Math.round(topDockRect.left),
      top: Math.round(topDockRect.top),
      right: Math.round(topDockRect.right),
      bottom: Math.round(topDockRect.bottom),
      width: Math.round(topDockRect.width),
      height: Math.round(topDockRect.height),
    } : null,
    tools,
    dockControls,
    titlebarToolKeys: tools.map((item) => item.key),
    visibleTitlebarToolKeys: tools.filter((item) => item.visible).map((item) => item.key),
    dockOneRow: uniqueDockTops.length <= 1,
    dockOverlapsTitlebar: Boolean(titlebarRect && topDockRect && topDockRect.top < titlebarRect.bottom),
    compactToolsTriggerPresent: Boolean(document.querySelector('[data-titlebar-tools-trigger="true"]')),
    bodyText: document.body.innerText,
  }
})()
`)
}

async function runVisualCheck(apiBaseUrl) {
  fs.mkdirSync(outputDir, { recursive: true })
  app.commandLine.appendSwitch('disable-gpu')
  process.env.MEETYOU_CHAT_VISUAL_API_BASE_URL = apiBaseUrl
  await app.whenReady()

  const win = new BrowserWindow({
    width: 400,
    height: 620,
    show: false,
    frame: false,
    transparent: true,
    webPreferences: {
      preload: path.join(__dirname, 'chat-ui-visual-preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  await win.loadURL(visualUrl)
  win.showInactive()
  await waitForCondition(win, "document.body.innerText.includes('个人工作区')", 'workspace shell')
  await waitForCondition(win, "document.body.innerText.includes('随时可以开始对话')", 'connected empty state')
  await waitForCondition(win, "document.querySelector('textarea') && !document.querySelector('textarea').disabled", 'enabled chat input')
  await wait(500)
  const topControlsReport = await collectTopControlsReport(win)
  const topControlsScreenshot = await capture(win, 'main-top-controls-400x620')

  win.setSize(540, 620)
  await wait(500)
  const islandReport = await collectIslandReport(win)
  await wait(1000)
  const islandScreenshot = await capture(win, 'main-island-open-540x620')

  await win.webContents.executeJavaScript(`
(() => {
  document.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: 1, clientY: 1 }))
})()
`)
  await waitForCondition(win, "!document.querySelector('[class*=\"usageDropdown\"]')", 'closed island dropdown')
  win.setSize(400, 620)
  await wait(300)
  await sendChatPrompt(win)
  await waitForCondition(win, `document.body.innerText.includes(${JSON.stringify(assistantAnswer)})`, 'assistant answer')
  await wait(500)
  const chatReport = await collectChatReport(win)
  const chatScreenshot = await capture(win, 'main-chat-after-send-400x620')

  const report = {
    visualUrl,
    apiBaseUrl,
    visualUsageReady,
    topControlsReport,
    islandReport,
    chatReport,
    screenshots: {
      topControls: topControlsScreenshot,
      island: islandScreenshot,
      chat: chatScreenshot,
    },
  }
  const reportPath = path.join(outputDir, 'chat-ui-visual-report.json')
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2))

  const failures = []
  const expectedTitlebarTools = ['pin', 'dashboard', 'workspace', 'danxi', 'stats', 'devtools', 'settings']
  for (const key of expectedTitlebarTools) {
    if (!topControlsReport.visibleTitlebarToolKeys.includes(key)) {
      failures.push(`titlebar tool ${key} is not visible at 400x620`)
    }
  }
  if (topControlsReport.compactToolsTriggerPresent) {
    failures.push('titlebar still uses compact tools trigger at 400x620')
  }
  if (topControlsReport.dockOverlapsTitlebar) {
    failures.push('V5 top dock overlaps the original titlebar')
  }
  if (!topControlsReport.dockOneRow) {
    failures.push('V5 top dock wrapped onto multiple rows')
  }
  for (const item of topControlsReport.dockControls) {
    if (!item.visible) {
      failures.push(`V5 dock control ${item.selector} is not visible at 400x620`)
    }
  }
  if (!islandReport.ok) {
    failures.push(`island dropdown failed: ${islandReport.reason}`)
  } else {
    if (islandReport.clipped) {
      failures.push('island dropdown is clipped by the window')
    }
    if (!islandReport.text.includes('上下文') && !islandReport.text.includes('占用')) {
      failures.push('island dropdown did not render context usage copy')
    }
    if (!visualUsageReady && !islandReport.text.includes('同步')) {
      failures.push('island dropdown did not show the pending usage state')
    }
  }
  if (!chatReport.orderOk) {
    failures.push(`message order invalid: userIndex=${chatReport.userIndex} assistantIndex=${chatReport.assistantIndex}`)
  }
  if (!chatReport.lastChildIsMessage) {
    failures.push(`scroll container has a trailing non-message child: ${chatReport.lastChildClassName}`)
  }
  if (chatReport.trailingChildCount > 0) {
    failures.push(`message list has ${chatReport.trailingChildCount} trailing rendered child nodes after the last message`)
  }
  if (chatReport.paragraphMarginBottom !== '0px') {
    failures.push(`single-paragraph assistant reply has bottom margin ${chatReport.paragraphMarginBottom}`)
  }
  if (chatReport.assistantBottomGap < 0 || chatReport.assistantBottomGap > 22) {
    failures.push(`assistant reply bottom gap is ${chatReport.assistantBottomGap}px, expected padding-only spacing`)
  }

  console.log(JSON.stringify({ ok: failures.length === 0, reportPath, report }, null, 2))
  if (failures.length > 0) {
    throw new Error(failures.join('; '))
  }
  return report
}

let viteProcess = null
let fixtureServer = null

async function main() {
  const fixture = await startFixtureServer()
  fixtureServer = fixture.server
  if (!process.env.MEETYOU_CHAT_VISUAL_URL) {
    try {
      await waitForHttp(`http://127.0.0.1:${vitePort}/`, 1000)
    } catch {
      viteProcess = startVite()
    }
    await waitForHttp(`http://127.0.0.1:${vitePort}/`)
  }
  try {
    await runVisualCheck(fixture.baseUrl)
  } finally {
    stopProcessTree(viteProcess)
    if (fixtureServer) {
      fixtureServer.close()
    }
    for (const socket of wsClients) {
      socket.destroy()
    }
    app.exit(0)
    process.exit(0)
  }
}

main().catch((error) => {
  console.error(error)
  stopProcessTree(viteProcess)
  if (fixtureServer) {
    fixtureServer.close()
  }
  for (const socket of wsClients) {
    socket.destroy()
  }
  app.exit(1)
  process.exit(1)
})
