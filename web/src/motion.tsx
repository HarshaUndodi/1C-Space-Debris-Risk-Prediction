// Small motion primitives. Everything settles to its final state immediately under prefers-reduced-motion.
import { useEffect, useRef, useState } from 'react'

export const reducedMotion = () =>
  typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

const easeOut = (x: number) => 1 - Math.pow(1 - x, 3)

/** Animates a number from its previous value to `value` (from 0 on first mount). */
export function CountUp({ value, format, duration = 900 }: { value: number; format: (v: number) => string; duration?: number }) {
  const [shown, setShown] = useState(() => (reducedMotion() ? value : 0))
  const from = useRef(reducedMotion() ? value : 0)
  useEffect(() => {
    if (reducedMotion() || !Number.isFinite(value)) { setShown(value); return }
    const start = performance.now()
    const a = from.current
    let raf = 0
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / duration)
      setShown(a + (value - a) * easeOut(k))
      if (k < 1) raf = requestAnimationFrame(step)
      else from.current = value
    }
    raf = requestAnimationFrame(step)
    return () => { cancelAnimationFrame(raf); from.current = value }
  }, [value, duration])
  return <>{format(shown)}</>
}

/** Types lines out character by character with a blinking cursor; restarts when `lines` change. */
export function Typewriter({ lines, render, cps = 70 }: {
  lines: string[]
  render: (line: string, i: number, full: string) => React.ReactNode
  cps?: number
}) {
  const total = lines.join('\n')
  const [n, setN] = useState(() => (reducedMotion() ? total.length : 0))
  useEffect(() => {
    if (reducedMotion()) { setN(total.length); return }
    setN(0)
    const start = performance.now()
    let raf = 0
    const step = (t: number) => {
      const k = Math.min(total.length, Math.floor(((t - start) / 1000) * cps))
      setN(k)
      if (k < total.length) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [total, cps])
  let left = n
  return (
    <>
      {lines.map((full, i) => {
        const visible = full.slice(0, Math.max(0, left))
        left -= full.length + 1
        const typing = n < total.length && visible.length > 0 && visible.length < full.length + 1 && left < 0
        return (
          <div key={i}>
            {render(visible, i, full)}
            {typing && <span className="caret" aria-hidden="true">▍</span>}
          </div>
        )
      })}
      {n >= total.length && <span className="caret idle" aria-hidden="true">▍</span>}
    </>
  )
}
