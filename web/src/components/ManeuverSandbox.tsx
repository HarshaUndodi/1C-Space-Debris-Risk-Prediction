import { useEffect, useMemo, useState } from 'react'
import type { ManeuverResult } from '../types'
import { pcSci } from '../format'

const DIRECTIONS = [
  { id: '+along', label: '+Along (Prograde)', desc: 'Burns in direction of motion' },
  { id: '-along', label: '-Along (Retrograde)', desc: 'Burns opposite velocity' },
  { id: '+radial', label: '+Radial (Outward)', desc: 'Burns away from Earth' },
  { id: '-radial', label: '-Radial (Inward)', desc: 'Burns toward Earth' },
] as const

const LEAD_HOURS = [6, 12, 24, 36, 48, 72]

function calculatePropellant(dv_ms: number, m0_kg = 500, isp_s = 220) {
  const g0 = 9.80665
  return m0_kg * (1 - Math.exp(-dv_ms / (isp_s * g0))) * 1000
}

/** Interpolate post_pc from the precomputed grid for any dv */
function interpolatePc(points: ManeuverResult['points'], dv_ms: number, dir: string, lead_h: number, pre_pc: number): number {
  if (dv_ms <= 0) return pre_pc
  const filtered = points.filter((p) => p.direction === dir && p.burn_lead_h === lead_h)
  if (!filtered.length) return pre_pc

  filtered.sort((a, b) => a.dv_ms - b.dv_ms)
  if (dv_ms <= filtered[0].dv_ms) return filtered[0].post_pc
  if (dv_ms >= filtered[filtered.length - 1].dv_ms) return filtered[filtered.length - 1].post_pc

  // Find bounding interval
  for (let i = 0; i < filtered.length - 1; i++) {
    const p1 = filtered[i]
    const p2 = filtered[i + 1]
    if (dv_ms >= p1.dv_ms && dv_ms <= p2.dv_ms) {
      const logDv = Math.log10(dv_ms)
      const logDv1 = Math.log10(p1.dv_ms)
      const logDv2 = Math.log10(p2.dv_ms)
      const frac = (logDv - logDv1) / (logDv2 - logDv1)

      const logPc1 = Math.log10(Math.max(1e-30, p1.post_pc))
      const logPc2 = Math.log10(Math.max(1e-30, p2.post_pc))
      const logInterp = logPc1 + frac * (logPc2 - logPc1)
      return Math.pow(10, logInterp)
    }
  }
  return pre_pc
}

