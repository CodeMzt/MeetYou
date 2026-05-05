const fs = require('fs')
const http = require('http')
const os = require('os')
const path = require('path')
const { execFileSync, spawn } = require('child_process')
const { app, BrowserWindow } = require('electron')

const appRoot = path.resolve(__dirname, '..')
const vitePort = Number(process.env.MEETYOU_SETTINGS_VISUAL_PORT || 5175)
const apiPort = Number(process.env.MEETYOU_SETTINGS_VISUAL_API_PORT || 5185)
const visualUrl = process.env.MEETYOU_SETTINGS_VISUAL_URL || `http://127.0.0.1:${vitePort}/#/settings`
const apiUrl = `http://127.0.0.1:${apiPort}`
const outputDir = process.env.MEETYOU_SETTINGS_VISUAL_OUTPUT_DIR || path.join(os.tmpdir(), 'meetyou-settings-skill-visual')
const sizes = [
  { name: 'settings-default', width: 560, height: 660 },
  { name: 'settings-minimum', width: 560, height: 620 },
]
const visualGitCommit = readGitValue(['rev-parse', 'HEAD'])
const visualGitBranch = readGitValue(['rev-parse', '--abbrev-ref', 'HEAD'], 'visual')
const visualBuildTime = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')

function readGitValue(args, fallback = 'unknown') {
  try {
    return execFileSync('git', args, { cwd: appRoot, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'ignore'] }).trim() || fallback
  } catch {
    return fallback
  }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function writeJson(response, payload, statusCode = 200) {
  response.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'authorization, content-type',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS',
  })
  response.end(JSON.stringify(payload))
}

function schemaEnvelope() {
  return {
    schema: 'meetyou.http.v1',
    kind: 'schema',
    ui_schema: {
      http_schema: 'meetyou.http.v1',
      ws_schema: 'meetyou.ws.v1',
      ws_frame_kinds: [],
      ws_event_types: [],
      ws_runtime_resources: [],
      runtime_statuses: ['idle'],
      providers: [{ label: 'OpenAI', value: 'openai' }],
      thinking_efforts: [{ label: '中', value: 'medium' }],
      config_groups: [
        {
          key: 'modes',
          title: '模式',
          description: '助手模式路由、可信写入目录与 JSON 配置包。',
        },
        {
          key: 'advanced',
          title: '高级',
          description: 'Gateway、飞书、MCP 等集成配置。',
        },
      ],
      config_fields: [
        {
          key: 'trusted_write_roots',
          title: '可信写入目录',
          description: '无需额外放宽信任边界即可写入本地文档的目录列表。',
          group: 'modes',
          input: 'list',
          control: 'directory_list',
          help_text: '每项是一个允许写入的目录；建议使用本机绝对路径。',
          examples: ['E:\\Documents\\MeetYou'],
          advanced: false,
        },
        {
          key: 'mode_router',
          title: '模式路由配置',
          description: '用于 Brain 决策、会话内切换与启发式回退策略的 JSON 配置。',
          group: 'modes',
          input: 'json',
          help_text: '必须是 JSON 对象。',
          examples: ['{"default_mode":"general"}'],
          advanced: false,
        },
        {
          key: 'web_search_quality',
          title: '网页搜索质量',
          description: '可选 adaptive、fast、balanced 或 deep。默认 adaptive。',
          group: 'advanced',
          input: 'select',
          options: [
            { label: '自适应', value: 'adaptive' },
            { label: '快速', value: 'fast' },
            { label: '均衡', value: 'balanced' },
            { label: '深入', value: 'deep' },
          ],
          advanced: false,
        },
      ],
    },
  }
}

function configSnapshot() {
  return {
    items: {
      trusted_write_roots: {
        key: 'trusted_write_roots',
        value: ['E:\\Documents\\MeetYou'],
        is_secret: false,
        has_value: true,
        source: 'config',
        env_key: null,
      },
      mode_router: {
        key: 'mode_router',
        value: { default_mode: 'general' },
        is_secret: false,
        has_value: true,
        source: 'config',
        env_key: null,
      },
      web_search_quality: {
        key: 'web_search_quality',
        value: 'adaptive',
        is_secret: false,
        has_value: true,
        source: 'config',
        env_key: null,
      },
    },
  }
}

