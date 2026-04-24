import uiBuildInfo from './generated/build_info.json'

export interface BuildInfo {
  git_commit: string
  branch: string
  build_time: string
  component: string
  package_version: string
}

export interface RuntimeBuildInfoSnapshot {
  ui: BuildInfo
  desktop_backend: BuildInfo | null
  core: BuildInfo | null
  warning: string | null
}

function normalizeBuildInfo(payload: unknown): BuildInfo | null {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return null
  }
  const node = payload as Record<string, unknown>
  return {
    git_commit: String(node.git_commit || 'unknown'),
    branch: String(node.branch || 'unknown'),
    build_time: String(node.build_time || ''),
    component: String(node.component || 'unknown'),
    package_version: String(node.package_version || '0.0.0'),
  }
}

function readCompileTimeValue(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function applyCompileTimeUiBuildInfo(info: BuildInfo): BuildInfo {
  const gitCommit = readCompileTimeValue(
    typeof __MEETYOU_UI_GIT_COMMIT__ === 'string' ? __MEETYOU_UI_GIT_COMMIT__ : '',
  )
  const branch = readCompileTimeValue(
    typeof __MEETYOU_UI_GIT_BRANCH__ === 'string' ? __MEETYOU_UI_GIT_BRANCH__ : '',
  )
  const buildTime = readCompileTimeValue(
    typeof __MEETYOU_UI_BUILD_TIME__ === 'string' ? __MEETYOU_UI_BUILD_TIME__ : '',
  )

  return {
    ...info,
    git_commit: gitCommit && gitCommit !== 'unknown' ? gitCommit : info.git_commit,
    branch: branch && branch !== 'unknown' ? branch : info.branch,
    build_time: buildTime || info.build_time,
  }
}

export function detectBuildDriftWarning(ui: BuildInfo, desktopBackend: BuildInfo | null): string | null {
  if (!desktopBackend) {
    return null
  }
  if (!ui.git_commit || !desktopBackend.git_commit) {
    return null
  }
  if (ui.git_commit !== desktopBackend.git_commit) {
    return '检测到 UI 与 desktop backend 构建提交不一致。请先重启应用；若仍存在，请重新安装同一版本安装包。'
  }
  return null
}

export function getUiBuildInfo(): BuildInfo {
  const fallback = normalizeBuildInfo(uiBuildInfo) ?? {
    git_commit: 'unknown',
    branch: 'unknown',
    build_time: '',
    component: 'ui',
    package_version: '0.0.0',
  }
  return applyCompileTimeUiBuildInfo(fallback)
}

export async function fetchRuntimeBuildInfo(baseUrl: string): Promise<RuntimeBuildInfoSnapshot> {
  const ui = getUiBuildInfo()
  let desktopBackend: BuildInfo | null = null
  let core: BuildInfo | null = null

  try {
    const response = await fetch(`${baseUrl}/desktop/status`)
    if (response.ok) {
      const payload = (await response.json()) as Record<string, unknown>
      desktopBackend = normalizeBuildInfo(payload.build_info)
      core = normalizeBuildInfo(payload.core_build_info)
    }
  } catch {
    // best effort
  }

  return {
    ui,
    desktop_backend: desktopBackend,
    core,
    warning: detectBuildDriftWarning(ui, desktopBackend),
  }
}
