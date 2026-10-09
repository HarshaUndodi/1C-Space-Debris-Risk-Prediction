import { useEffect, useState } from 'react'

export type Route =
  | { page: 'mission' }
  | { page: 'alert'; id: string }
  | { page: 'metrics' }

function parse(hash: string): Route {
  const h = hash.replace(/^#\/?/, '')
  const m = h.match(/^alert\/(.+)$/)
  if (m) return { page: 'alert', id: decodeURIComponent(m[1]) }
  if (h === 'metrics') return { page: 'metrics' }
  return { page: 'mission' }
}

/** Minimal hash router — keeps the app a static bundle that works offline. */
export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash))
  useEffect(() => {
    const on = () => setRoute(parse(window.location.hash))
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}

export const go = {
  mission: () => { window.location.hash = '#/' },
  alert: (id: string) => { window.location.hash = `#/alert/${encodeURIComponent(id)}` },
  metrics: () => { window.location.hash = '#/metrics' },
}
