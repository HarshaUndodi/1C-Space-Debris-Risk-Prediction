import axios from 'axios'
import { useCallback, useEffect, useState } from 'react'
import { errorMessage } from './api'

export interface ApiState<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
}

/** Fetch on mount / when deps change; exposes loading + error state for every request. */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[]): ApiState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let alive = true
    let retry: ReturnType<typeof setTimeout> | undefined
    setLoading(true)
    setError(null)
    fetcher()
      .then((d) => { if (alive) setData(d) })
      .catch((e) => {
        if (!alive) return
        // 503 = the backend is still computing (e.g. live screening) → keep loading and poll
        if (axios.isAxiosError(e) && e.response?.status === 503) {
          retry = setTimeout(() => setTick((t) => t + 1), 2500)
          return
        }
        setError(errorMessage(e))
        setLoading(false)
      })
      .then(() => { if (alive && retry === undefined) setLoading(false) })
    return () => { alive = false; if (retry) clearTimeout(retry) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, loading, error, reload }
}
