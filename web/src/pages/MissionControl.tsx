import { useState } from 'react'
import { api } from '../api'
import { AlertList } from '../components/AlertList'
import { Globe } from '../components/Globe'
import { ErrorBox, Loading } from '../components/Status'
import { pcSci } from '../format'
import { go } from '../router'
import type { Source } from '../types'
import { useApi } from '../useApi'

export function MissionControl({ source }: { source: Source }) {
  const [norad, setNorad] = useState(25544)
  const alerts = useApi(() => api.alerts('historical', 50), [])
  const catalog = useApi(() => api.liveCatalog(3000), [])
  const conj = useApi(() => api.liveConjunctions(norad, 72), [norad])
  const orbit = useApi(() => api.liveOrbit(norad, 90, 30), [norad])
  const presets = useApi(() => api.livePresets(), [])
  const stats = (conj.data as { stats?: { objects?: number; hours?: number } } | null)?.stats

  return (
    <main className="mission">
      <section className="panel globe-panel">
        <div className="panel-title">
          {source === 'live' ? `Live sky · ${conj.data?.primary.name ?? norad} · next 72 h` : 'Catalog overview'}
          {catalog.data && <span className="muted"> · {catalog.data.objects.length.toLocaleString()} objects shown</span>}
        </div>
        {catalog.error && <ErrorBox message={catalog.error} onRetry={catalog.reload} />}
        <Globe
          objects={catalog.data?.objects ?? []}
          primary={conj.data?.primary ?? null}
          orbit={source === 'live' ? orbit.data?.points ?? [] : []}
          conjunctions={source === 'live' ? conj.data?.conjunctions ?? [] : []}
        />
        <div className="globe-legend">
          <span><i style={{ background: '#22d3ee' }} /> primary</span>
          <span><i style={{ background: '#ffffff' }} /> payloads</span>
          <span><i style={{ background: '#7a8594' }} /> debris / rocket bodies</span>
          {source === 'live' && <span><i style={{ background: '#ef4444' }} /> conjunction partner (at TCA)</span>}
        </div>
      </section>

      <section className="panel list-panel">
        {source === 'historical' ? (
          <>
            <div className="panel-title">Ranked alerts · ESA Kelvins CDMs (held-out) · decision 2 days before TCA</div>
            {alerts.loading && <Loading what="alerts" />}
            {alerts.error && <ErrorBox message={alerts.error} onRetry={alerts.reload} />}
            {alerts.data && <AlertList alerts={alerts.data} onSelect={go.alert} />}
          </>
        ) : (
          <>
            <div className="panel-title live-title">
              <span>Close approaches &lt; 10 km · next 72 h</span>
              <select value={norad} onChange={(e) => setNorad(Number(e.target.value))} aria-label="Primary satellite">
                {(presets.data ?? [{ norad: 25544, name: 'ISS (ZARYA)' }]).map((p) => (
                  <option key={p.norad} value={p.norad}>{p.name} ({p.norad})</option>
                ))}
              </select>
            </div>
            {conj.loading && <Loading what="conjunctions (screening the catalog)" />}
            {conj.error && <ErrorBox message={conj.error} onRetry={conj.reload} />}
            {conj.data && !conj.loading && (
              <>
                <div className="footnote mono">
                  Screened {stats?.objects ? stats.objects.toLocaleString() : '—'} objects over {stats?.hours ?? 72} h in{' '}
                  {conj.data.compute_seconds.toFixed(1)} s (SGP4, 60 s grid + 1 s TCA refinement)
                </div>
                {conj.data.conjunctions.length === 0 && <div className="status">No close approaches under 10 km in the window.</div>}
                <ol className="alert-list">
                  {conj.data.conjunctions.map((c, i) => (
                    <li key={`${c.secondary.norad}-${c.tca}`} className="alert-row"
                      onClick={() => c.event_id && go.alert(c.event_id)}>
                      <span className="rank mono">{i + 1}</span>
                      <span className={`decision ${c.pc_est >= 1e-4 ? 'decision-maneuver' : c.pc_est >= 1e-6 ? 'decision-watch' : 'decision-hold'}`}>
                        {c.pc_est >= 1e-4 ? 'MANEUVER' : c.pc_est >= 1e-6 ? 'WATCH' : 'HOLD'}
                      </span>
                      <div className="alert-main">
                        <div className="alert-title">
                          <span className="mono">{conj.data!.primary.name}</span>
                          <span className="muted"> × {c.secondary.name} ({c.secondary.type})</span>
                        </div>
                        <div className="muted mono">TCA {c.tca.replace('T', ' ').slice(0, 16)}Z · {c.rel_speed_kms.toFixed(1)} km/s</div>
                      </div>
                      <div className="alert-nums">
                        <div className="mono big">{c.miss_km.toFixed(2)} km</div>
                        <div className="muted mono">Pc est {pcSci(c.pc_est)}</div>
                      </div>
                    </li>
                  ))}
                </ol>
              </>
            )}
            <p className="footnote">
              Live Pc is <em>estimated</em>: catalog (OMM/TLE) data has no covariance, so position sigmas are assumed to
              grow with data age (σR = 0.1 + 0.05·d km, σT = 0.3 + 0.3·d km, σN = 0.1 + 0.05·d km). Live mode is
              screening; the trained risk model runs on CDMs, which carry covariance.
            </p>
          </>
        )}
      </section>
    </main>
  )
}
