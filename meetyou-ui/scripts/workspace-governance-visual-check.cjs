const fs = require('fs')
const http = require('http')
const os = require('os')
const path = require('path')
const { spawn } = require('child_process')
const { app, BrowserWindow } = require('electron')

const appRoot = path.resolve(__dirname, '..')
const port = Number(process.env.MEETYOU_VISUAL_PORT || 5173)
const visualUrl = process.env.MEETYOU_VISUAL_URL || `http://127.0.0.1:${port}/#/workspace`
const outputDir = process.env.MEETYOU_VISUAL_OUTPUT_DIR || path.join(os.tmpdir(), 'meetyou-workspace-governance-visual')
const sizes = [
  { name: 'workspace-default', width: 560, height: 700 },
  { name: 'workspace-minimum', width: 520, height: 620 },
]
const states = [
  {
    name: 'top',
    visibleTexts: ['个人工作区', 'Provider 偏好：3', '路由策略：严格偏好端点'],
    scrollScript: 'window.scrollTo(0, 0)',
  },
  {
    name: 'governance',
    visibleTexts: [
      '运行治理与路由偏好',
      '默认执行目标',
      '路由策略',
      '工具策略',
      '允许工具',
      '偏好端点',
      'Provider 偏好',
      '工具路由覆盖',
    ],
    scrollScript: `
      (() => {
        const heading = Array.from(document.querySelectorAll('h3')).find((item) => item.innerText.includes('运行治理与路由偏好'))
        if (heading) heading.scrollIntoView({ block: 'start' })
        window.scrollBy(0, -12)
      })()
    `,
  },
  {
    name: 'governance-lower',
    visibleTexts: ['Provider 偏好', '工具路由覆盖', '偏好来源', '记忆排序'],
    scrollScript: `
      (() => {
        const label = Array.from(document.querySelectorAll('label')).find((item) => item.innerText.trim().startsWith('Provider 偏好'))
        if (label) label.scrollIntoView({ block: 'start' })
        window.scrollBy(0, -16)
      })()
    `,
  },
]

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
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
      env: { ...process.env, BROWSER: 'none' },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    },
  )
  child.stdout.on('data', (chunk) => process.stdout.write(chunk))
  child.stderr.on('data', (chunk) => process.stderr.write(chunk))
  return child
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
  const requiredTexts = [
    '运行治理与路由偏好',
    '默认执行目标',
    '路由策略',
    '工具策略',
    '允许工具',
    '偏好端点',
    'Provider 偏好',
    '工具路由覆盖',
    '偏好来源',
    '记忆排序',
    'Provider 偏好：3',
    '路由策略：严格偏好端点'
  ]
  const requiredVisibleTexts = ${JSON.stringify(state.visibleTexts)}
  const bodyText = document.body.innerText || ''
  const missingTexts = requiredTexts.filter((text) => !bodyText.includes(text))
  const viewport = { width: window.innerWidth, height: window.innerHeight }
  const bodyOverflowX = document.documentElement.scrollWidth - window.innerWidth
  const visibleElements = Array.from(document.querySelectorAll('body *')).filter((element) => {
    const style = window.getComputedStyle(element)
    const rect = element.getBoundingClientRect()
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
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
  const controls = Array.from(document.querySelectorAll('button, select, textarea'))
  const clippedControls = controls
    .filter((element) => {
      const rect = element.getBoundingClientRect()
      return rect.width < 32 || rect.height < 24 || rect.left < -1 || rect.right > window.innerWidth + 1
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
    viewport,
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
  await waitForText(win, '运行治理与路由偏好')
  const reports = []
  for (const size of sizes) {
    win.setSize(size.width, size.height)
    await wait(500)
    for (const state of states) {
      await win.webContents.executeJavaScript(state.scrollScript)
      await wait(250)
      const report = await collectLayoutReport(win, size, state)
      const image = await win.webContents.capturePage()
      const screenshotPath = path.join(outputDir, `${size.name}-${state.name}-${size.width}x${size.height}.png`)
      fs.writeFileSync(screenshotPath, image.toPNG())
      reports.push({ ...report, screenshotPath })
    }
  }

  const reportPath = path.join(outputDir, 'workspace-governance-visual-report.json')
  fs.writeFileSync(reportPath, JSON.stringify({ visualUrl, reports }, null, 2))
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
    throw new Error(failures.join('; '))
  }
}

let viteProcess = null

async function main() {
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
    if (viteProcess && !viteProcess.killed) {
      viteProcess.kill()
    }
    app.quit()
  }
}

main().catch((error) => {
  console.error(error)
  if (viteProcess && !viteProcess.killed) {
    viteProcess.kill()
  }
  app.exit(1)
})
