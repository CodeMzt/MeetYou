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
const projectId = 'project_visual_v5'
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

const project = {
  project_id: projectId,
  workspace_id: workspaceId,
  title: 'V5 可视项目',
  description: '用于 400x620 项目源验收',
  instructions: '项目源必须来自 Core。',
  status: 'active',
  memory_scope: {},
  metadata: {},
  created_at: nowIso(),
  updated_at: nowIso(),
}

const projectSources = [
  {
    source_id: 'src_visual_existing',
    project_id: projectId,
    source_type: 'message_snapshot',
    title: '已保存消息',
    content: '这是一条已有项目源，用来验证列表和预览。',
    content_type: 'text',
    checksum: 'sha256:visual-existing',
    status: 'active',
    metadata: { message_id: 'msg_visual_existing' },
    created_at: nowIso(),
    updated_at: nowIso(),
  },
]

const thread = {
  thread_id: threadId,
  home_workspace_id: workspaceId,
  workspace_id: workspaceId,
  project_id: projectId,
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

const checkpoints = []

function ensureCheckpoint(messageId, title) {
  if (!messageId || checkpoints.some((item) => item.message_id === messageId)) {
    return
  }
  branch.current_leaf_message_id = messageId
  checkpoints.push({
    checkpoint_id: `checkpoint_visual_${messageId}`,
    thread_id: threadId,
    branch_id: branch.branch_id,
    message_id: messageId,
    checkpoint_type: 'auto',
    title,
    state: { message_id: messageId },
    status: 'active',
    metadata: { automatic: true },
    created_at: nowIso(),
    updated_at: nowIso(),
  })
}

const researchTask = {
  research_task_id: 'res_visual_audit',
  project_id: projectId,
  thread_id: threadId,
  run_id: '',
  artifact_id: '',
  topic: '证据审计可视化',
  status: 'running',
  plan: {
    schema: 'meetyou.research.plan.v1',
    language: 'zh-CN',
    steps: [
      { id: 'plan_review', title: '确认研究计划', status: 'completed', requires_user_confirmation: true },
      { id: 'gather', title: '收集证据', status: 'completed' },
      { id: 'synthesize', title: '综合报告', status: 'completed' },
    ],
  },
  source_policy: {},
  evidence_ledger: [
    {
      source_id: '1',
      rank: 1,
      quality_score: 88.5,
      duplicate_count: 2,
      merged_source_ids: ['4', '1'],
      title: 'Conversation branch evidence',
      source_type: 'project_source',
      url: 'https://example.test/evidence',
      verification_status: 'project_source_snapshot',
      source_trust: 'untrusted',
    },
  ],
  output_format: 'markdown',
  summary: 'GPT Researcher 正在搜索和阅读资料。',
  artifact: null,
  derived_artifacts: [],
  metadata: {
    research_provider: 'gpt_researcher',
    external_run_id: 'rad_visual_research',
    adapter_status: 'running',
    adapter_source_count: 1,
    progress: {
      stage: 'gather',
      status: 'running',
      message: 'GPT Researcher 正在搜索和阅读资料。',
      at: nowIso(),
      research_provider: 'gpt_researcher',
      external_run_id: 'rad_visual_research',
      adapter_status: 'running',
      adapter_source_count: 1,
    },
    progress_events: [
      { stage: 'queued', status: 'running', message: '研究任务已进入外部服务队列。', at: nowIso() },
      { stage: 'gather', status: 'running', message: 'GPT Researcher 正在搜索和阅读资料。', at: nowIso() },
    ],
  },
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
    ensureCheckpoint('msg_visual_assistant', '自动检查点：助手消息')
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
    writeJson(response, [project])
    return
  }
  if (request.method === 'GET' && url.pathname === `/desktop/projects/${projectId}/sources`) {
    const includeArchived = url.searchParams.get('include_archived') === 'true'
    writeJson(response, includeArchived ? projectSources : projectSources.filter((source) => source.status !== 'archived'))
    return
  }
  if (request.method === 'POST' && url.pathname === `/desktop/projects/${projectId}/sources`) {
    const body = await readBody(request)
    const content = String(body.content || '').trim()
    const title = String(body.title || '').trim() || `项目源 ${projectSources.length + 1}`
    const source = {
      source_id: `src_visual_note_${projectSources.length + 1}`,
      project_id: projectId,
      source_type: String(body.source_type || 'note'),
      title,
      content,
      content_type: String(body.content_type || 'text'),
      checksum: 'sha256:visual-note',
      status: 'active',
      metadata: body.metadata || {},
      created_at: nowIso(),
      updated_at: nowIso(),
    }
    projectSources.unshift(source)
    writeJson(response, source)
    return
  }
  if (request.method === 'DELETE' && url.pathname.startsWith(`/desktop/projects/${projectId}/sources/`)) {
    const sourceId = decodeURIComponent(url.pathname.slice(`/desktop/projects/${projectId}/sources/`.length))
    const source = projectSources.find((item) => item.source_id === sourceId)
    if (!source) {
      writeJson(response, { kind: 'error', error: { code: 'project_source_not_found', message: sourceId } }, 404)
      return
    }
    source.status = 'archived'
    source.updated_at = nowIso()
    writeJson(response, source)
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
    writeJson(response, checkpoints)
    return
  }
  if (request.method === 'POST' && url.pathname === `/desktop/threads/${threadId}/checkpoints`) {
    ensureCheckpoint(branch.current_leaf_message_id || 'msg_visual_manual', '手动检查点')
    writeJson(response, checkpoints[checkpoints.length - 1])
    return
  }
  if (request.method === 'GET' && url.pathname === '/desktop/research-tasks') {
    writeJson(response, [researchTask])
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
      ensureCheckpoint('msg_visual_user', '自动检查点：用户消息')
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

async function selectVisualProject(win) {
  await win.webContents.executeJavaScript(`
(() => {
  const trigger = document.querySelector('[data-project-picker-trigger="true"]')
  if (!trigger) throw new Error('project picker trigger missing')
  trigger.click()
})()
`)
  await waitForCondition(win, `document.querySelector('[data-project-option-id="${projectId}"]')`, 'visual project option')
  await win.webContents.executeJavaScript(`
(() => {
  const option = document.querySelector('[data-project-option-id="${projectId}"]')
  if (!option) throw new Error('visual project option missing')
  option.click()
})()
`)
  await waitForCondition(win, "!document.querySelector('[data-project-sources-trigger=\"true\"]')?.disabled", 'project sources trigger enabled')
}

async function createProjectSourceNote(win) {
  const sourceTitle = '视觉项目笔记'
  const sourceContent = '这是 400x620 验收中新建的项目源。'
  await win.webContents.executeJavaScript(`
(() => {
  const trigger = document.querySelector('[data-project-sources-trigger="true"]')
  if (!trigger) throw new Error('project sources trigger missing')
  trigger.click()
})()
`)
  await waitForCondition(win, "document.querySelector('[data-project-sources-menu=\"true\"]')", 'project sources menu')
  await waitForCondition(win, "!document.querySelector('[data-project-source-create-toggle=\"true\"]')?.disabled", 'project source create toggle enabled')
  await win.webContents.executeJavaScript(`
(() => {
  const button = document.querySelector('[data-project-source-create-toggle="true"]')
  if (!button) throw new Error('project source create toggle missing')
  button.click()
})()
`)
  await waitForCondition(win, "document.querySelector('[data-project-source-create-form=\"true\"]')", 'project source create form')
  await win.webContents.executeJavaScript(`
(() => {
  const setValue = (element, value) => {
    const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value')
    if (descriptor?.set) descriptor.set.call(element, value)
    else element.value = value
    element.dispatchEvent(new Event('input', { bubbles: true }))
  }
  const title = document.querySelector('[data-project-source-title-input="true"]')
  const content = document.querySelector('[data-project-source-content-input="true"]')
  if (!title || !content) throw new Error('project source inputs missing')
  setValue(title, ${JSON.stringify(sourceTitle)})
  setValue(content, ${JSON.stringify(sourceContent)})
})()
`)
  await waitForCondition(win, "!document.querySelector('[data-project-source-save=\"true\"]')?.disabled", 'project source save enabled')
  await win.webContents.executeJavaScript(`
(() => {
  const save = document.querySelector('[data-project-source-save="true"]')
  if (!save) throw new Error('project source save missing')
  save.click()
})()
`)
  await waitForCondition(win, `document.body.innerText.includes(${JSON.stringify(sourceTitle)})`, 'created project source title')
  await waitForCondition(win, `document.body.innerText.includes(${JSON.stringify(sourceContent)})`, 'created project source content')
}

async function collectProjectSourceReport(win) {
  return win.webContents.executeJavaScript(`
(() => {
  const menu = document.querySelector('[data-project-sources-menu="true"]')
  const created = document.querySelector('[data-project-source-id="src_visual_note_2"]')
  const content = document.querySelector('[data-project-source-content="true"]')
  const menuRect = menu ? menu.getBoundingClientRect() : null
  const createdRect = created ? created.getBoundingClientRect() : null
  return {
    ok: Boolean(menu && created && content),
    viewport: { width: window.innerWidth, height: window.innerHeight },
    menuRect: menuRect ? {
      left: Math.round(menuRect.left),
      top: Math.round(menuRect.top),
      right: Math.round(menuRect.right),
      bottom: Math.round(menuRect.bottom),
      width: Math.round(menuRect.width),
      height: Math.round(menuRect.height),
    } : null,
    createdRect: createdRect ? {
      left: Math.round(createdRect.left),
      top: Math.round(createdRect.top),
      right: Math.round(createdRect.right),
      bottom: Math.round(createdRect.bottom),
      width: Math.round(createdRect.width),
      height: Math.round(createdRect.height),
    } : null,
    contentText: String(content?.textContent || ''),
    bodyText: document.body.innerText,
    clipped: Boolean(menuRect && (menuRect.left < 0 || menuRect.right > window.innerWidth || menuRect.top < 0 || menuRect.bottom > window.innerHeight)),
  }
})()
`)
}

async function deleteCreatedProjectSource(win) {
  await win.webContents.executeJavaScript(`
(() => {
  window.confirm = () => true
  const created = document.querySelector('[data-project-source-id="src_visual_note_2"]')
  if (!created) throw new Error('created project source missing before delete')
  created.click()
})()
`)
  await waitForCondition(win, "document.querySelector('[data-project-source-delete=\"true\"]')", 'project source delete button')
  await waitForCondition(win, "!document.querySelector('[data-project-source-delete=\"true\"]')?.disabled", 'project source delete button enabled')
  await win.webContents.executeJavaScript(`
(() => {
  const deleteButton = document.querySelector('[data-project-source-delete="true"]')
  if (!deleteButton) throw new Error('project source delete button missing')
  deleteButton.click()
})()
`)
  await waitForCondition(win, "!document.querySelector('[data-project-source-id=\"src_visual_note_2\"]')", 'deleted project source removed from active list')
}

async function collectProjectSourceDeleteReport(win) {
  return win.webContents.executeJavaScript(`
(() => {
  const menu = document.querySelector('[data-project-sources-menu="true"]')
  const deleted = document.querySelector('[data-project-source-id="src_visual_note_2"]')
  const existing = document.querySelector('[data-project-source-id="src_visual_existing"]')
  const detail = document.querySelector('[data-project-source-content="true"]')
  return {
    ok: Boolean(menu && !deleted && existing && detail),
    deletedPresent: Boolean(deleted),
    existingPresent: Boolean(existing),
    detailText: String(detail?.textContent || ''),
    bodyText: document.body.innerText,
  }
})()
`)
}

async function closeProjectSources(win) {
  await win.webContents.executeJavaScript(`
(() => {
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
})()
`)
  await wait(200)
}

async function openMessageActionMenu(win, messageId = 'msg_visual_user') {
  await waitForCondition(win, `document.querySelector('[data-message-action-trigger="${messageId}"]')`, 'message action trigger')
  await win.webContents.executeJavaScript(`
(() => {
  const trigger = document.querySelector('[data-message-action-trigger="${messageId}"]')
  if (!trigger) throw new Error('message action trigger missing')
  trigger.click()
})()
`)
  await waitForCondition(win, "document.querySelector('[class*=\"messageActionMenu\"]')", 'message action menu opened')
}

async function collectMessageActionMenuReport(win) {
  return win.webContents.executeJavaScript(`
(() => {
  const menu = document.querySelector('[class*="messageActionMenu"]')
  return {
    open: Boolean(menu),
    text: String(menu?.innerText || ''),
    hasSaveSource: Boolean(document.querySelector('[data-message-action="save-source"]')),
    hasEditRetry: Boolean(document.querySelector('[data-message-action="edit-retry"]')),
    hasRestoreCheckpoint: Boolean(document.querySelector('[data-message-action="restore-checkpoint"]')),
    hasCheckoutCheckpoint: Boolean(document.querySelector('[data-message-action="checkout-checkpoint"]')),
  }
})()
`)
}

async function closeMessageActionMenuOutside(win) {
  await win.webContents.executeJavaScript(`
(() => {
  const target = document.body
  target.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: 2, clientY: 2 }))
  target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: 2, clientY: 2 }))
})()
`)
  await waitForCondition(win, "!document.querySelector('[class*=\"messageActionMenu\"]')", 'message action menu closed by outside click')
}

async function switchToResearchMode(win) {
  await win.webContents.executeJavaScript(`
(() => {
  const settings = document.querySelector('[data-chat-settings="true"]')
  if (!settings) throw new Error('chat settings button missing')
  settings.click()
})()
`)
  await waitForCondition(win, "document.querySelector('[data-mode-value=\"research\"]')", 'research mode option')
  await win.webContents.executeJavaScript(`
(() => {
  const research = document.querySelector('[data-mode-value="research"]')
  if (!research) throw new Error('research mode option missing')
  research.click()
  const content = document.querySelector('[class*="contentArea"]')
  if (content) content.scrollTop = 0
})()
`)
  await waitForCondition(win, "document.querySelector('[data-research-status-bubble=\"true\"]')", 'research status bubble')
  await win.webContents.executeJavaScript(`
(() => {
  const bubble = document.querySelector('[data-research-status-bubble="true"]')
  if (bubble) bubble.scrollIntoView({ block: 'center' })
})()
`)
  await wait(300)
}

async function collectResearchAuditReport(win) {
  return win.webContents.executeJavaScript(`
(() => {
  const bubble = document.querySelector('[data-research-status-bubble="true"]')
  const stalePanel = document.querySelector('[data-research-panel="true"]')
  const bubbleRect = bubble ? bubble.getBoundingClientRect() : null
  const text = String(bubble?.innerText || bubble?.textContent || '')
  return {
    ok: Boolean(bubble && !stalePanel && text.includes('gpt_researcher') && text.includes('gather') && text.includes('rad_visual_research')),
    viewport: { width: window.innerWidth, height: window.innerHeight },
    bubbleRect: bubbleRect ? {
      left: Math.round(bubbleRect.left),
      top: Math.round(bubbleRect.top),
      right: Math.round(bubbleRect.right),
      bottom: Math.round(bubbleRect.bottom),
      width: Math.round(bubbleRect.width),
      height: Math.round(bubbleRect.height),
    } : null,
    text,
    hasStalePanel: Boolean(stalePanel),
    hasProvider: text.includes('gpt_researcher'),
    hasStage: text.includes('gather'),
    hasRunId: text.includes('rad_visual_research'),
    clipped: Boolean(bubbleRect && (bubbleRect.left < 0 || bubbleRect.right > window.innerWidth || bubbleRect.top < 0 || bubbleRect.bottom > window.innerHeight)),
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
  await selectVisualProject(win)
  await createProjectSourceNote(win)
  const projectSourceReport = await collectProjectSourceReport(win)
  const projectSourceScreenshot = await capture(win, 'main-project-source-note-created-400x620')
  await deleteCreatedProjectSource(win)
  const projectSourceDeleteReport = await collectProjectSourceDeleteReport(win)
  const projectSourceDeleteScreenshot = await capture(win, 'main-project-source-note-deleted-400x620')
  await closeProjectSources(win)

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
  await openMessageActionMenu(win)
  const messageActionOpenReport = await collectMessageActionMenuReport(win)
  const messageActionScreenshot = await capture(win, 'main-message-action-menu-400x620')
  await closeMessageActionMenuOutside(win)
  const messageActionClosedReport = await collectMessageActionMenuReport(win)
  const chatReport = await collectChatReport(win)
  const chatScreenshot = await capture(win, 'main-chat-after-send-400x620')
  await switchToResearchMode(win)
  const researchAuditReport = await collectResearchAuditReport(win)
  const researchScreenshot = await capture(win, 'main-research-status-bubble-400x620')

  const report = {
    visualUrl,
    apiBaseUrl,
    visualUsageReady,
    topControlsReport,
    projectSourceReport,
    projectSourceDeleteReport,
    islandReport,
    messageActionOpenReport,
    messageActionClosedReport,
    chatReport,
    researchAuditReport,
    screenshots: {
      topControls: topControlsScreenshot,
      projectSource: projectSourceScreenshot,
      projectSourceDelete: projectSourceDeleteScreenshot,
      island: islandScreenshot,
      messageAction: messageActionScreenshot,
      chat: chatScreenshot,
      research: researchScreenshot,
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
  if (!projectSourceReport.ok) {
    failures.push('project source create flow did not render the created source')
  } else {
    if (projectSourceReport.clipped) {
      failures.push('project source menu is clipped by the window')
    }
    if (!projectSourceReport.contentText.includes('400x620')) {
      failures.push(`project source created content missing: ${projectSourceReport.contentText}`)
    }
  }
  if (!projectSourceDeleteReport.ok) {
    failures.push(`project source delete flow did not archive/remove active source; deletedPresent=${projectSourceDeleteReport.deletedPresent} existingPresent=${projectSourceDeleteReport.existingPresent}`)
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
  if (!messageActionOpenReport.open) {
    failures.push('message action menu did not open')
  }
  if (!messageActionOpenReport.hasRestoreCheckpoint || !messageActionOpenReport.hasCheckoutCheckpoint) {
    failures.push(`message action menu did not expose immediate checkpoint actions: ${JSON.stringify(messageActionOpenReport)}`)
  }
  if (!messageActionOpenReport.hasEditRetry || !messageActionOpenReport.hasSaveSource) {
    failures.push(`message action menu missing expected V5 actions: ${JSON.stringify(messageActionOpenReport)}`)
  }
  if (messageActionClosedReport.open) {
    failures.push('message action menu stayed open after outside pointer/mouse click')
  }
  if (!researchAuditReport.ok) {
    failures.push(`research status bubble did not render expected adapter state: ${JSON.stringify(researchAuditReport)}`)
  } else {
    if (researchAuditReport.clipped) {
      failures.push('research status bubble is clipped by the window')
    }
    if (researchAuditReport.hasStalePanel) {
      failures.push('stale standalone research panel is still mounted')
    }
    if (!researchAuditReport.hasProvider) {
      failures.push(`research status bubble missing provider: ${researchAuditReport.text}`)
    }
    if (!researchAuditReport.hasStage) {
      failures.push(`research status bubble missing stage: ${researchAuditReport.text}`)
    }
    if (!researchAuditReport.hasRunId) {
      failures.push(`research status bubble missing external run id: ${researchAuditReport.text}`)
    }
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
