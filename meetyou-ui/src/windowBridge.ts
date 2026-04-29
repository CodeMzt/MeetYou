const DEFAULT_LOCAL_BRIDGE_BASE_URL = 'http://127.0.0.1:38951'
const ENV_LOCAL_BRIDGE_BASE_URL = String(import.meta.env.VITE_MEETYOU_DESKTOP_BASE_URL || '').trim()

function resolveRendererBridgeBaseUrl(): string {
  if (typeof window === 'undefined') {
    return ENV_LOCAL_BRIDGE_BASE_URL || DEFAULT_LOCAL_BRIDGE_BASE_URL
  }
  const candidate = String(window.meetyouDesktopRuntime?.bridgeBaseUrl || '').trim()
  return candidate || ENV_LOCAL_BRIDGE_BASE_URL || DEFAULT_LOCAL_BRIDGE_BASE_URL
}

export const DEFAULT_BASE_URL = resolveRendererBridgeBaseUrl()
export const DESKTOP_BRIDGE_STATUS_PATH = '/desktop/status'

export const WINDOW_HASH_ROUTE = {
  dashboard: '#/dashboard',
  settings: '#/settings',
  workspace: '#/workspace',
  attachments: '#/attachments',
  danxi: '#/danxi',
  context: '#/context',
  runtimeDebug: '#/runtime-debug',
} as const

export const WINDOW_HASH_ALIAS: Record<string, string> = {
  '#/usage': WINDOW_HASH_ROUTE.context,
  '#/stats': WINDOW_HASH_ROUTE.context,
  '#/devtools': WINDOW_HASH_ROUTE.runtimeDebug,
}

export const WINDOW_OPEN_CHANNEL = {
  dashboard: 'open-dashboard',
  settings: 'open-settings',
  workspace: 'open-workspace',
  attachments: 'open-attachments',
  danxi: 'open-danxi',
  context: 'open-context',
  runtimeDebug: 'open-runtime-debug',
} as const

export const WINDOW_SYNC_CHANNEL = {
  context: {
    update: 'context-window-updated',
    request: 'request-context-window',
  },
  runtimeDebug: {
    update: 'runtime-debug-window-updated',
    request: 'request-runtime-debug-window',
  },
  workspace: {
    update: 'workspace-window-updated',
    request: 'request-workspace-window',
  },
  attachments: {
    update: 'attachments-window-updated',
    request: 'request-attachments-window',
  },
  danxi: {
    update: 'danxi-window-updated',
    request: 'request-danxi-window',
  },
} as const

export const WINDOW_EVENT_CHANNEL = {
  danxiAuthUpdated: 'danxi-auth-updated',
  workspaceGovernanceUpdated: 'workspace-governance-updated',
} as const
