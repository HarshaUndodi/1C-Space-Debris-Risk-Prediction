// Display helpers. Risk values are log10 PoC throughout.

export function oneInN(log10Risk: number): string {
  if (!Number.isFinite(log10Risk)) return '—'
  const n = Math.pow(10, -log10Risk)
  if (n < 1.5) return '≈ certain'
  if (n < 1e7) return `1 in ${Math.round(n).toLocaleString('en-US', { maximumSignificantDigits: 3 })}`
  return `1 in ${n.toExponential(1).replace('e+', 'e')}`
}

export function pcSci(pc: number): string {
  if (pc <= 0) return '0'
  return pc.toExponential(1).replace('e-', 'e−')
}

export function days(d: number): string {
  return d < 1 ? `${(d * 24).toFixed(1)} h` : `${d.toFixed(2)} d`
}

export function meters(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${m.toFixed(0)} m`
}
