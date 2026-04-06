import { useState } from 'react'
import { useMeetYou } from './hooks/useMeetYou'
import Titlebar from './components/layout/Titlebar'
import StatusStrip from './components/status/StatusStrip'
import UsagePanel from './components/status/UsagePanel'
import MessageList from './components/chat/MessageList'
import ChatInput from './components/input/ChatInput'
import { AssistantMode, ThinkingOverride } from './types'
import { getUsagePillText } from './utils/statusFormatting'
import styles from './App.module.css'

export default function App() {
  const {
    messages,
    sendMessage,
    connectionState,
    connected,
    runtimeSnapshot,
    usageSnapshot,
    runtimeDebugSnapshot,
    turnActivities,
    confirmRequest,
    pendingHumanInput,
    healthSnapshot,
    lastAck,
    lastError,
    archivedTurnCount,
    sendConfirmResponse,
    sendHumanInputResponse,
  } = useMeetYou('http://127.0.0.1:8000')

  const [inputVal, setInputVal] = useState('')
  const [isPinned, setIsPinned] = useState(true)
  const [usagePanelOpen, setUsagePanelOpen] = useState(false)
  const [thinkingOverride, setThinkingOverride] = useState<ThinkingOverride>('default')
  const [preferredMode, setPreferredMode] = useState<AssistantMode>('normal')

  const usagePillText = usageSnapshot && !usageSnapshot.usage_ready
    ? '初始化...'
    : getUsagePillText(usageSnapshot)

  const togglePin = () => {
    const nextPinned = !isPinned
    setIsPinned(nextPinned)
    window.ipcRenderer?.send('window-toggle-top', nextPinned)
  }

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
        isPinned={isPinned}
        usagePanelOpen={usagePanelOpen}
        usagePillText={usagePillText}
        onTogglePin={togglePin}
        onToggleUsagePanel={() => setUsagePanelOpen(!usagePanelOpen)}
      />

      <div className={styles.statusBarContainer}>
        {usagePanelOpen && (
          <UsagePanel usageSnapshot={usageSnapshot} runtimeDebugSnapshot={runtimeDebugSnapshot} />
        )}

        <StatusStrip
          connectionState={connectionState}
          runtimeSnapshot={runtimeSnapshot}
          healthSnapshot={healthSnapshot}
          turnActivities={turnActivities}
        />
      </div>

      <div className={styles.contentArea}>
        <MessageList
          connected={connected}
          messages={messages}
          runtimeSnapshot={runtimeSnapshot}
          runtimeDebugSnapshot={runtimeDebugSnapshot}
          healthSnapshot={healthSnapshot}
          lastAck={lastAck}
          lastError={lastError}
          archivedTurnCount={archivedTurnCount}
          confirmRequest={confirmRequest}
          pendingHumanInput={pendingHumanInput}
          sendConfirmResponse={sendConfirmResponse}
          sendHumanInputResponse={sendHumanInputResponse}
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
      />
    </div>
  )
}
