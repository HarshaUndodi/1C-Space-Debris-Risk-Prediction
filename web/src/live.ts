// Real-time globe: a time-warpable simulation clock + rolling SGP4 track windows from /api/live/tracks.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import type { LiveTracks } from './types'

export interface SimClock {
  speed: number
  setSpeed: (s: number) => void
  /** current simulated time, epoch ms */
  now: () => number
}

/** Sim time = anchor + (real elapsed × speed). Changing speed re-anchors so time never jumps. */
export function useSimClock(): SimClock {
  const anchor = useRef({ real: performance.now(), sim: Date.now(), speed: 1 })
  const [speed, setSpeedState] = useState(1)
  const now = useCallback(() => {
    const a = anchor.current
    return a.sim + (performance.now() - a.real) * a.speed
  }, [])
  const setSpeed = useCallback((s: number) => {
    const t = now()
    anchor.current = { real: performance.now(), sim: t, speed: s }
    setSpeedState(s)
  }, [now])
  return useMemo(() => ({ speed, setSpeed, now }), [speed, setSpeed, now])
}

// 60 min windows at 60 s steps: linear interpolation errs by ~4 km mid-step (invisible at globe scale)
// and keeps each window small enough for a tunnel, even at 60× time warp.
const WINDOW_MIN = 60
const STEP_S = 60

/** Keeps a track window that covers the sim clock; prefetches the next one at 60 % of the window. */
export function useLiveTracks(clock: SimClock, limit = 1500): { tracks: LiveTracks | null; error: string | null } {
  const [tracks, setTracks] = useState<LiveTracks | null>(null)
  const [error, setError] = useState<string | null>(null)
  const loading = useRef(false)
  const current = useRef<LiveTracks | null>(null)

  useEffect(() => {
    let alive = true
    const load = (startMs: number) => {
      if (loading.current) return
      loading.current = true
      api.liveTracks(new Date(startMs).toISOString().slice(0, 19) + 'Z', limit, WINDOW_MIN, STEP_S)
        .then((t) => { if (alive) { current.current = t; setTracks(t); setError(null) } })
        .catch((e) => { if (alive) setError(String(e?.message ?? e)) })
        .finally(() => { loading.current = false })
    }
    const tick = () => {
      const t = current.current
      const sim = clock.now()
      if (!t) return load(sim - 60_000)
      const start = Date.parse(t.start)
      const span = (t.n_steps - 1) * t.step_s * 1000
      if (sim < start || sim > start + 0.6 * span) load(sim - 60_000)
    }
    tick()
    const id = setInterval(tick, 1500)
    return () => { alive = false; clearInterval(id) }
  }, [clock.now, limit]) // eslint-disable-line react-hooks/exhaustive-deps

  return { tracks, error }
}

/** Interpolated Earth-fixed position (km) of object i at sim time; null outside the window. */
export function positionAt(t: LiveTracks, i: number, simMs: number, out: number[]): number[] | null {
  const s = (simMs - Date.parse(t.start)) / 1000 / t.step_s
  if (s < 0 || s > t.n_steps - 1) return null
  const k = Math.min(Math.floor(s), t.n_steps - 2)
  const f = s - k
  const a = t.samples_km[i]
  const j = 3 * k
  out[0] = a[j] + (a[j + 3] - a[j]) * f
  out[1] = a[j + 1] + (a[j + 4] - a[j + 1]) * f
  out[2] = a[j + 2] + (a[j + 5] - a[j + 2]) * f
  return out
}

/** Re-render every `ms` (for ticking clocks and countdowns). */
export function useNow(ms = 1000): number {
  const [t, setT] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setT(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return t
}

export function countdown(targetIso: string, nowMs: number): string {
  let s = Math.round((Date.parse(targetIso) - nowMs) / 1000)
  if (s <= 0) return 'passed'
  const d = Math.floor(s / 86400); s -= d * 86400
  const h = Math.floor(s / 3600); s -= h * 3600
  const m = Math.floor(s / 60); s -= m * 60
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d > 0 ? `${d}d ` : ''}${p(h)}:${p(m)}:${p(s)}`
}
