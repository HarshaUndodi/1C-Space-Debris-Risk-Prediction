import type { AlertItem } from '../types'
import { days, meters, oneInN } from '../format'

// Band bar maps log10 risk from LO..HI onto 0..100 %.
const LO = -12
const HI = -2
const pct = (r: number) => `${Math.min(100, Math.max(0, ((r - LO) / (HI - LO)) * 100))}%`

function RiskBand({ a }: { a: AlertItem }) {
  return (
    <div className="band" title={`P10 ${a.risk_p10.toFixed(2)} · P50 ${a.risk_p50.toFixed(2)} · P90 ${a.risk_p90.toFixed(2)} (log10 PoC)`}>
      <div className="band-marker band-hr" style={{ left: pct(-6) }} />
      <div className="band-marker band-trigger" style={{ left: pct(-4) }} />
      <div className={`band-range band-${a.decision.toLowerCase()}`}
        style={{ left: pct(a.risk_p10), width: `calc(${pct(a.risk_p90)} - ${pct(a.risk_p10)})` }} />
      <div className="band-p50" style={{ left: pct(a.risk_p50) }} />
    </div>
  )
}

export function AlertList({ alerts, selected, onSelect }: {
  alerts: AlertItem[]
  selected?: string | null
  onSelect?: (id: string) => void
}) {
  if (alerts.length === 0) return <div className="status">No alerts.</div>
  return (
    <ol className="alert-list">
      {alerts.map((a, i) => (
        <li key={a.event_id}
          className={`alert-row ${selected === a.event_id ? 'selected' : ''}`}
          onClick={() => onSelect?.(a.event_id)}>
          <span className="rank mono">{i + 1}</span>
          <span className={`decision decision-${a.decision.toLowerCase()}`}>{a.decision}</span>
          <div className="alert-main">
            <div className="alert-title">
              <span className="mono">EVT {a.event_id}</span>
              <span className="muted"> · {a.chaser_type} · {meters(a.miss_distance_m)}</span>
            </div>
            <RiskBand a={a} />
          </div>
          <div className="alert-nums">
            <div className="mono big">{oneInN(a.risk_p50)}</div>
            <div className="muted mono">TCA {days(a.time_to_tca_days)} · p<sub>high</sub> {a.p_high == null ? 'n/a' : a.p_high.toFixed(2)}</div>
          </div>
        </li>
      ))}
    </ol>
  )
}
