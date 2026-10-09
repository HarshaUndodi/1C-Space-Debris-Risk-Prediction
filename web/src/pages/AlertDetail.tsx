import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { CdmHistoryChart } from '../charts/CdmHistoryChart'
import { ManeuverChart } from '../charts/ManeuverChart'
import { ShapChart } from '../charts/ShapChart'
import { ErrorBox, Loading } from '../components/Status'
import { days, meters, oneInN, pcSci } from '../format'
import { countdown, useNow } from '../live'
import { CountUp, Typewriter } from '../motion'
import { exportHtml, exportJson } from '../report'
import { go } from '../router'
import type { ManeuverResult } from '../types'
import { useApi } from '../useApi'

function ManeuverSummary({ m }: { m: ManeuverResult }) {
  const r = m.recommended
  // Pitch line: what the same burn would buy if executed only 6 h before TCA.
  const late = useMemo(() => {
    if (r.dv_ms <= 0) return null
    const same = m.points.find((p) => p.direction === r.direction && Math.abs(p.dv_ms - r.dv_ms) < 1e-9 && p.burn_lead_h === 6)
    const ok6 = m.points.filter((p) => p.burn_lead_h === 6 && p.post_pc <= m.target_pc).sort((a, b) => a.dv_ms - b.dv_ms)[0]
    return { same, ok6 }
  }, [m, r])
  if (r.dv_ms <= 0) return <p className="man-text">{m.note ?? 'No burn needed.'}</p>
  return (
    <div className="man-text">
      <p>
        <b>Recommended:</b> <span className="mono">{r.dv_ms.toPrecision(2)} m/s {r.direction}</span>,{' '}
        <span className="mono">{r.burn_lead_h} h</span> before TCA → Pc <span className="mono">{pcSci(r.post_pc)}</span>{' '}
        (≈ <span className="mono">{r.propellant_g < 10 ? r.propellant_g.toFixed(1) : r.propellant_g.toFixed(0)} g</span> propellant)
        {!m.target_met && <span className="warn"> — target not reachable in the search grid</span>}
      </p>
      {late && r.burn_lead_h > 6 && (
        <p className="muted">
          Same burn only 6 h out: Pc {late.same ? pcSci(late.same.post_pc) : '—'}
          {late.ok6 ? ` · cheapest burn meeting the target at 6 h: ${late.ok6.dv_ms.toPrecision(2)} m/s (${(late.ok6.dv_ms / r.dv_ms).toFixed(1)}× the Δv)` : ' · no burn in the grid meets the target at 6 h'}
        </p>
      )}
      <p className="muted small">
        Pre-burn Pc {pcSci(m.pre_burn_pc)} · {m.secondary_check.applicable
          ? `${m.secondary_check.new_conjunctions.length} new conjunctions < 5 km after the burn`
          : `secondary-conjunction check: ${m.secondary_check.note ?? 'not applicable'}`}
      </p>
    </div>
  )
}

