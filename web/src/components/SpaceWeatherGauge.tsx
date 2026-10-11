import { useState } from 'react'
import type { SpaceWeather } from '../types'

export function SpaceWeatherGauge({ data, onClose }: { data: SpaceWeather | null; onClose?: () => void }) {
  const [simulated, setSimulated] = useState(false)

  if (!data) return null

  // Active values (live or simulated extreme storm)
  const f107 = simulated ? 275.0 : data.f107
  const ap = simulated ? 180.0 : data.ap
  const noaaScale = simulated ? 'G4 (Severe Solar Storm)' : (data.noaa_scale ?? 'G0 (Quiet)')
  const densityMult = simulated ? 3.85 : (data.density_multiplier ?? 1.5)
  const dragUncertainty = simulated ? 136.0 : (data.drag_uncertainty_pct ?? 24.0)
  const isElevated = simulated || data.heuristic_drag_flag === 'elevated' || ap >= 30 || f107 >= 180

  const impact = simulated
    ? 'Extreme Coronal Mass Ejection: Upper thermosphere expanding rapidly. LEO orbits (<500 km) experience 3.8× atmospheric drag. Along-track position error grows by >130%, causing massive false-alarm spikes in conjunction screening.'
    : (data.leo_impact ?? 'Nominal thermospheric conditions. Ephemeris confidence high across Low Earth Orbit.')

  // Percentages for gauge bars (F10.7: 60 to 300, Ap: 0 to 200)
  const f107Pct = Math.min(100, Math.max(0, ((f107 - 60) / 240) * 100))
  const apPct = Math.min(100, Math.max(0, (ap / 160) * 100))

  return (
    <div className={`sw-card ${isElevated ? 'sw-elevated' : 'sw-nominal'}`}>
      <div className="sw-header">
        <div className="sw-title-wrap">
          <span className="sw-badge-pulse" />
          <span className="sw-title">Solar Activity & Atmospheric Drag</span>
          <span className={`sw-noaa-badge ${isElevated ? 'noaa-storm' : 'noaa-quiet'}`}>
            {noaaScale}
          </span>
        </div>
        <div className="sw-actions">
          <button
            type="button"
            className={`sim-storm-btn ${simulated ? 'active' : ''}`}
            onClick={() => setSimulated(!simulated)}
            title="Simulate conditions during a G4/G5 Extreme Solar Storm"
          >
            {simulated ? '↺ Reset Live' : '⚡ Simulate G4 Storm'}
          </button>
          {onClose && (
            <button type="button" className="sw-close" onClick={onClose} aria-label="Close gauge">
              ×
            </button>
          )}
        </div>
      </div>

      <div className="sw-metrics-grid">
        {/* Metric 1: Solar Radio Flux F10.7 */}
        <div className="sw-metric-box">
          <div className="sw-metric-top">
            <span className="sw-label">Solar Radio Flux (F10.7)</span>
            <span className="sw-val mono">{f107.toFixed(1)} <small>sfu</small></span>
          </div>
          <div className="sw-meter-bar">
            <div
              className={`sw-meter-fill ${f107 >= 200 ? 'meter-red' : f107 >= 140 ? 'meter-amber' : 'meter-green'}`}
              style={{ width: `${f107Pct}%` }}
            />
          </div>
          <div className="sw-meter-labels muted mono small">
            <span>60 Quiet</span>
            <span>150 Active</span>
            <span>300 Storm</span>
          </div>
        </div>

        {/* Metric 2: Planetary Geomagnetic Ap Index */}
        <div className="sw-metric-box">
          <div className="sw-metric-top">
            <span className="sw-label">Geomagnetic Index (Ap)</span>
            <span className="sw-val mono">{ap.toFixed(0)} <small>nT</small></span>
          </div>
          <div className="sw-meter-bar">
            <div
              className={`sw-meter-fill ${ap >= 50 ? 'meter-red' : ap >= 30 ? 'meter-amber' : 'meter-green'}`}
              style={{ width: `${apPct}%` }}
            />
          </div>
          <div className="sw-meter-labels muted mono small">
            <span>0 Quiet</span>
            <span>30 G1 Minor</span>
            <span>150+ G4 Severe</span>
          </div>
        </div>

        {/* Metric 3: Thermospheric Density Multiplier */}
        <div className="sw-metric-box highlight-box">
          <span className="sw-label">Thermospheric Density Multiplier</span>
          <div className="sw-big-stat mono">
            {densityMult.toFixed(2)}×
            <span className="sw-substat muted">vs quiet Sun</span>
          </div>
          <p className="sw-stat-note">Relative thermospheric mass density at 400–500 km altitude.</p>
        </div>

        {/* Metric 4: Covariance Drag Uncertainty Inflation */}
        <div className="sw-metric-box highlight-box">
          <span className="sw-label">Along-Track Error Inflation</span>
          <div className={`sw-big-stat mono ${dragUncertainty > 50 ? 'warn-red' : 'warn-amber'}`}>
            +{dragUncertainty.toFixed(0)}%
            <span className="sw-substat muted">σT uncertainty</span>
          </div>
          <p className="sw-stat-note">In-track positional covariance error growth due to density fluctuations.</p>
        </div>
      </div>

      {/* 7-Day Solar Flux Trend Sparkline */}
      {data.history_7d && data.history_7d.length > 0 && !simulated && (
        <div className="sw-trend-section">
          <div className="sw-trend-title muted small">7-Day Observed Solar Flux & Geomagnetic Trend:</div>
          <div className="sw-sparkline">
            {data.history_7d.map((h) => {
              const height = Math.min(100, Math.max(15, ((h.f107 - 70) / 100) * 100))
              const isSpike = h.ap >= 30 || h.f107 >= 140
              return (
                <div key={h.date} className="sw-trend-bar-col" title={`${h.date}: F10.7 ${h.f107} sfu · Ap ${h.ap}`}>
                  <div
                    className={`sw-trend-bar ${isSpike ? 'trend-spike' : ''}`}
                    style={{ height: `${height}%` }}
                  />
                  <span className="sw-trend-date mono">{h.date.slice(8)}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Operational LEO Advisory */}
      <div className={`sw-advisory ${isElevated ? 'advisory-elevated' : 'advisory-nominal'}`}>
        <span className="advisory-icon">{isElevated ? '⚠️' : '✓'}</span>
        <div className="advisory-body">
          <b>LEO Operator Advisory:</b> {impact}
        </div>
      </div>
    </div>
  )
}
