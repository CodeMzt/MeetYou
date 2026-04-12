import { Database, Gauge, LayoutTemplate, Minus, Pin, PinOff, Settings, Wrench, X } from 'lucide-react'
import { ClientWsConnectionState, ClientWorkspace } from '../../types'
import { getConnectionText } from '../../utils/statusFormatting'
import styles from './Titlebar.module.css'

interface TitlebarProps {
  connectionState: ClientWsConnectionState | 'connecting' | 'disconnected'
  workspace: ClientWorkspace | null
  desktopAgentConnected: boolean
  isPinned: boolean
  onTogglePin: () => void
}

export default function Titlebar({
  connectionState,
  workspace,
  desktopAgentConnected,
  isPinned,
  onTogglePin,
}: TitlebarProps) {
  const connectionText = getConnectionText(connectionState)

  const handleClose = () => window.ipcRenderer?.send('window-close')
  const handleMinimize = () => window.ipcRenderer?.send('window-minimize')
  const handleOpenDashboard = () => window.ipcRenderer?.send('open-dashboard')
  const handleOpenSettings = () => window.ipcRenderer?.send('open-settings')
  const handleOpenWorkspacePanel = () => window.ipcRenderer?.send('open-workspace-panel')
  const handleOpenStats = () => window.ipcRenderer?.send('open-stats')
  const handleOpenDevtools = () => window.ipcRenderer?.send('open-devtools')

  return (
    <div className={styles.titlebar}>
      <div className={styles.topRow}>
        <div className={styles.titleContent}>
          <img src="/icon.svg" alt="MeetYou" className={styles.appIcon} />
          <span className={styles.titleText}>MeetYou</span>
          <div 
            className={styles.envPill}
            title={`服务端：${connectionText} | 本地代理：${desktopAgentConnected ? '在线' : '离线'}`}
          >
            <span className={styles.envWorkspaceName}>
              {workspace?.title || workspace?.workspace_id || '未绑定'}
            </span>
            <span className={`${styles.statusDot} ${styles[connectionState]}`} />
          </div>
        </div>

        <div className={styles.dragRegion} />

        <div className={styles.tools}>
          <button
            className={`${styles.iconBtn} ${isPinned ? styles.active : ''}`}
            onClick={onTogglePin}
            title={isPinned ? '取消置顶' : '置顶窗口'}
          >
            {isPinned ? <Pin size={15} /> : <PinOff size={15} />}
          </button>
          <button className={styles.iconBtn} onClick={handleOpenDashboard} title="记忆图谱">
            <Database size={15} />
          </button>
          <button className={styles.iconBtn} onClick={handleOpenWorkspacePanel} title="工作区与规程">
            <LayoutTemplate size={15} />
          </button>
          <button className={styles.iconBtn} onClick={handleOpenStats} title="上下文与用量">
            <Gauge size={15} />
          </button>
          <button className={styles.iconBtn} onClick={handleOpenDevtools} title="开发工具">
            <Wrench size={15} />
          </button>
          <button className={styles.iconBtn} onClick={handleOpenSettings} title="设置">
            <Settings size={15} />
          </button>
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
