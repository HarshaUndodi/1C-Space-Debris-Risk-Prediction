// All data access goes through this module (SPEC Section 12 rule).
import axios from 'axios'
import type {
  AlertDetail, AlertItem, Health, LiveCatalog, LiveConjunctions, ManeuverResult,
  Metrics, OrbitPath, Source, SpaceWeather,
} from './types'

const http = axios.create({
  // Same-origin by default: FastAPI serves the built app (make serve / tunnel); Vite proxies /api in dev.
  baseURL: import.meta.env.VITE_API_BASE ?? '/api',
  timeout: 15000,
})

const get = async <T>(url: string, params?: Record<string, unknown>): Promise<T> =>
  (await http.get<T>(url, { params })).data

export const api = {
  health: () => get<Health>('/health'),
  alerts: (source: Source = 'historical', limit = 50) => get<AlertItem[]>('/alerts', { source, limit }),
  alert: (eventId: string, cutoff = 2) => get<AlertDetail>(`/alerts/${eventId}`, { cutoff }),
  maneuver: (eventId: string) => get<ManeuverResult>(`/alerts/${eventId}/maneuver`),
  liveCatalog: (limit = 3000) => get<LiveCatalog>('/live/catalog', { limit }),
  liveConjunctions: (norad = 25544, hours = 72) => get<LiveConjunctions>('/live/conjunctions', { norad, hours }),
  liveOrbit: (norad: number, minutes = 90, step_s = 30) => get<OrbitPath>(`/live/orbit/${norad}`, { minutes, step_s }),
  livePresets: () => get<{ norad: number; name: string }[]>('/live/presets'),
  metrics: () => get<Metrics>('/metrics'),
  spaceWeather: () => get<SpaceWeather>('/space-weather'),
}

export function errorMessage(e: unknown): string {
  if (axios.isAxiosError(e)) {
    if (!e.response) return `API unreachable (${e.message}). Is the OrbitGuard server running?`
    return `API error ${e.response.status}: ${JSON.stringify(e.response.data).slice(0, 160)}`
  }
  return String(e)
}
