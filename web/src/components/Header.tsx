import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Source } from '../types'
import { useApi } from '../useApi'

function UtcClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return <span className="clock mono">{now.toISOString().slice(0, 19).replace('T', ' ')} UTC</span>
}

function SpaceWeatherChip() {
  const sw = useApi(() => api.spaceWeather(), [])
  if (sw.loading) return <span className="chip">SW …</span>
  if (sw.error || !sw.data) return <span className="chip chip-muted" title={sw.error ?? ''}>SW n/a</span>
  const elevated = sw.data.heuristic_drag_flag === 'elevated'
  return (
    <span className={`chip ${elevated ? 'chip-amber' : ''}`}
      title={`Space weather ${sw.data.date}. Drag-uncertainty flag is a heuristic (Ap ≥ 30 or F10.7 ≥ 200).`}>
      <span className="mono">F10.7 {sw.data.f107.toFixed(0)} · Ap {sw.data.ap}</span>
      <span className="chip-sub">drag uncertainty: {sw.data.heuristic_drag_flag}</span>
    </span>
  )
}

export function Header({ source, onSource, mode }: { source: Source; onSource: (s: Source) => void; mode?: string }) {
  return (
    <header className="header">
      <div className="logo">
        <span className="logo-mark">◎</span> ORBIT<span className="logo-accent">GUARD</span>
        {mode === 'mock' && <span className="badge badge-mock" title="API is serving mock data (Milestone 0)">MOCK DATA</span>}
      </div>
      <div className="header-right">
        <SpaceWeatherChip />
        <div className="toggle" role="tablist">
          <button className={source === 'historical' ? 'active' : ''} onClick={() => onSource('historical')}>
            Historical (ESA CDMs)
          </button>
          <button className={source === 'live' ? 'active' : ''} onClick={() => onSource('live')}>
            Live (CelesTrak)
          </button>
        </div>
        <UtcClock />
      </div>
    </header>
  )
}
