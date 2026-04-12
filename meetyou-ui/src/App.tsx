import { useState, useEffect } from 'react'
import { useMeetYou } from './hooks/useMeetYou'
import Titlebar from './components/layout/Titlebar'
import StatusIsland from './components/status/StatusIsland'
import MessageList from './components/chat/MessageList'
import ChatInput from './components/input/ChatInput'
import { AssistantMode, ThinkingOverride } from './types'
import styles from './App.module.css'

export default function App() {
  const baseUrl = 'http://127.0.0.1:8000'
  const {
    messages,
    operations,
    procedureContext,
    workspace,
    sendMessage,
    decideOperationApproval,
    sessionId,
    threadId,
    connectionState,
    connected,
    desktopAgentConnected,
    runtimeSnapshot,
    usageSnapshot,
    approvalDisplay,
    confirmRequest,
    pendingHumanInput,
    healthSnapshot,
    lastError,
    archivedTurnCount,
    sendConfirmResponse,
    sendHumanInputResponse,
    sendControlCommand,
    uploadAttachment,
    downloadAttachment,
    refreshWorkspace,
  } = useMeetYou(baseUrl)

  const [inputVal, setInputVal] = useState('')
  const [isPinned, setIsPinned] = useState(true)
  const [thinkingOverride, setThinkingOverride] = useState<ThinkingOverride>('default')
  const [preferredMode, setPreferredMode] = useState<AssistantMode>('general')

  const togglePin = () => {
    const nextPinned = !isPinned
    setIsPinned(nextPinned)
    window.ipcRenderer?.send('window-toggle-top', nextPinned)
  }

  useEffect(() => {
    window.ipcRenderer?.send('update-devtools', { usageSnapshot, sessionId, baseUrl })
  }, [usageSnapshot, sessionId, baseUrl])

  useEffect(() => {
    window.ipcRenderer?.send('update-stats', { usageSnapshot })
  }, [usageSnapshot])

  useEffect(() => {
    window.ipcRenderer?.send('update-workspace-panel', {
      baseUrl,
      threadId,
      workspace,
      procedureContext,
      connectionState,
      desktopAgentConnected,
      operations,
      approvalDisplay,
      pendingHumanInput,
    })
  }, [baseUrl, threadId, workspace, procedureContext, connectionState, desktopAgentConnected, operations, approvalDisplay, pendingHumanInput])

  useEffect(() => {
    const handleWorkspaceGovernanceUpdated = (_event: unknown, data: { workspace_id?: string } | null) => {
      void refreshWorkspace(data?.workspace_id)
    }

    window.ipcRenderer?.on('workspace-governance-updated', handleWorkspaceGovernanceUpdated)
    return () => {
      window.ipcRenderer?.off('workspace-governance-updated', handleWorkspaceGovernanceUpdated)
    }
  }, [refreshWorkspace])

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

      <StatusIsland 
        runtimeSnapshot={runtimeSnapshot}
        usageSnapshot={usageSnapshot}
        healthSnapshot={healthSnapshot}
      />

      <div className={styles.contentArea}>
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
