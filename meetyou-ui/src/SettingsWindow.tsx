import { Settings } from 'lucide-react'
import './dashboard.css'
import SettingsView from './views/SettingsView'
import SubWindow from './components/layout/SubWindow'

export default function SettingsWindow() {
  return (
    <SubWindow title="设置中心" icon={<Settings size={16} />} contentStyle={{ padding: 0 }}>
      <SettingsView />
    </SubWindow>
  )
}
