// Regulator persona: exportable, transparent risk report (JSON + printable HTML).
import type { AlertDetail, ManeuverResult } from './types'
import { oneInN, pcSci } from './format'

function download(name: string, mime: string, body: string) {
  const url = URL.createObjectURL(new Blob([body], { type: mime }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!))

export function exportJson(d: AlertDetail, m: ManeuverResult | null, cutoff: number) {
  const { points: _omit, ...man } = m ?? ({ points: [] } as unknown as ManeuverResult)
  void _omit
  const report = { generated_at: new Date().toISOString(), tool: 'OrbitGuard', cutoff_days: cutoff, alert: d, maneuver: m ? man : null }
  download(`orbitguard_event_${d.event_id}_cutoff${cutoff}.json`, 'application/json', JSON.stringify(report, null, 2))
}

export function exportHtml(d: AlertDetail, m: ManeuverResult | null, cutoff: number) {
  const rec = m?.recommended
  const rows = d.shap_top.map((s) =>
    `<tr><td>${esc(s.label)}</td><td><code>${esc(s.feature)}</code></td><td>${s.value == null ? 'n/a' : Number(s.value).toPrecision(4)}</td><td>${s.shap >= 0 ? '+' : ''}${s.shap.toFixed(3)}</td></tr>`).join('')
  const cdms = d.cdm_history.map((c) => `<tr><td>${c.time_to_tca.toFixed(3)}</td><td>${c.risk.toFixed(3)}</td><td>${c.miss_distance_m.toFixed(1)}</td></tr>`).join('')
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>OrbitGuard risk report — event ${esc(d.event_id)}</title>
<style>body{font:14px/1.5 system-ui,sans-serif;max-width:860px;margin:32px auto;padding:0 16px;color:#111}
h1{font-size:22px}h2{font-size:16px;margin-top:28px;border-bottom:1px solid #ddd}table{border-collapse:collapse;width:100%}
td,th{border:1px solid #ddd;padding:4px 8px;text-align:left}code{font-size:12px}.d{font-weight:700}
.brief{font-family:ui-monospace,Consolas,monospace;background:#f5f5f4;padding:12px;white-space:pre-wrap}</style></head><body>
<h1>OrbitGuard collision-risk report — event ${esc(d.event_id)}</h1>
<p>Generated ${new Date().toISOString()} · data source: ${d.source === 'historical' ? 'ESA Kelvins CDMs (held-out test set)' : 'CelesTrak catalog'} · assessment made ${cutoff} days before TCA using only CDMs available then.</p>
<h2>Decision</h2>
<p class="d">${d.decision}</p>
<table><tr><th>Calibrated P(high risk)</th><td>${d.p_high.toFixed(4)}</td></tr>
<tr><th>Final risk P50</th><td>${d.risk_p50.toFixed(2)} (${oneInN(d.risk_p50)})</td></tr>
<tr><th>Confidence band P10–P90</th><td>${d.risk_p10.toFixed(2)} … ${d.risk_p90.toFixed(2)} (log10 PoC)</td></tr>
<tr><th>Baseline (latest CDM risk)</th><td>${d.baseline_risk.toFixed(2)}</td></tr>
<tr><th>Miss distance (latest CDM)</th><td>${d.miss_distance_m.toFixed(1)} m</td></tr>
<tr><th>Chaser type</th><td>${esc(d.chaser_type)}</td></tr>
${d.true_final_risk != null ? `<tr><th>Actual outcome (final CDM)</th><td>${d.true_final_risk.toFixed(2)} (${oneInN(d.true_final_risk)})</td></tr>` : ''}</table>
<h2>Operator briefing (${d.briefing_source === 'llm' ? 'LLM-written from the numbers below' : 'template'})</h2>
<div class="brief">${d.briefing.map(esc).join('\n')}</div>
<h2>Why it was flagged — top SHAP drivers (classifier log-odds)</h2>
<table><tr><th>Driver</th><th>Feature</th><th>Value</th><th>SHAP</th></tr>${rows}</table>
<h2>Avoidance maneuver (Clohessy–Wiltshire, 2D Foster Pc)</h2>
${m && rec ? `<p>Pre-burn Pc ${pcSci(m.pre_burn_pc)}. ${rec.dv_ms > 0 ? `Recommended ${rec.dv_ms.toPrecision(3)} m/s ${rec.direction} burn ${rec.burn_lead_h} h before TCA → Pc ${pcSci(rec.post_pc)} (≈ ${rec.propellant_g.toFixed(1)} g propellant, 500 kg / Isp 220 s).` : 'No burn needed.'} Target ${pcSci(m.target_pc)} ${m.target_met ? 'met' : 'NOT met'}.</p>
<p>Secondary-conjunction check: ${m.secondary_check.applicable ? `${m.secondary_check.new_conjunctions.length} new conjunctions < 5 km` : esc(m.secondary_check.note ?? 'not applicable')}.</p>` : '<p>Not available (incomplete covariance).</p>'}
<h2>CDM history used</h2><table><tr><th>Days to TCA</th><th>log10 PoC</th><th>Miss distance (m)</th></tr>${cdms}</table>
<h2>Method & limitations</h2><p>LightGBM models trained on ESA Kelvins CDMs with event-level splits and no information after the cutoff. Probabilities are isotonic-calibrated on out-of-fold predictions. Pc assumes short-encounter linear motion; CW assumes near-circular orbits. Not flight-ready guidance.</p>
</body></html>`
  download(`orbitguard_event_${d.event_id}_cutoff${cutoff}.html`, 'text/html', html)
}
