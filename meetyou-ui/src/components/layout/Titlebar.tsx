import { Database, Minus, Pin, PinOff, Settings, X } from 'lucide-react'
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

  return (
    <div className={styles.titlebar}>
      <div className={styles.topRow}>
        <div className={styles.titleContent}>
          <span className={styles.titleText}>MeetYou</span>
          <span
            className={`${styles.statusDot} ${styles[connectionState]}`}
            title={connectionText}
          />
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

      <div className={styles.metaRow}>
        <div className={styles.metaCard} title={`Core ${connectionText}`}>
          <span className={styles.metaLabel}>Core</span>
          <span className={styles.metaValue}>{connectionText}</span>
        </div>
        <div className={styles.metaCard} title={`Local Agent ${desktopAgentConnected ? 'online' : 'offline'}`}>
          <span className={styles.metaLabel}>Agent</span>
          <span className={styles.metaValue}>{desktopAgentConnected ? 'online' : 'offline'}</span>
        </div>
        <div className={styles.metaCard} title={`Workspace ${workspace?.title || workspace?.workspace_id || 'unbound'}`}>
          <span className={styles.metaLabel}>Workspace</span>
          <span className={styles.metaValue}>{workspace?.title || workspace?.workspace_id || 'unbound'}</span>
        </div>
      </div>
    </div>
  )
}
