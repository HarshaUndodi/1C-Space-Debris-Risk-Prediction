// Chart tokens — dark-surface steps of the validated reference palette (dataviz skill, palette.md).
export const C = {
  surface: '#0b1018',
  grid: '#2c2c2a',
  axis: '#383835',
  muted: '#898781',
  ink: '#ffffff',
  ink2: '#c3c2b7',
  series1: '#3987e5', // blue  — model / along-track / "lowers risk"
  series2: '#d95926', // orange — baseline / radial
  series3: '#199e70', // aqua  — P10–P90 band
  critical: '#e66767', // diverging warm pole — "raises risk"; maneuver trigger line
  warning: '#fab219',
}

export const axisProps = {
  stroke: C.axis,
  tick: { fill: C.muted, fontSize: 12, fontFamily: 'JetBrains Mono, monospace' },
  tickLine: { stroke: C.axis },
}

export const tooltipStyle = {
  contentStyle: { background: '#111827', border: '1px solid #1f2a3a', borderRadius: 6, color: C.ink, fontSize: 12 },
  labelStyle: { color: C.ink2 },
  itemStyle: { color: C.ink },
}

/** Clamp a log10 risk to the plotted range so -30 floors sit on the axis instead of off-chart. */
export const RISK_MIN = -12
export const RISK_MAX = -1
export const clampRisk = (r: number) => Math.max(RISK_MIN, Math.min(RISK_MAX, r))

export const PC_MIN = 1e-12
export const clampPc = (p: number) => Math.max(PC_MIN, Math.min(1, p))
