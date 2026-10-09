import { useState } from 'react'
import { api } from './api'
import { AlertList } from './components/AlertList'
import { Globe } from './components/Globe'
import { Header } from './components/Header'
import { ErrorBox, Loading } from './components/Status'
import { days, pcSci } from './format'
import type { Source } from './types'
import { useApi } from './useApi'

export default function App() {
  const [source, setSource] = useState<Source>('historical')
  const [selected, setSelected] = useState<string | null>(null)

  const health = useApi(() => api.health(), [])
  const alerts = useApi(() => api.alerts('historical', 50), [])
  const catalog = useApi(() => api.liveCatalog(3000), [])
  const conj = useApi(() => api.liveConjunctions(25544, 72), [])
  const orbit = useApi(() => api.liveOrbit(25544, 90, 30), [])

  return (
    <div className="app">
      <Header source={source} onSource={setSource} mode={health.data?.mode} />
      <main className="mission">
        <section className="panel globe-panel">
          <div className="panel-title">
            {source === 'live' ? 'Live sky · ISS (25544) · next 72 h' : 'Catalog overview'}
            {catalog.data && <span className="muted"> · {catalog.data.objects.length.toLocaleString()} objects</span>}
          </div>
          {catalog.error && <ErrorBox message={catalog.error} onRetry={catalog.reload} />}
          <Globe
            objects={catalog.data?.objects ?? []}
            primary={conj.data?.primary ?? null}
            orbit={orbit.data?.points ?? []}
            conjunctions={source === 'live' ? conj.data?.conjunctions ?? [] : []}
          />
        </section>

        <section className="panel list-panel">
          {source === 'historical' ? (
            <>
              <div className="panel-title">Ranked alerts · ESA Kelvins CDMs</div>
              {alerts.loading && <Loading what="alerts" />}
              {alerts.error && <ErrorBox message={alerts.error} onRetry={alerts.reload} />}
              {alerts.data && <AlertList alerts={alerts.data} selected={selected} onSelect={setSelected} />}
            </>
          ) : (
            <>
              <div className="panel-title">Close approaches · ISS · estimated Pc</div>
              {conj.loading && <Loading what="conjunctions" />}
              {conj.error && <ErrorBox message={conj.error} onRetry={conj.reload} />}
              {conj.data && (
                <ol className="alert-list">
                  {conj.data.conjunctions.map((c, i) => (
                    <li key={c.secondary.norad} className="alert-row">
                      <span className="rank mono">{i + 1}</span>
                      <span className="decision decision-watch">CONJ</span>
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
              )}
              <p className="footnote">
                Live Pc is <em>estimated</em>: catalog data has no covariance, so position sigmas are assumed
                to grow with data age.
              </p>
            </>
          )}
          {selected && source === 'historical' && (
            <div className="footnote">Selected EVT {selected} — alert detail page arrives in Milestone 4.</div>
          )}
          {health.data && (
            <div className="footnote mono">
              API {health.data.status} · mode {health.data.mode} · model {health.data.model_loaded ? 'loaded' : 'not loaded'} ·
              catalog {health.data.catalog_age_hours == null ? 'n/a' : days(health.data.catalog_age_hours / 24) + ' old'}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