export function ManeuverSandbox({
  m,
  onPlanChange,
}: {
  m: ManeuverResult
  onPlanChange?: (plan: { dv_ms: number; direction: string; burn_lead_h: number; post_pc: number }) => void
}) {
  const rec = m.recommended
  const defaultDv = rec.dv_ms > 0 ? rec.dv_ms : 0.05
  const defaultDir = rec.direction || '+along'
  const defaultLead = rec.burn_lead_h || 24

  const [dv, setDv] = useState<number>(defaultDv)
  const [direction, setDirection] = useState<string>(defaultDir)
  const [leadH, setLeadH] = useState<number>(defaultLead)

  // Available lead times in this maneuver result
  const availableLeads = useMemo(() => {
    const set = new Set(m.points.map((p) => p.burn_lead_h))
    return LEAD_HOURS.filter((h) => set.has(h))
  }, [m.points])

  // Interpolated post_pc for current sandbox parameters
  const currentPostPc = useMemo(() => {
    const val = interpolatePc(m.points, dv, direction, leadH, m.pre_burn_pc)
    return Math.max(1e-15, val)
  }, [m.points, dv, direction, leadH, m.pre_burn_pc])

  // Propellant required
  const propG = useMemo(() => calculatePropellant(dv), [dv])

  // Estimated separation along-track / encounter plane
  const separationKm = useMemo(() => {
    // Secular CW drift: y ≈ 3 * n * t * dv_along. For LEO, n ≈ 0.0011 rad/s
    const isAlong = direction.includes('along')
    const n = 0.0011
    const tSec = leadH * 3600
    if (isAlong) {
      return (3 * n * tSec * dv) / 1000
    }
    // Radial burns produce oscillatory displacement ≈ 2 * dv / n
    return (2 * dv) / (n * 1000)
  }, [direction, leadH, dv])

  // Safety rating
  const isSafe = currentPostPc <= m.target_pc
  const isMarginal = !isSafe && currentPostPc < 1e-4

  // Risk reduction multiplier
  const riskReductionFactor = useMemo(() => {
    if (currentPostPc >= m.pre_burn_pc) return 1
    return Math.round(m.pre_burn_pc / currentPostPc)
  }, [m.pre_burn_pc, currentPostPc])

  // Minimal safe dv for current direction and timing
  const minSafePoint = useMemo(() => {
    const candidates = m.points.filter((p) => p.direction === direction && p.burn_lead_h === leadH && p.post_pc <= m.target_pc)
    if (!candidates.length) return null
    candidates.sort((a, b) => a.dv_ms - b.dv_ms)
    return candidates[0]
  }, [m.points, direction, leadH, m.target_pc])

  // Notify parent of active plan
  useEffect(() => {
    if (onPlanChange) {
      onPlanChange({ dv_ms: dv, direction, burn_lead_h: leadH, post_pc: currentPostPc })
    }
  }, [dv, direction, leadH, currentPostPc, onPlanChange])

  return (
    <div className="sandbox-panel">
      <div className="sandbox-header">
        <div className="sandbox-title-wrap">
          <span className="sandbox-icon">🎯</span>
          <div>
            <span className="sandbox-title">Interactive "What-If" Maneuver Simulator</span>
            <span className="sandbox-subtitle muted">Test custom thruster Δv budgets, thrust directions, and execution timing</span>
          </div>
        </div>
        <div className="sandbox-presets">
          {rec.dv_ms > 0 && (
            <button
              type="button"
              className="preset-btn"
              onClick={() => {
                setDv(rec.dv_ms)
                setDirection(rec.direction)
                setLeadH(rec.burn_lead_h)
              }}
              title="Reset to automated algorithm recommended burn"
            >
              Recommended Plan
            </button>
          )}
          {minSafePoint && (
            <button
              type="button"
              className="preset-btn"
              onClick={() => setDv(minSafePoint.dv_ms)}
              title="Set to minimum delta-v that meets safety threshold"
            >
              Min Safe ({minSafePoint.dv_ms.toPrecision(2)} m/s)
            </button>
          )}
          <button
            type="button"
            className="preset-btn"
            onClick={() => setDv(0.05)}
            title="Standard stationkeeping micro-burn"
          >
            0.05 m/s
          </button>
        </div>
      </div>

      <div className="sandbox-grid">
        {/* Left column: Controls */}
        <div className="sandbox-controls">
          {/* 1. Delta-v slider */}
          <div className="control-group">
            <div className="control-label-row">
              <label htmlFor="dv-slider" className="control-label">
                Impulsive Burn (Δv)
              </label>
              <span className="control-val mono">
                <b>{dv.toFixed(3)}</b> m/s
                <span className="muted small"> ({propG < 10 ? propG.toFixed(1) : propG.toFixed(0)} g fuel)</span>
              </span>
            </div>
            <input
              id="dv-slider"
              type="range"
              min="0.005"
              max="0.400"
              step="0.005"
              value={dv}
              onChange={(e) => setDv(parseFloat(e.target.value))}
              className="sandbox-slider"
            />
            <div className="slider-ticks mono muted small">
              <span>0.01 m/s</span>
              <span>0.10 m/s</span>
              <span>0.20 m/s</span>
              <span>0.40 m/s</span>
            </div>
          </div>

          {/* 2. Direction selection */}
          <div className="control-group">
            <span className="control-label">Thrust Vector Direction</span>
            <div className="direction-grid">
              {DIRECTIONS.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  className={`dir-btn ${direction === d.id ? 'active' : ''}`}
                  onClick={() => setDirection(d.id)}
                  title={d.desc}
                >
                  <span className="dir-name mono">{d.label}</span>
                  <span className="dir-desc muted small">{d.desc}</span>
                </button>
              ))}
            </div>
          </div>

          {/* 3. Execution timing */}
          <div className="control-group">
            <span className="control-label">Burn Execution Lead Time (Hours before TCA)</span>
            <div className="timing-btn-group">
              {availableLeads.map((h) => (
                <button
                  key={h}
                  type="button"
                  className={`lead-btn ${leadH === h ? 'active' : ''}`}
                  onClick={() => setLeadH(h)}
                >
                  <span className="mono">{h} h</span>
                  <span className="muted small">{h === 24 ? 'Nominal' : h === 6 ? 'Emergency' : ''}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Right column: Outcome & Physical metrics */}
        <div className="sandbox-outcome">
          <div className={`outcome-card ${isSafe ? 'card-safe' : isMarginal ? 'card-marginal' : 'card-hazard'}`}>
            <div className="outcome-top">
              <span className="outcome-status-badge">
                {isSafe ? '✓ SAFETY TARGET MET' : isMarginal ? '⚠️ MARGINAL RISK' : '⛔ HAZARD NOT CLEARED'}
              </span>
              <span className="outcome-dv mono">{dv.toPrecision(2)} m/s · {direction}</span>
            </div>

            <div className="outcome-stats">
              <div className="stat-block">
                <span className="stat-label muted">Residual Collision Risk</span>
                <span className={`stat-value mono ${isSafe ? 'text-green' : 'text-red'}`}>
                  {pcSci(currentPostPc)}
                </span>
                <span className="stat-sub muted small">Target: ≤ {pcSci(m.target_pc)}</span>
              </div>

              <div className="stat-block">
                <span className="stat-label muted">Risk Reduction Factor</span>
                <span className="stat-value mono text-cyan">
                  {riskReductionFactor > 1 ? `${riskReductionFactor.toLocaleString()}×` : '1×'}
                </span>
                <span className="stat-sub muted small">from initial {pcSci(m.pre_burn_pc)}</span>
              </div>

              <div className="stat-block">
                <span className="stat-label muted">Propellant Expended</span>
                <span className="stat-value mono">
                  {propG < 10 ? propG.toFixed(1) : propG.toFixed(0)} <small>grams</small>
                </span>
                <span className="stat-sub muted small">500 kg / Isp 220 s hydrazine</span>
              </div>

              <div className="stat-block">
                <span className="stat-label muted">Separation Generated</span>
                <span className="stat-value mono">
                  ≈ {separationKm >= 1 ? `${separationKm.toFixed(1)} km` : `${(separationKm * 1000).toFixed(0)} m`}
                </span>
                <span className="stat-sub muted small">CW relative displacement at TCA</span>
              </div>
            </div>

            <div className="outcome-advisory">
              {leadH <= 6 ? (
                <span className="advisory-text warn">
                  ⏱️ <b>Late Execution Penalty:</b> Burning only 6 h before TCA requires significantly more Δv to achieve clearance because secular along-track drift has less time to accumulate.
                </span>
              ) : isSafe ? (
                <span className="advisory-text">
                  ✓ <b>Clean Maneuver:</b> This {dv.toPrecision(2)} m/s burn clears the conjunction safely below the 1-in-a-million threshold while consuming only {propG.toFixed(0)} g of propellant.
                </span>
              ) : (
                <span className="advisory-text text-red">
                  ⚠️ <b>Insufficient Δv:</b> Residual risk remains at {pcSci(currentPostPc)}. Increase Δv to at least {minSafePoint ? `${minSafePoint.dv_ms.toPrecision(2)} m/s` : '0.10 m/s'} or burn earlier.
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
