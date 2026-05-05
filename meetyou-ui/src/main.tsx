import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import ContextWindow from './ContextWindow'
import DanxiWindow from './DanxiWindow'
import Dashboard from './Dashboard'
import SettingsWindow from './SettingsWindow'
import RuntimeDebugWindow from './StatsWindow'
import WorkspaceWindow from './WorkspaceWindow'
import { WINDOW_HASH_ALIAS, WINDOW_HASH_ROUTE } from './windowBridge'
import './index.css'
import './memory.css'
import './dashboard.css'

const ROUTE_COMPONENTS: Record<string, React.ReactNode> = {
  [WINDOW_HASH_ROUTE.dashboard]: <Dashboard />,
  [WINDOW_HASH_ROUTE.settings]: <SettingsWindow />,
  [WINDOW_HASH_ROUTE.workspace]: <WorkspaceWindow />,
  [WINDOW_HASH_ROUTE.danxi]: <DanxiWindow />,
  [WINDOW_HASH_ROUTE.context]: <ContextWindow />,
  [WINDOW_HASH_ROUTE.runtimeDebug]: <RuntimeDebugWindow />,
}

const hash = WINDOW_HASH_ALIAS[window.location.hash] ?? window.location.hash

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {ROUTE_COMPONENTS[hash] ?? <App />}
  </React.StrictMode>,
)
