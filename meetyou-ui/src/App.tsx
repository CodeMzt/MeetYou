import { useState, useEffect, useMemo } from 'react'
import { getDanxiSessionStatus } from './runtimeApi'
import { useMeetYou } from './hooks/useMeetYou'
import Titlebar from './components/layout/Titlebar'
import StatusIsland from './components/status/StatusIsland'
import MessageList from './components/chat/MessageList'
import ChatInput from './components/input/ChatInput'
import ProjectPicker from './components/project/ProjectPicker'
import ThreadPicker from './components/thread/ThreadPicker'
import VersionControl from './components/version/VersionControl'
import { AssistantMode, ThinkingOverride } from './types'
import { getVisibleRuntimeThreadItems } from './threadPresentation'
import { DEFAULT_BASE_URL, WINDOW_EVENT_CHANNEL, WINDOW_SYNC_CHANNEL } from './windowBridge'
import styles from './App.module.css'

export default function App() {
  const baseUrl = DEFAULT_BASE_URL
  const {
    messages,
    workspace,
    sendMessage,
    connectionState,
    connected,
    desktopToolsAvailable,
    runtimeSnapshot,
    usageSnapshot,
    approvalDisplay,
    confirmRequest,
    pendingHumanInput,
    healthSnapshot,
    lastError,
    archivedTurnCount,
    statusFeedback,
    threads,
    projects,
    branches,
    checkpoints,
    activeProjectId,
    threadId,
    defaultThreadId,
    sendConfirmResponse,
    sendHumanInputResponse,
    sendControlCommand,
    saveMessageAsProjectSource,
    editRetryMessage,
    createCheckpoint,
    restoreCheckpoint,
    checkoutCheckpoint,
    createThread,
    createProject,
    deleteThread,
    refreshWorkspace,
    selectProject,
    selectThread,
  } = useMeetYou(baseUrl)

  const [inputVal, setInputVal] = useState('')
  const [isPinned, setIsPinned] = useState(true)
  const [thinkingOverride, setThinkingOverride] = useState<ThinkingOverride>('default')
  const [preferredMode, setPreferredMode] = useState<AssistantMode>('general')
  const [danxiStatusText, setDanxiStatusText] = useState('未连接')
  const projectThreads = useMemo(
    () => activeProjectId
      ? threads.filter((thread) => String(thread.project_id || '') === activeProjectId)
      : threads,
    [activeProjectId, threads],
  )
  const visibleThreads = useMemo(
    () => getVisibleRuntimeThreadItems(projectThreads, threadId, defaultThreadId),
    [defaultThreadId, projectThreads, threadId],
  )

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
    }

    window.ipcRenderer?.on(WINDOW_EVENT_CHANNEL.workspaceGovernanceUpdated, handleWorkspaceGovernanceUpdated)
    return () => {
      window.ipcRenderer?.off(WINDOW_EVENT_CHANNEL.workspaceGovernanceUpdated, handleWorkspaceGovernanceUpdated)
    }
  }, [refreshWorkspace])

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
              ? `已连接 · ${status.transport || '直连'}`
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
        desktopToolsAvailable={desktopToolsAvailable}
        isPinned={isPinned}
        onTogglePin={togglePin}
      />

      <div className={styles.mainContent}>
        <div className={styles.topDock}>
          <StatusIsland
            runtimeSnapshot={runtimeSnapshot}
            usageSnapshot={usageSnapshot}
            healthSnapshot={healthSnapshot}
            statusFeedback={statusFeedback}
            preferredMode={preferredMode}
            danxiStatusText={danxiStatusText}
          />

          <div className={styles.threadPickerSlot}>
            <ProjectPicker
              projects={projects}
              activeProjectId={activeProjectId}
              onSelectProject={(nextProjectId) => selectProject(nextProjectId)}
              onCreateProject={(title) => createProject(title)}
            />
            <ThreadPicker
              items={visibleThreads}
              activeThreadId={threadId}
              onSelectThread={(nextThreadId) => void selectThread(nextThreadId)}
              onCreateThread={(title) => createThread(title, activeProjectId)}
              onDeleteThread={(nextThreadId) => deleteThread(nextThreadId)}
            />
            <VersionControl
              branches={branches}
              checkpoints={checkpoints}
              onCreateCheckpoint={() => createCheckpoint()}
              onRestoreCheckpoint={(checkpointId) => restoreCheckpoint(checkpointId)}
              onCheckoutCheckpoint={(checkpointId) => checkoutCheckpoint(checkpointId)}
            />
          </div>
        </div>

        <div className={styles.contentArea}>
          <MessageList
            connected={connected}
            messages={messages}
            runtimeSnapshot={runtimeSnapshot}
            healthSnapshot={healthSnapshot}
            lastError={lastError}
            archivedTurnCount={archivedTurnCount}
            approvalDisplay={approvalDisplay}
            pendingHumanInput={pendingHumanInput}
            sendConfirmResponse={sendConfirmResponse}
            sendHumanInputResponse={sendHumanInputResponse}
            sendControlCommand={sendControlCommand}
            activeProjectId={activeProjectId}
            onSaveMessageAsProjectSource={saveMessageAsProjectSource}
            onEditRetryMessage={editRetryMessage}
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
      />
    </div>
  )
}
