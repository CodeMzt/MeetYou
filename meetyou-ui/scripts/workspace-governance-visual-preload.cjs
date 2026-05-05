const { contextBridge } = require('electron')

const workspacePayload = {
  baseUrl: 'http://127.0.0.1:38951',
  threadId: 'thread_visual_check',
  connectionState: 'connected',
  desktopToolsAvailable: true,
  approvalDisplay: null,
  pendingHumanInput: null,
  operations: [
    {
      operation_id: 'op_visual_running',
      thread_id: 'thread_visual_check',
      workspace_id: 'personal',
      status: 'running',
      title: '工作区路由探测',
      operation_type: 'tool.call',
      execution_target: 'workspace_any_endpoint',
      target_endpoint_id: 'desktop.personal-workstation.executor',
      tool_key: 'utility.echo',
      tool_id: 'endpoint.desktop.personal-workstation.executor.utility.echo',
      call_id: 'call_visual_running',
      phase: 'dispatching',
      detail: '',
      result: {},
      error: {},
      summary: '',
      tone: 'running',
      isBlocking: false,
      approval_required: false,
      approval_status: '',
      approval_id: '',
    },
    {
      operation_id: 'op_visual_approval',
      thread_id: 'thread_visual_check',
      workspace_id: 'personal',
      status: 'running',
      title: '命令执行确认',
      operation_type: 'tool.call',
      execution_target: 'workspace_any_endpoint',
      target_endpoint_id: 'desktop.personal-workstation.executor',
      tool_key: 'shell.exec',
      tool_id: 'endpoint.desktop.personal-workstation.executor.shell.exec',
      call_id: 'call_visual_approval',
      phase: 'waiting_approval',
      detail: '',
      result: {},
      error: {},
      summary: '',
      tone: 'pending',
      isBlocking: true,
      approval_required: true,
      approval_status: 'pending',
      approval_id: 'approval_visual',
    },
  ],
  workspace: {
    workspace_id: 'personal',
    title: '个人工作区',
    status: 'active',
    base_mode: 'automation',
    description: '用于在真实窗口中验证路由治理控件的工作区。',
    prompt_overlay: '',
    default_execution_target: 'workspace_any_endpoint',
    tool_policy: 'allowlist',
    allowed_tool_ids: ['utility.echo', 'shell.exec', 'workspace.analyze', 'delivery.message'],
    preferred_target_endpoint_ids: [
      'desktop.personal-workstation.executor',
      'edge.remote-lab-west.executor',
    ],
    preferred_endpoint_provider_types: ['desktop', 'edge', 'feishu'],
    preferred_source_profiles: ['workspace_local', 'study_materials'],
    tool_target_routing_policy: 'strict_preferred_endpoint',
    memory_ranking_policy: 'workspace_first',
    tool_routing_overrides: {
      'utility.echo': {
        preferred_target_endpoint_ids: ['desktop.personal-workstation.executor'],
        tool_target_routing_policy: 'strict_preferred_endpoint',
      },
      'delivery.message': {
        preferred_endpoint_provider_types: ['feishu', 'wechatbot'],
        tool_target_routing_policy: 'balanced',
      },
    },
  },
}

const listeners = new Map()

function emit(channel, data) {
  const callbacks = listeners.get(channel) || new Set()
  for (const callback of callbacks) {
    try {
      callback({}, data)
    } catch {
      // Visual QA should not fail because a mocked listener throws.
    }
  }
}

contextBridge.exposeInMainWorld('meetyouDesktopRuntime', {
  bridgeBaseUrl: workspacePayload.baseUrl,
})

contextBridge.exposeInMainWorld('ipcRenderer', {
  on(channel, callback) {
    if (!listeners.has(channel)) {
      listeners.set(channel, new Set())
    }
    listeners.get(channel).add(callback)
  },
  off(channel, callback) {
    listeners.get(channel)?.delete(callback)
  },
  send(channel, data) {
    if (channel === 'request-workspace-window') {
      setTimeout(() => emit('workspace-window-updated', workspacePayload), 0)
    }
    if (channel === 'workspace-governance-updated') {
      setTimeout(() => emit('workspace-window-updated', { ...workspacePayload, workspace: data?.workspace || workspacePayload.workspace }), 0)
    }
  },
})