function skillList() {
  return [
    {
      id: 'task_recognition',
      skill_type: 'reusable',
      title: '任务识别 SKILL',
      summary: '识别提醒、追踪、阻塞与任务状态请求，并衔接任务工具。',
      storage_path: '',
      storage_ref: 'core://skills/reusable/task_recognition',
      editable: false,
      source: 'builtin',
      applicable_modes: ['general', 'automation'],
      scenarios: ['提醒', '跟进', '任务更新'],
      recommended_tools: ['manage_tasks', 'create_scheduled_workflow'],
      content: 'Detect task, reminder, follow-up, blocker, and status-update intent. Use task and scheduled-workflow tools when needed.',
    },
    {
      id: 'mode:general',
      skill_type: 'mode',
      title: '通用模式 SKILL',
      summary: '通用日常协作范式，优先使用共享基础能力处理轻量任务。',
      storage_path: '',
      storage_ref: 'core://skills/mode/general',
      editable: false,
      source: 'builtin',
      applicable_modes: ['general'],
      scenarios: ['日常对话', '轻量规划'],
      recommended_tools: ['search_memory', 'search_web'],
      content: 'Operate as a general daily assistant. Use shared basic tools before escalating to specialized workflows.',
    },
  ]
}

function createFixtureServer() {
  const server = http.createServer((request, response) => {
    const url = new URL(request.url, apiUrl)
    if (request.method === 'OPTIONS') {
      writeJson(response, {})
      return
    }
    if (url.pathname === '/desktop/status') {
      writeJson(response, {
        status: 'ready',
        build_info: {
          git_commit: visualGitCommit,
          branch: visualGitBranch,
          build_time: visualBuildTime,
          component: 'desktop_backend',
          package_version: '1.0.0',
        },
        core_build_info: {
          git_commit: visualGitCommit,
          branch: visualGitBranch,
          build_time: visualBuildTime,
          component: 'core',
          package_version: '1.0.0',
        },
      })
      return
    }
    if (url.pathname === '/desktop/config/schema') {
      writeJson(response, schemaEnvelope())
      return
    }
    if (url.pathname === '/desktop/config') {
      writeJson(response, configSnapshot())
      return
    }
    if (url.pathname === '/desktop/skills') {
      writeJson(response, skillList())
      return
    }
    if (url.pathname.startsWith('/desktop/skills/')) {
      const skillId = decodeURIComponent(url.pathname.slice('/desktop/skills/'.length))
      const skill = skillList().find((item) => item.id === skillId)
      if (skill) {
        writeJson(response, skill)
        return
      }
      writeJson(response, { error: 'skill not found', skill_id: skillId }, 404)
      return
    }
    writeJson(response, { error: 'not found', path: url.pathname }, 404)
  })
  return new Promise((resolve) => {
    server.listen(apiPort, '127.0.0.1', () => resolve(server))
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
  if (!child || !child.pid) {
    return
  }
  if (process.platform === 'win32') {
    try {
      execFileSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], { stdio: 'ignore' })
      return
    } catch {
      // Fall back to the direct child below.
    }
  }
  child.kill()
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

async function captureState(win, size, stateName, requiredVisibleTexts) {
  await win.webContents.executeJavaScript(
    'new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))',
  )
  await wait(100)
  const report = await win.webContents.executeJavaScript(`
(() => {
  const requiredVisibleTexts = ${JSON.stringify(requiredVisibleTexts)}
  const visibleElements = Array.from(document.querySelectorAll('body *')).filter((element) => {
    const style = window.getComputedStyle(element)
    const rect = element.getBoundingClientRect()
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
  })
  const visibleTextMissing = requiredVisibleTexts.filter((text) => {
    return !visibleElements.some((element) => {
      const rect = element.getBoundingClientRect()
      const value = String(element.innerText || element.textContent || '')
      return value.includes(text) && rect.bottom > 0 && rect.top < window.innerHeight
    })
  })
  const horizontalOverflowElements = visibleElements
    .filter((element) => {
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
  const clippedControls = Array.from(document.querySelectorAll('button, select, textarea, input'))
    .filter((element) => {
      const rect = element.getBoundingClientRect()
      return rect.width < 24 || rect.height < 20 || rect.left < -1 || rect.right > window.innerWidth + 1
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
  return {
    name: ${JSON.stringify(size.name)},
    state: ${JSON.stringify(stateName)},
    viewport: { width: window.innerWidth, height: window.innerHeight },
    bodyOverflowX: document.documentElement.scrollWidth - window.innerWidth,
    visibleTextMissing,
    horizontalOverflowElements,
    clippedControls,
  }
})()
`)
  const image = await win.webContents.capturePage()
  const screenshotPath = path.join(outputDir, `${size.name}-${stateName}-${size.width}x${size.height}.png`)
  fs.writeFileSync(screenshotPath, image.toPNG())
  return { ...report, screenshotPath }
}

async function runVisualCheck() {
  fs.mkdirSync(outputDir, { recursive: true })
  process.env.MEETYOU_SETTINGS_VISUAL_API_URL = apiUrl
  app.commandLine.appendSwitch('disable-gpu')
  const fixtureServer = await createFixtureServer()
  let vite = null
  try {
    try {
      await waitForHttp(`http://127.0.0.1:${vitePort}`, 1000)
    } catch {
      vite = startVite()
    }
    await waitForHttp(`http://127.0.0.1:${vitePort}`)
    await app.whenReady()
    const win = new BrowserWindow({
      width: sizes[0].width,
      height: sizes[0].height,
      show: false,
      frame: false,
      transparent: true,
      resizable: true,
      minWidth: 560,
      minHeight: 620,
      webPreferences: {
        preload: path.join(__dirname, 'settings-skill-visual-preload.cjs'),
        nodeIntegration: false,
        contextIsolation: true,
      },
    })

    await win.loadURL(visualUrl)
    await waitForText(win, '可信写入目录')
    await wait(600)
    const reports = []
    for (const size of sizes) {
      win.setSize(size.width, size.height)
      await wait(400)
      await win.webContents.executeJavaScript('window.scrollTo(0, 0)')
      await wait(200)
      reports.push(await captureState(win, size, 'config-top', ['配置', 'SKILL', '可信写入目录', '添加目录']))

      await win.webContents.executeJavaScript(`
        Array.from(document.querySelectorAll('button')).find((button) => button.innerText.trim() === '添加目录')?.click()
      `)
      await wait(300)
      await win.webContents.executeJavaScript(`
        Array.from(document.querySelectorAll('label'))
          .find((label) => label.innerText.includes('可信写入目录'))
          ?.closest('.settings-field')
          ?.scrollIntoView({ block: 'center' })
      `)
      await wait(200)
      reports.push(await captureState(win, size, 'directory-picked', ['E:\\Visual\\Trusted', 'D:\\Reports\\MeetYou']))

      await win.webContents.executeJavaScript(`
        Array.from(document.querySelectorAll('button')).find((button) => button.innerText.trim() === 'SKILL')?.click()
      `)
      await waitForText(win, '任务识别 SKILL')
      reports.push(await captureState(win, size, 'skills-list', ['任务识别 SKILL', '通用模式 SKILL', 'core://skills']))

      await win.webContents.executeJavaScript(`
        document.querySelector('.skill-list-item')?.click()
      `)
      await waitForText(win, 'SKILL 详情')
      reports.push(await captureState(win, size, 'skill-detail', ['SKILL 详情', 'core://skills', 'Detect task', 'manage_tasks']))
      await win.webContents.executeJavaScript(`
        document.querySelector('.skill-detail-header button')?.click()
      `)
      await wait(200)

      await win.webContents.executeJavaScript(`
        Array.from(document.querySelectorAll('button')).find((button) => button.innerText.trim() === '配置')?.click()
      `)
      await waitForText(win, '可信写入目录')
    }

    const reportPath = path.join(outputDir, 'settings-skill-visual-report.json')
    fs.writeFileSync(reportPath, JSON.stringify({ visualUrl, apiUrl, reports }, null, 2))
    const failures = reports.flatMap((report) => {
      const items = []
      if (report.visibleTextMissing.length > 0) {
        items.push(`${report.name}/${report.state}: missing visible text ${report.visibleTextMissing.join(', ')}`)
      }
      if (report.bodyOverflowX > 1 || report.horizontalOverflowElements.length > 0) {
        items.push(`${report.name}/${report.state}: horizontal overflow`)
      }
      if (report.clippedControls.length > 0) {
        items.push(`${report.name}/${report.state}: clipped controls`)
      }
      return items
    })
    console.log(JSON.stringify({ ok: failures.length === 0, reportPath, reports }, null, 2))
    if (failures.length > 0) {
      throw new Error(failures.join('; '))
    }
  } finally {
    stopProcessTree(vite)
    fixtureServer.close()
    app.quit()
  }
}

runVisualCheck().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
