import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import ContextWindow from './ContextWindow'
import Dashboard from './Dashboard'
import SettingsWindow from './SettingsWindow'
import StatsWindow from './StatsWindow'
import WorkspaceWindow from './WorkspaceWindow'
import './index.css'
import './memory.css'
import './dashboard.css'

const hash = window.location.hash;

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {hash === '#/dashboard' ? <Dashboard /> : hash === '#/settings' ? <SettingsWindow /> : hash === '#/workspace' ? <WorkspaceWindow /> : hash === '#/stats' ? <ContextWindow /> : hash === '#/devtools' ? <StatsWindow /> : <App />}
  </React.StrictMode>,
)
