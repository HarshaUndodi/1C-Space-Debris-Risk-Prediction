import {
  CartesianGrid, ComposedChart, Legend, Line, ReferenceArea, ReferenceLine, ResponsiveContainer,
  Scatter, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { AlertDetail } from '../types'
import { oneInN } from '../format'
import { C, RISK_MAX, RISK_MIN, axisProps, clampRisk, tooltipStyle } from './theme'

/** Risk (log10 PoC) vs days to TCA: CDMs received so far, unseen later CDMs, the model's band at TCA. */
export function CdmHistoryChart({ d, cutoff }: { d: AlertDetail; cutoff: number }) {
  const pts = d.cdm_history.map((p) => ({ t: p.time_to_tca, risk: clampRisk(p.risk), raw: p.risk, miss: p.miss_distance_m }))
  const seen = pts.filter((p) => p.t >= cutoff)
  const unseen = pts.filter((p) => p.t < cutoff)
  const p50 = [{ t: 0.12, risk: clampRisk(d.risk_p50), raw: d.risk_p50 }]
  const actual = d.true_final_risk == null ? [] : [{ t: 0.04, risk: clampRisk(d.true_final_risk), raw: d.true_final_risk }]

  return (
    <ResponsiveContainer width="100%" height={300}>
      <ComposedChart margin={{ top: 12, right: 24, bottom: 8, left: 4 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="0" vertical={false} />
        <XAxis type="number" dataKey="t" domain={[0, 7]} reversed ticks={[7, 6, 5, 4, 3, 2, 1, 0]}
          {...axisProps} label={{ value: 'days to TCA', position: 'insideBottomRight', offset: -4, fill: C.muted, fontSize: 12 }} />
        <YAxis type="number" dataKey="risk" domain={[RISK_MIN, RISK_MAX]} ticks={[-12, -10, -8, -6, -4, -2]}
          tickFormatter={(v: number) => `1e${v}`} width={52} {...axisProps} />
        <Tooltip {...tooltipStyle} cursor={{ stroke: C.axis }}
          formatter={(_v: unknown, _n: unknown, item: { payload?: { raw?: number; miss?: number } }) => {
            const raw = item?.payload?.raw
            const miss = item?.payload?.miss
            return [raw == null ? '—' : `${raw.toFixed(2)} (${oneInN(raw)})${miss != null ? ` · miss ${miss.toFixed(0)} m` : ''}`, 'log10 PoC']
          }}
          labelFormatter={(v: unknown) => `${Number(v).toFixed(2)} d to TCA`} />
        <Legend wrapperStyle={{ fontSize: 12, color: C.ink2 }} />

        {/* model P10–P90 band at TCA */}
        <ReferenceArea x1={0.3} x2={0} y1={clampRisk(d.risk_p10)} y2={clampRisk(d.risk_p90)}
          fill={C.series3} fillOpacity={0.35} stroke={C.series3} ifOverflow="extendDomain" />
        <ReferenceLine y={-4} stroke={C.critical} strokeDasharray="6 4"
          label={{ value: 'maneuver trigger 1e-4', fill: C.critical, fontSize: 11, position: 'insideTopLeft' }} />
        <ReferenceLine y={-6} stroke={C.muted} strokeDasharray="3 4"
          label={{ value: 'high-risk 1e-6', fill: C.muted, fontSize: 11, position: 'insideBottomLeft' }} />
        <ReferenceLine x={cutoff} stroke={C.warning} strokeWidth={2}
          label={{ value: `now (${cutoff} d)`, fill: C.warning, fontSize: 11, position: 'top' }} />

        <Line data={seen} dataKey="risk" name="CDM risk (received)" stroke={C.series1} strokeWidth={2}
          dot={{ r: 4, fill: C.series1, stroke: C.surface, strokeWidth: 2 }} isAnimationActive={false} />
        <Scatter data={unseen} dataKey="risk" name="later CDMs (not yet received)" fill={C.muted} fillOpacity={0.45} />
        <Scatter data={p50} dataKey="risk" name="model P50 at TCA (band = P10–P90)" fill={C.series3} shape="diamond" />
        {actual.length > 0 && <Scatter data={actual} dataKey="risk" name="actual outcome" fill={C.ink} shape="star" />}
      </ComposedChart>
    </ResponsiveContainer>
  )
}
