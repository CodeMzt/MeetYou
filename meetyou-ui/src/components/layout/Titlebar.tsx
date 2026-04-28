import { Database, Gauge, LayoutTemplate, MessageSquareMore, Minus, Paperclip, Pin, PinOff, Settings, Wrench, X } from 'lucide-react'
import { ClientWorkspace, ConnectionState } from '../../types'
import { getConnectionText } from '../../utils/statusFormatting'
import { WINDOW_OPEN_CHANNEL } from '../../windowBridge'
import styles from './Titlebar.module.css'

interface TitlebarProps {
  connectionState: ConnectionState
  workspace: ClientWorkspace | null
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
  const handleOpenAttachments = () => window.ipcRenderer?.send(WINDOW_OPEN_CHANNEL.attachments)
  const handleOpenDanxi = () => window.ipcRenderer?.send(WINDOW_OPEN_CHANNEL.danxi)
  const handleOpenStats = () => window.ipcRenderer?.send(WINDOW_OPEN_CHANNEL.context)
  const handleOpenDevtools = () => window.ipcRenderer?.send(WINDOW_OPEN_CHANNEL.runtimeDebug)

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
          <button className={styles.iconBtn} onClick={handleOpenWorkspacePanel} title="工作区">
            <LayoutTemplate size={15} />
          </button>
          <button className={styles.iconBtn} onClick={handleOpenAttachments} title="附件管理">
            <Paperclip size={15} />
          </button>
          <button className={styles.iconBtn} onClick={handleOpenDanxi} title="旦夕">
            <MessageSquareMore size={15} />
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
