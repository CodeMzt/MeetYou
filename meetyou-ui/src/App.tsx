import { useState, useEffect } from 'react'
import { getDanxiSessionStatus } from './clientApi'
import { useMeetYou } from './hooks/useMeetYou'
import Titlebar from './components/layout/Titlebar'
import StatusIsland from './components/status/StatusIsland'
import StatusStrip from './components/status/StatusStrip'
import MessageList from './components/chat/MessageList'
import ChatInput from './components/input/ChatInput'
import { AssistantMode, ThinkingOverride } from './types'
import { DEFAULT_BASE_URL, WINDOW_EVENT_CHANNEL, WINDOW_SYNC_CHANNEL } from './windowBridge'
import styles from './App.module.css'

export default function App() {
  const baseUrl = DEFAULT_BASE_URL
  const {
    messages,
    operations,
    workspace,
    sendMessage,
    decideOperationApproval,
    connectionState,
    connected,
    desktopAgentConnected,
    runtimeSnapshot,
    usageSnapshot,
    turnActivities,
    approvalDisplay,
    confirmRequest,
    pendingHumanInput,
    healthSnapshot,
    lastError,
    archivedTurnCount,
    statusFeedback,
    sendConfirmResponse,
    sendHumanInputResponse,
    sendControlCommand,
    uploadAttachment,
    downloadAttachment,
    refreshWorkspace,
    reloadProcedureContext,
  } = useMeetYou(baseUrl)

  const [inputVal, setInputVal] = useState('')
  const [isPinned, setIsPinned] = useState(true)
  const [thinkingOverride, setThinkingOverride] = useState<ThinkingOverride>('default')
  const [preferredMode, setPreferredMode] = useState<AssistantMode>('general')
  const [danxiStatusText, setDanxiStatusText] = useState('未连接')

  const togglePin = () => {
    const nextPinned = !isPinned
    setIsPinned(nextPinned)
    window.ipcRenderer?.send('window-toggle-top', nextPinned)
  }

  useEffect(() => {
    window.ipcRenderer?.send(WINDOW_SYNC_CHANNEL.danxi.update, {
      baseUrl,
      preferredMode,
      workspaceTitle: workspace?.title || workspace?.workspace_id || '',
    })
  }, [baseUrl, preferredMode, workspace])

  useEffect(() => {
    const handleWorkspaceGovernanceUpdated = (_event: unknown, data: { workspace_id?: string } | null) => {
      void refreshWorkspace(data?.workspace_id)
      void reloadProcedureContext()
    }

    window.ipcRenderer?.on(WINDOW_EVENT_CHANNEL.workspaceGovernanceUpdated, handleWorkspaceGovernanceUpdated)
    return () => {
      window.ipcRenderer?.off(WINDOW_EVENT_CHANNEL.workspaceGovernanceUpdated, handleWorkspaceGovernanceUpdated)
    }
  }, [refreshWorkspace, reloadProcedureContext])

  useEffect(() => {
    if (preferredMode !== 'danxi') {
      return
    }
    let cancelled = false
    const loadDanxiStatus = async () => {
      try {
        const status = await getDanxiSessionStatus(baseUrl)
        if (!cancelled) {
          setDanxiStatusText(
            status.logged_in
              ? `已连接 · ${status.transport || 'direct'}`
              : status.connection_error
                ? '连接异常'
                : '未连接',
          )
        }
      } catch {
        if (!cancelled) {
          setDanxiStatusText('未连接')
        }
      }
    }
    void loadDanxiStatus()
    const handleDanxiAuthUpdated = () => {
      void loadDanxiStatus()
    }
    window.ipcRenderer?.on(WINDOW_EVENT_CHANNEL.danxiAuthUpdated, handleDanxiAuthUpdated)
    return () => {
      cancelled = true
      window.ipcRenderer?.off(WINDOW_EVENT_CHANNEL.danxiAuthUpdated, handleDanxiAuthUpdated)
    }
  }, [baseUrl, preferredMode])

  const handleSend = () => {
    if (!inputVal.trim() || !connected || confirmRequest || pendingHumanInput) {
      return
    }
    void sendMessage(inputVal, thinkingOverride, preferredMode)
    setInputVal('')
  }

  return (
    <div className={styles.appContainer}>
      <Titlebar
        connectionState={connectionState}
        workspace={workspace}
        desktopAgentConnected={desktopAgentConnected}
        isPinned={isPinned}
        onTogglePin={togglePin}
      />

      <div className={styles.mainContent}>
        <StatusIsland 
          runtimeSnapshot={runtimeSnapshot}
          usageSnapshot={usageSnapshot}
          healthSnapshot={healthSnapshot}
          statusFeedback={statusFeedback}
          preferredMode={preferredMode}
          danxiStatusText={danxiStatusText}
        />

        <div className={styles.contentArea}>
          <StatusStrip
            connectionState={connectionState}
            runtimeSnapshot={runtimeSnapshot}
            healthSnapshot={healthSnapshot}
            turnActivities={turnActivities}
          />
          <MessageList
            connected={connected}
            messages={messages}
            operations={operations}
            runtimeSnapshot={runtimeSnapshot}
            healthSnapshot={healthSnapshot}
            lastError={lastError}
            archivedTurnCount={archivedTurnCount}
            approvalDisplay={approvalDisplay}
            pendingHumanInput={pendingHumanInput}
            sendConfirmResponse={sendConfirmResponse}
            sendHumanInputResponse={sendHumanInputResponse}
            decideOperationApproval={decideOperationApproval}
            onDownloadAttachment={(attachmentId) => void downloadAttachment(attachmentId)}
            sendControlCommand={sendControlCommand}
          />
        </div>
      </div>

      <ChatInput
        connected={connected}
        connectionState={connectionState}
        inputVal={inputVal}
        setInputVal={setInputVal}
        preferredMode={preferredMode}
        setPreferredMode={setPreferredMode}
        thinkingOverride={thinkingOverride}
        setThinkingOverride={setThinkingOverride}
        onSend={handleSend}
        confirmRequest={confirmRequest}
        pendingHumanInput={pendingHumanInput}
        runtimeSnapshot={runtimeSnapshot}
        sendControlCommand={sendControlCommand}
        onUploadAttachment={(file) => void uploadAttachment(file)}
      />
    </div>
  )
}
