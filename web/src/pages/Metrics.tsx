import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '../api'
import { C, anim, axisProps, tooltipStyle } from '../charts/theme'
import { CountUp } from '../motion'
import { ErrorBox, Loading } from '../components/Status'
import type { Metrics } from '../types'
import { useApi } from '../useApi'

const f = (v: number | null | undefined, d = 3) => (v == null || !Number.isFinite(v) ? '—' : v.toFixed(d))
const pct = (v: number | null | undefined) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)

/** Animated number for tiles: counts up to the value, '—' when missing. */
const n = (v: number | null | undefined, fmt: (x: number) => string) =>
  v == null || !Number.isFinite(v) ? '—' : <CountUp value={v} format={fmt} duration={1200} />
const pctFmt = (v: number) => `${(v * 100).toFixed(1)}%`
const dec = (d: number) => (v: number) => v.toFixed(d)

function Tile({ label, model, baseline, better, note, i = 0 }: {
  label: string; model: React.ReactNode; baseline: React.ReactNode; better?: 'model' | 'baseline' | 'tie'; note?: string; i?: number
}) {
  return (
    <div className="tile enter" style={{ animationDelay: `${i * 90}ms` }}>
      <div className="tile-label">{label}</div>
      <div className="tile-row">
        <div><span className="tile-who" style={{ color: C.series1 }}>■</span> model <span className="mono tile-val">{model}</span></div>
        <div><span className="tile-who" style={{ color: C.series2 }}>▲</span> baseline <span className="mono tile-val">{baseline}</span></div>
      </div>
      {better && <div className={`tile-verdict v-${better}`}>{better === 'tie' ? 'tie' : `${better} better`}</div>}
      {note && <div className="tile-note">{note}</div>}
    </div>
  )
}

function verdict(m: number | null | undefined, b: number | null | undefined, lowerIsBetter: boolean, tol = 0.01): 'model' | 'baseline' | 'tie' | undefined {
  if (m == null || b == null || !Number.isFinite(m) || !Number.isFinite(b)) return undefined
  if (Math.abs(m - b) <= tol * Math.max(Math.abs(m), Math.abs(b), 1e-9)) return 'tie'
  return (lowerIsBetter ? m < b : m > b) ? 'model' : 'baseline'
}

function Reliability({ m }: { m: Metrics }) {
  const rel = m.reliability
  if (!rel) return <div className="status">No reliability data (mock mode).</div>
  const series = [
    { key: 'model_calibrated', name: 'model (isotonic)', color: C.series1, data: rel.model_calibrated },
    { key: 'baseline_logistic', name: 'baseline (logistic of latest risk)', color: C.series2, data: rel.baseline_logistic },
  ]
  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart margin={{ top: 12, right: 24, bottom: 8, left: 4 }}>
        <CartesianGrid stroke={C.grid} />
        {/* sqrt axes: most events have small probabilities; a linear axis piles every bin onto the origin */}
        <XAxis type="number" dataKey="p_mean" domain={[0, 1]} scale="sqrt" ticks={[0, 0.01, 0.05, 0.1, 0.25, 0.5, 1]} {...axisProps}
          label={{ value: 'predicted P(high risk) · √ scale', position: 'insideBottomRight', offset: -4, fill: C.muted, fontSize: 12 }} />
        <YAxis type="number" dataKey="frac_pos" domain={[0, 1]} scale="sqrt" ticks={[0, 0.01, 0.05, 0.1, 0.25, 0.5, 1]} {...axisProps} width={44} />
        <Tooltip {...tooltipStyle} formatter={(v: unknown) => Number(v).toFixed(3)} labelFormatter={(v: unknown) => `predicted ${Number(v).toFixed(3)}`} />
        <Legend wrapperStyle={{ fontSize: 12, color: C.ink2 }} />
        <Line data={[{ p_mean: 0, frac_pos: 0 }, { p_mean: 1, frac_pos: 1 }]} dataKey="frac_pos" name="perfectly calibrated"
          stroke={C.muted} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
        {series.map((s) => (
          <Line key={s.key} data={s.data} dataKey="frac_pos" name={s.name} stroke={s.color} strokeWidth={2}
            dot={{ r: 4, fill: s.color, stroke: C.surface, strokeWidth: 2 }} {...anim(200 + series.indexOf(s) * 300, 1300)} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

function LeadTime({ m, field, label }: { m: Metrics; field: 'recall' | 'far'; label: string }) {
  const data = m.lead_time.map((p) => ({
    d: p.cutoff_days,
    model: field === 'recall' ? p.model_recall : p.model_far,
    baseline: field === 'recall' ? p.baseline_recall : p.baseline_far,
  }))
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 12, right: 24, bottom: 8, left: 4 }}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="d" type="number" domain={[1.5, 6.5]} reversed ticks={m.lead_time.map((p) => p.cutoff_days)} {...axisProps}
          label={{ value: 'days before TCA', position: 'insideBottomRight', offset: -4, fill: C.muted, fontSize: 12 }} />
        <YAxis domain={[0, 1]} {...axisProps} width={44} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} />
        <Tooltip {...tooltipStyle} formatter={(v: unknown) => pct(Number(v))} labelFormatter={(v: unknown) => `${v} days before TCA`} />
        <Legend wrapperStyle={{ fontSize: 12, color: C.ink2 }} />
        <Line dataKey="model" name={`model ${label}`} stroke={C.series1} strokeWidth={2}
          dot={{ r: 4, fill: C.series1, stroke: C.surface, strokeWidth: 2 }} {...anim(200, 1300)} />
        <Line dataKey="baseline" name={`baseline ${label}`} stroke={C.series2} strokeWidth={2} strokeDasharray="6 3"
          dot={{ r: 4, fill: C.series2, stroke: C.surface, strokeWidth: 2 }} {...anim(500, 1300)} />
      </LineChart>
    </ResponsiveContainer>
  )
}

