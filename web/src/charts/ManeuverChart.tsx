import {
  CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { ManeuverResult } from '../types'
import { pcSci } from '../format'
import { C, PC_MIN, anim, axisProps, clampPc, tooltipStyle } from './theme'

// Two hues (along vs radial) × marker shape (sign): stays within the 3-colour cap for scatter.
const SERIES = [
  { dir: '+along', color: C.series1, shape: 'circle' as const },
  { dir: '-along', color: C.series1, shape: 'triangle' as const },
  { dir: '+radial', color: C.series2, shape: 'circle' as const },
  { dir: '-radial', color: C.series2, shape: 'triangle' as const },
]

/** Residual Pc (log) vs Δv (log): every option, the Pareto front, the recommended burn, and operator custom plan. */
export function ManeuverChart({
  m,
  customPlan,
}: {
  m: ManeuverResult
  customPlan?: { dv_ms: number; post_pc: number; direction?: string; burn_lead_h?: number } | null
}) {
  const pts = m.points.map((p) => ({ ...p, y: clampPc(p.post_pc) }))
  const front = m.pareto.map((p) => ({ dv_ms: p.dv_ms, y: clampPc(p.post_pc) }))
  const rec = m.recommended.dv_ms > 0 ? [{ ...m.recommended, y: clampPc(m.recommended.post_pc) }] : []
  const custom = customPlan && customPlan.dv_ms > 0 ? [{ ...customPlan, y: clampPc(customPlan.post_pc) }] : []
  return (
    <ResponsiveContainer width="100%" height={320}>
      <ComposedChart margin={{ top: 12, right: 24, bottom: 8, left: 4 }}>
        <CartesianGrid stroke={C.grid} />
        <XAxis type="number" dataKey="dv_ms" scale="log" domain={[0.001, 2]} allowDataOverflow
          ticks={[0.001, 0.01, 0.1, 1]} tickFormatter={(v: number) => `${v}`} {...axisProps}
          label={{ value: 'Δv (m/s)', position: 'insideBottomRight', offset: -4, fill: C.muted, fontSize: 12 }} />
        <YAxis type="number" dataKey="y" scale="log" domain={[PC_MIN, 1]} allowDataOverflow
          ticks={[1e-12, 1e-10, 1e-8, 1e-6, 1e-4, 1e-2, 1]} tickFormatter={(v: number) => v.toExponential(0)}
          width={56} {...axisProps} />
        <Tooltip {...tooltipStyle}
          formatter={(_v: unknown, _n: unknown, item: { payload?: { post_pc?: number; dv_ms?: number; direction?: string; burn_lead_h?: number } }) => {
            const p = item?.payload ?? {}
            return [`Pc ${pcSci(p.post_pc ?? 0)}${p.direction ? ` · ${p.direction} · ${p.burn_lead_h} h before TCA` : ''}`, `Δv ${p.dv_ms} m/s`]
          }} />
        <Legend wrapperStyle={{ fontSize: 12, color: C.ink2 }} />
        <ReferenceLine y={m.target_pc} stroke={C.warning} strokeDasharray="6 4"
          label={{ value: `target ${pcSci(m.target_pc)}`, fill: C.warning, fontSize: 11, position: 'insideTopRight' }} />
        <ReferenceLine y={clampPc(m.pre_burn_pc)} stroke={C.critical} strokeDasharray="3 4"
          label={{ value: `no burn ${pcSci(m.pre_burn_pc)}`, fill: C.critical, fontSize: 11, position: 'insideBottomRight' }} />
        {SERIES.map((s, i) => (
          <Scatter key={s.dir} name={s.dir} data={pts.filter((p) => p.direction === s.dir)} dataKey="y"
            fill={s.color} fillOpacity={0.35} shape={s.shape} legendType={s.shape} {...anim(100 + i * 150, 700)} />
        ))}
        <Line data={front} dataKey="y" name="Pareto front (best Pc per Δv)" stroke={C.ink} strokeWidth={2} dot={false}
          {...anim(800, 1400)} />
        {rec.length > 0 && (
          <Scatter name="recommended" data={rec} dataKey="y" fill={C.warning} shape="star"
            stroke={C.surface} strokeWidth={2} {...anim(2100, 500)} />
        )}
        {custom.length > 0 && (
          <Scatter name="Operator Custom Plan" data={custom} dataKey="y" fill="#22d3ee" shape="diamond"
            stroke="#ffffff" strokeWidth={2} />
        )}
      </ComposedChart>
    </ResponsiveContainer>
  )
}
