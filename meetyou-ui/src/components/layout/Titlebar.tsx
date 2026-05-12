import { Database, Gauge, LayoutTemplate, MessageSquareMore, Minus, Pin, PinOff, Settings, Wrench, X } from 'lucide-react'
import { RuntimeWorkspace, ConnectionState } from '../../types'
import { getConnectionText } from '../../utils/statusFormatting'
import { WINDOW_OPEN_CHANNEL } from '../../windowBridge'
import styles from './Titlebar.module.css'

interface TitlebarProps {
  connectionState: ConnectionState
  workspace: RuntimeWorkspace | null
  desktopToolsAvailable: boolean
  isPinned: boolean
  onTogglePin: () => void
}

export default function Titlebar({
  connectionState,
  workspace,
  desktopToolsAvailable,
  isPinned,
  onTogglePin,
}: TitlebarProps) {
  const connectionText = getConnectionText(connectionState)

  const handleClose = () => window.ipcRenderer?.send('window-close')
  const handleMinimize = () => window.ipcRenderer?.send('window-minimize')
  const handleOpenDashboard = () => window.ipcRenderer?.send(WINDOW_OPEN_CHANNEL.dashboard)
  const handleOpenSettings = () => window.ipcRenderer?.send(WINDOW_OPEN_CHANNEL.settings)
  const handleOpenWorkspacePanel = () => window.ipcRenderer?.send(WINDOW_OPEN_CHANNEL.workspace)
  const handleOpenDanxi = () => window.ipcRenderer?.send(WINDOW_OPEN_CHANNEL.danxi)
  const handleOpenStats = () => window.ipcRenderer?.send(WINDOW_OPEN_CHANNEL.context)
  const handleOpenDevtools = () => window.ipcRenderer?.send(WINDOW_OPEN_CHANNEL.runtimeDebug)
  const toolItems = [
    {
      key: 'pin',
      title: isPinned ? '取消置顶' : '置顶窗口',
      icon: isPinned ? <Pin size={15} /> : <PinOff size={15} />,
      action: onTogglePin,
      active: isPinned,
    },
    { key: 'dashboard', title: '记忆图谱', icon: <Database size={15} />, action: handleOpenDashboard },
    { key: 'workspace', title: '工作区', icon: <LayoutTemplate size={15} />, action: handleOpenWorkspacePanel },
    { key: 'danxi', title: '旦夕', icon: <MessageSquareMore size={15} />, action: handleOpenDanxi },
    { key: 'stats', title: '上下文与用量', icon: <Gauge size={15} />, action: handleOpenStats },
    { key: 'devtools', title: '开发工具', icon: <Wrench size={15} />, action: handleOpenDevtools },
    { key: 'settings', title: '设置', icon: <Settings size={15} />, action: handleOpenSettings },
  ]

  return (
    <div className={styles.titlebar}>
      <div className={styles.topRow}>
        <div className={styles.titleContent}>
          <div
            className={styles.envPill}
            title={`服务端：${connectionText} | 本地工具：${desktopToolsAvailable ? '在线' : '离线'}`}
          >
            <span className={styles.envWorkspaceName}>
              {workspace?.title || workspace?.workspace_id || '未绑定'}
            </span>
            <span className={`${styles.statusDot} ${styles[connectionState]}`} />
          </div>
        </div>

        <div className={styles.dragRegion} />

        <div className={styles.tools}>
          {toolItems.map((item) => (
            <button
              key={item.key}
              className={`${styles.iconBtn} ${item.active ? styles.active : ''}`}
              onClick={item.action}
              title={item.title}
              data-titlebar-tool={item.key}
            >
              {item.icon}
            </button>
          ))}
        </div>

        <div className={styles.windowControls}>
          <button className={`${styles.winBtn} ${styles.minimize}`} onClick={handleMinimize} title="最小化">
            <Minus size={14} />
          </button>
          <button className={`${styles.winBtn} ${styles.close}`} onClick={handleClose} title="关闭">
            <X size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}
