import { useState } from 'react'
import { api } from './api'
import { Header } from './components/Header'
import { VoiceAgent } from './components/VoiceAgent'
import { AlertDetailPage } from './pages/AlertDetail'
import { MetricsPage } from './pages/Metrics'
import { MissionControl } from './pages/MissionControl'
import { useRoute } from './router'
import type { Source } from './types'
import { useApi } from './useApi'

export default function App() {
  const route = useRoute()
  const [source, setSource] = useState<Source>('historical')
  const health = useApi(() => api.health(), [])

  return (
    <div className="app">
      <Header route={route.page} source={source} onSource={setSource} mode={health.data?.mode} />
      {route.page === 'mission' && <MissionControl source={source} />}
      {route.page === 'alert' && <AlertDetailPage id={route.id} />}
      {route.page === 'metrics' && <MetricsPage />}
      {health.error && <div className="api-down">{health.error}</div>}
      <VoiceAgent route={route} />
    </div>
  )
}
