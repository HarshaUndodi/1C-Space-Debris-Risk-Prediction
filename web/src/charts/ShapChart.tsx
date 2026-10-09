import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ShapItem } from '../types'
import { C, anim, axisProps, tooltipStyle } from './theme'

/** Top-5 SHAP drivers (classifier log-odds). Red pushes toward high risk, blue away (diverging pair). */
export function ShapChart({ items }: { items: ShapItem[] }) {
  const data = items.map((s) => ({ ...s, name: s.label }))
  return (
    <div>
      <ResponsiveContainer width="100%" height={40 + 38 * data.length}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }} barCategoryGap={8}>
          <CartesianGrid stroke={C.grid} horizontal={false} />
          <XAxis type="number" {...axisProps} tickFormatter={(v: number) => v.toFixed(1)} />
          <YAxis type="category" dataKey="name" width={230} {...axisProps}
            tick={{ fill: C.ink2, fontSize: 13 }} />
          <ReferenceLine x={0} stroke={C.axis} />
          <Tooltip {...tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            formatter={(v: unknown, _n: unknown, item: { payload?: ShapItem }) => {
              const val = item?.payload?.value
              return [`${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(3)} log-odds · feature value ${val == null ? 'n/a' : Number(val).toPrecision(4)}`, item?.payload?.feature ?? '']
            }} />
          <Bar dataKey="shap" radius={4} {...anim(250, 1000)}>
            {data.map((d) => <Cell key={d.feature} fill={d.shap >= 0 ? C.critical : C.series1} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="chart-key">
        <span><i style={{ background: C.critical }} /> raises risk</span>
        <span><i style={{ background: C.series1 }} /> lowers risk</span>
      </div>
    </div>
  )
}
