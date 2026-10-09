import { api } from '../api'
import { AlertList } from '../components/AlertList'
import { Globe } from '../components/Globe'
import { ErrorBox, Loading } from '../components/Status'
import { pcSci } from '../format'
import { go } from '../router'
import type { Source } from '../types'
import { useApi } from '../useApi'

export function MissionControl({ source }: { source: Source }) {
  const alerts = useApi(() => api.alerts('historical', 50), [])
  const catalog = useApi(() => api.liveCatalog(3000), [])
  const conj = useApi(() => api.liveConjunctions(25544, 72), [])
  const orbit = useApi(() => api.liveOrbit(25544, 90, 30), [])
  const metrics = useApi(() => api.metrics(), [])
  const scr = metrics.data?.screening

  return (
    <main className="mission">
      <section className="panel globe-panel">
        <div className="panel-title">
          {source === 'live' ? 'Live sky · ISS (25544) · next 72 h' : 'Catalog overview'}
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
            <div className="panel-title">Close approaches · ISS · next 72 h</div>
            {conj.loading && <Loading what="conjunctions (screening the catalog)" />}
            {conj.error && <ErrorBox message={conj.error} onRetry={conj.reload} />}
            {conj.data && (
              <>
                <div className="footnote mono">
                  Screened {scr?.objects ? scr.objects.toLocaleString() : '—'} objects over {scr?.hours ?? 72} h in{' '}
                  {conj.data.compute_seconds.toFixed(1)} s
                </div>
                {conj.data.conjunctions.length === 0 && <div className="status">No close approaches under the threshold in the window.</div>}
                <ol className="alert-list">
                  {conj.data.conjunctions.map((c, i) => (
                    <li key={`${c.secondary.norad}-${c.tca}`} className="alert-row"
                      onClick={() => go.alert(`live-${c.secondary.norad}`)}>
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