export function MetricsPage() {
  const q = useApi(() => api.metrics(), [])
  const m = q.data
  if (q.loading) return <main className="metrics"><Loading what="metrics" /></main>
  if (q.error || !m) return <main className="metrics"><ErrorBox message={q.error ?? 'no data'} onRetry={q.reload} /></main>
  const r = m.ranking
  const far = r?.far_at_recall_diagnostic ?? {}
  return (
    <main className="metrics">
      <h1>Proof · held-out ESA test set</h1>
      <p className="muted">
        {m.n_test_events.toLocaleString()} test events, <b>{m.n_test_high_risk}</b> high-risk (PoC ≥ 1e-6) ·
        decisions {m.cutoff_days} days before TCA · trained on {m.n_train_events?.toLocaleString() ?? '—'} events
        ({m.n_train_high_risk ?? '—'} high-risk){m.is_mock ? ' · MOCK DATA — run the pipeline' : ''}
      </p>

      <div className="tiles">
        <Tile i={0} label={`Recall on high-risk at tau (n=${m.n_test_high_risk})`} model={n(m.model.recall, pctFmt)}
          baseline={n(m.baseline_at_95_recall_level?.recall, pctFmt)} better={verdict(m.model.recall, m.baseline_at_95_recall_level?.recall, false)}
          note="both at their own ≥95%-recall operating point, chosen on training data" />
        <Tile i={1} label="False-alarm rate at tau" model={n(m.model.false_alarm_rate, pctFmt)}
          baseline={n(m.baseline_at_95_recall_level?.false_alarm_rate, pctFmt)}
          better={verdict(m.model.false_alarm_rate, m.baseline_at_95_recall_level?.false_alarm_rate, true)}
          note="fraction of low-risk events flagged" />
        <Tile i={2} label="Brier score (lower = better)" model={n(m.model.brier, dec(4))} baseline={n(m.baseline.brier, dec(4))}
          better={verdict(m.model.brier, m.baseline.brier, true)} note={`uncalibrated model ${f(m.model.brier_uncalibrated, 4)}`} />
        <Tile i={3} label="AUC-PR (ranking, threshold-free)" model={n(r?.auc_pr_model, dec(3))} baseline={n(r?.auc_pr_baseline, dec(3))}
          better={verdict(r?.auc_pr_model, r?.auc_pr_baseline, false)} note={`ROC-AUC ${f(r?.roc_auc_model)} vs ${f(r?.roc_auc_baseline)}`} />
        <Tile i={4} label="Kelvins score L = MSE_HR / F2 (lower = better)" model={n(m.model.kelvins_score, dec(3))}
          baseline={n(m.baseline_clipped?.kelvins_score ?? m.baseline.kelvins_score, dec(3))}
          better={verdict(m.model.kelvins_score, m.baseline_clipped?.kelvins_score ?? m.baseline.kelvins_score, true)}
          note={`baseline = latest CDM floored at 1e-6.5; raw latest CDM scores ${f(m.baseline.kelvins_score)}`} />
        <Tile i={5} label="P10–P90 band coverage" model={n(m.model.band_coverage_p10_p90, pctFmt)} baseline="n/a"
          note="target ≈ 80%; most events sit at the risk floor, which inflates coverage" />
      </div>

      <div className="metrics-grid">
        <section className="panel">
          <div className="panel-title">Lead time · recall of high-risk events</div>
          <div className="panel-body"><LeadTime m={m} field="recall" label="recall" /></div>
        </section>
        <section className="panel">
          <div className="panel-title">Lead time · false-alarm rate</div>
          <div className="panel-body"><LeadTime m={m} field="far" label="false alarms" /></div>
        </section>
        <section className="panel">
          <div className="panel-title">Reliability · does a predicted p happen p of the time?</div>
          <div className="panel-body"><Reliability m={m} /></div>
        </section>
        <section className="panel">
          <div className="panel-title">False alarms at matched recall (diagnostic)</div>
          <div className="panel-body">
            <table className="tbl">
              <thead><tr><th>recall</th><th>model FAR</th><th>baseline FAR</th></tr></thead>
              <tbody>
                {Object.entries(far).map(([k, v]) => (
                  <tr key={k}><td className="mono">{pct(Number(k))}</td><td className="mono">{pct(v.model)}</td>
                    <td className="mono">{v.baseline >= 0.999 ? '100% (cannot reach)' : pct(v.baseline)}</td></tr>
                ))}
              </tbody>
            </table>
            <p className="muted small">Thresholds here are set on the test set itself, so this table compares curves, not deployable operating points.</p>
          </div>
        </section>
        <section className="panel">
          <div className="panel-title">Global drivers · mean |SHAP|</div>
          <div className="panel-body">
            {m.shap_global ? (
              <ResponsiveContainer width="100%" height={36 + 26 * Math.min(10, m.shap_global.length)}>
                <BarChart data={m.shap_global.slice(0, 10)} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
                  <CartesianGrid stroke={C.grid} horizontal={false} />
                  <XAxis type="number" {...axisProps} />
                  <YAxis type="category" dataKey="label" width={240} {...axisProps} tick={{ fill: C.ink2, fontSize: 12 }} />
                  <Tooltip {...tooltipStyle} formatter={(v: unknown) => Number(v).toFixed(3)} />
                  <Bar dataKey="mean_abs_shap" name="mean |SHAP|" fill={C.series1} radius={4} {...anim(300, 1100)} />
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="status">No SHAP data (mock mode).</div>}
          </div>
        </section>
        <section className="panel">
          <div className="panel-title">Physics validation & throughput</div>
          <div className="panel-body stat-list">
            <div><span className="kpi-label">Pc engine vs ESA risk · Spearman</span>
              <span className="mono kpi">{f(m.pc_validation?.spearman_all)}</span>
              <span className="muted small">{m.pc_validation ? `${m.pc_validation.n_cdms.toLocaleString()} CDMs · ${pct(m.pc_validation.within_1_order_of_magnitude)} within 10×` : 'not run'}</span></div>
            <div><span className="kpi-label">Catalog screening</span>
              <span className="mono kpi">{m.screening.seconds ? `${m.screening.seconds.toFixed(1)} s` : '—'}</span>
              <span className="muted small">{m.screening.objects.toLocaleString()} objects · {m.screening.hours} h · {m.screening.step_s} s steps{m.screening.primary ? ` · primary ${m.screening.primary}` : ''}</span></div>
            {m.screening.all_vs_all && (
              <div><span className="kpi-label">All-vs-all (every LEO pair, sampled)</span>
                <span className="mono kpi">{m.screening.all_vs_all.seconds.toFixed(0)} s</span>
                <span className="muted small">{m.screening.all_vs_all.objects.toLocaleString()} objects · {m.screening.all_vs_all.hours} h ·
                  {' '}{m.screening.all_vs_all.pairs_sampled_close.toLocaleString()} pairs within {m.screening.all_vs_all.radius_km} km at a {m.screening.all_vs_all.step_s} s sample (unrefined)</span></div>
            )}
          </div>
        </section>
      </div>

      {m.notes && (
        <section className="panel notes">
          <div className="panel-title">Honesty notes</div>
          <ul>{m.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </section>
      )}
    </main>
  )
}
