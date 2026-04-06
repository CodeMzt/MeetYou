import { useState, useEffect } from 'react'
import { useMeetYou } from './hooks/useMeetYou'
import Titlebar from './components/layout/Titlebar'
import StatusIsland from './components/status/StatusIsland'
import MessageList from './components/chat/MessageList'
import ChatInput from './components/input/ChatInput'
import { AssistantMode, ThinkingOverride } from './types'
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
    confirmRequest,
    pendingHumanInput,
    healthSnapshot,
    lastError,
    archivedTurnCount,
    sendConfirmResponse,
    sendHumanInputResponse,
    sendControlCommand,
  } = useMeetYou('http://127.0.0.1:8000')

  const [inputVal, setInputVal] = useState('')
  const [isPinned, setIsPinned] = useState(true)
  const [thinkingOverride, setThinkingOverride] = useState<ThinkingOverride>('default')
  const [preferredMode, setPreferredMode] = useState<AssistantMode>('normal')

  const togglePin = () => {
    const nextPinned = !isPinned
    setIsPinned(nextPinned)
    window.ipcRenderer?.send('window-toggle-top', nextPinned)
  }

  useEffect(() => {
    window.ipcRenderer?.send('update-stats', { usageSnapshot, runtimeDebugSnapshot })
  }, [usageSnapshot, runtimeDebugSnapshot])

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
        onTogglePin={togglePin}
        onToggleUsagePanel={() => window.ipcRenderer?.send('open-stats')}
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
          runtimeSnapshot={runtimeSnapshot}
          runtimeDebugSnapshot={runtimeDebugSnapshot}
          healthSnapshot={healthSnapshot}
          lastError={lastError}
          archivedTurnCount={archivedTurnCount}
          confirmRequest={confirmRequest}
          pendingHumanInput={pendingHumanInput}
          sendConfirmResponse={sendConfirmResponse}
          sendHumanInputResponse={sendHumanInputResponse}
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
      />
    </div>
  )
}