export function AlertDetailPage({ id }: { id: string }) {
  const [cutoff, setCutoff] = useState(2)
  const detail = useApi(() => api.alert(id, cutoff), [id, cutoff])
  const man = useApi(() => api.maneuver(id), [id])
  const d = detail.data
  const live = d?.source === 'live'
  const cutoffs = useMemo(() => (d ? [...d.available_cutoffs].sort((a, b) => b - a) : [6, 5, 4, 3, 2]), [d])
  const now = useNow(1000)
  // Live events: TCA as an absolute time (time_to_tca_days is relative to when the detail was fetched).
  const tcaAt = useMemo(() => (d && live ? new Date(Date.now() + d.time_to_tca_days * 86400e3).toISOString() : null), [d, live])

  useEffect(() => { setCutoff(2) }, [id])

  return (
    <main className="detail">
      <div className="detail-top">
        <button className="ghost" onClick={go.mission}>← Alerts</button>
        {d && (
          <>
            <h1 className="mono">{live ? 'LIVE' : 'EVT'} {live ? d.event_id.replace(/^live-/, '') : d.event_id}</h1>
            <span className={`decision decision-${d.decision.toLowerCase()} big`}>{d.decision}</span>
            <span className="muted">{d.chaser_type} · {live ? 'live screening (CelesTrak, estimated Pc)' : 'ESA Kelvins (held-out)'}</span>
            <div className="spacer" />
            <button className="ghost" onClick={() => exportHtml(d, man.data, cutoff)}>Export report (HTML)</button>
            <button className="ghost" onClick={() => exportJson(d, man.data, cutoff)}>JSON</button>
          </>
        )}
      </div>

      {detail.error && <ErrorBox message={detail.error} onRetry={detail.reload} />}
      {!d && detail.loading && <Loading what="alert" />}

      {d && (
        <>
          <section className="panel replay enter">
            {cutoffs.length > 0 && (
              <div className="replay-row">
                <label htmlFor="replay" className="panel-label">Replay — “now” is</label>
                <input id="replay" type="range" min={0} max={cutoffs.length - 1} step={1}
                  value={Math.max(0, cutoffs.indexOf(cutoff))}
                  onChange={(e) => setCutoff(cutoffs[Number(e.target.value)])} />
                <span className="mono big">{cutoff} days before TCA</span>
                {detail.loading && <span className="muted small">updating…</span>}
              </div>
            )}
            <div className="kpis">
              <div><span className="kpi-label">{live ? 'Pc (estimated)' : 'P(high risk), calibrated'}</span>
                <span className="mono kpi">{d.p_high == null ? pcSci(Math.pow(10, d.risk_p50))
                  : <CountUp value={d.p_high} format={(v) => v.toFixed(3)} />}</span></div>
              <div><span className="kpi-label">Final risk P50</span>
                <span className="mono kpi"><CountUp value={d.risk_p50} format={oneInN} duration={1100} /></span></div>
              <div><span className="kpi-label">Band P10–P90</span><span className="mono kpi small">{oneInN(d.risk_p10)} … {oneInN(d.risk_p90)}</span></div>
              {!live && <div><span className="kpi-label">Baseline (latest CDM)</span>
                <span className="mono kpi"><CountUp value={d.baseline_risk} format={oneInN} duration={1100} /></span></div>}
              <div><span className="kpi-label">Miss distance</span>
                <span className="mono kpi"><CountUp value={d.miss_distance_m} format={meters} /></span></div>
              <div><span className="kpi-label">{live ? 'TCA in' : 'Latest CDM'}</span>
                <span className="mono kpi">{live && tcaAt ? <span className="tick">{countdown(tcaAt, now)}</span> : `${days(d.time_to_tca_days)} out`}</span></div>
              {d.true_final_risk != null && (
                <div><span className="kpi-label">Actual outcome</span>
                  <span className="mono kpi"><CountUp value={d.true_final_risk} format={oneInN} duration={1300} /></span></div>
              )}
            </div>
          </section>

          <div className="detail-grid">
            <section className="panel enter" style={{ animationDelay: '80ms' }}>
              <div className="panel-title">CDM history · risk vs time to TCA</div>
              <div className="panel-body">
                {d.cdm_history.length ? <CdmHistoryChart d={d} cutoff={cutoff} /> : (
                  <div className="status">No CDMs for live screening: catalog elements carry no covariance, so Pc is
                    estimated with assumed, age-grown position sigmas (band = sigmas ×0.5 … ×2).</div>
                )}
              </div>
            </section>
            <section className="panel enter" style={{ animationDelay: '160ms' }}>
              <div className="panel-title">Why flagged · top SHAP drivers</div>
              <div className="panel-body">
                {d.shap_top.length ? <ShapChart items={d.shap_top} /> : (
                  <div className="status">The trained risk model runs on CDMs; live mode is screening only, so there are
                    no model drivers. Geometry: miss {meters(d.miss_distance_m)}, {d.chaser_type.toLowerCase()}.</div>
                )}
              </div>
            </section>
            <section className="panel enter" style={{ animationDelay: '240ms' }}>
              <div className="panel-title">Operator briefing <span className="muted">· {d.briefing_source === 'llm' ? 'LLM' : 'template'}</span></div>
              <pre className="terminal" aria-label={d.briefing.join(' ')}>
                <Typewriter lines={d.briefing} render={(text, _i, full) => {
                  const tag = full.match(/^\[(\w+)\]/)?.[1] ?? ''
                  return <span className={`brief-${tag.toLowerCase()}`}>{text}</span>
                }} />
              </pre>
            </section>
            <section className="panel enter" style={{ animationDelay: '320ms' }}>
              <div className="panel-title">Avoidance maneuver · residual Pc vs Δv <span className="muted">({live ? 'burn options from now' : 'decision at 2 d'})</span></div>
              <div className="panel-body">
                {man.loading && <Loading what="maneuver options" />}
                {man.error && <div className="status">Maneuver not available for this event ({man.error.includes('404') ? 'incomplete covariance in its CDM' : man.error}).</div>}
                {man.data && <><ManeuverChart m={man.data} /><ManeuverSummary m={man.data} /></>}
              </div>
            </section>
          </div>
        </>
      )}
    </main>
  )
}
