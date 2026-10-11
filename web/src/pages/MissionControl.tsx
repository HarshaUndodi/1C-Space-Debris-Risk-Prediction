import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { AlertList } from '../components/AlertList'
import { Globe } from '../components/Globe'
import { SpaceWeatherGauge } from '../components/SpaceWeatherGauge'
import { ErrorBox, Loading } from '../components/Status'
import { pcSci } from '../format'
import { countdown, useLiveTracks, useNow, useSimClock, type SimClock } from '../live'
import { go } from '../router'
import type { Conjunction, OrbitPath, Preset, Source } from '../types'
import { useApi } from '../useApi'

const SPEEDS = [1, 10, 60]

function SimBar({ clock }: { clock: SimClock }) {
  useNow(250)
  const t = new Date(clock.now())
  return (
    <div className="simbar">
      <span className="sim-dot" aria-hidden="true" />
      <span className="mono">SIM {t.toISOString().slice(11, 19)} UTC</span>
      <div className="speed" role="group" aria-label="Time warp">
        {SPEEDS.map((s) => (
          <button key={s} className={clock.speed === s ? 'active' : ''} onClick={() => clock.setSpeed(s)}>{s}×</button>
        ))}
      </div>
    </div>
  )
}

export function MissionControl({ source }: { source: Source }) {
  const [norad, setNorad] = useState(25544)
  const [highlightIsro, setHighlightIsro] = useState(true)
  const [highlightSwarm, setHighlightSwarm] = useState(true)
  const [showWeather, setShowWeather] = useState(false)
  const clock = useSimClock()
  const { tracks } = useLiveTracks(clock)
  const now = useNow(1000)
  const alerts = useApi(() => api.alerts('historical', 50), [])
  const catalog = useApi(() => api.liveCatalog(3000), [])
  const conj = useApi(() => api.liveConjunctions(norad, 72), [norad])
  const presets = useApi(() => api.livePresets(), [])
  const spaceWeather = useApi(() => api.spaceWeather(), [])
  const stats = (conj.data as { stats?: { objects?: number; hours?: number } } | null)?.stats

  // Categorize presets into ISRO fleet vs Space Stations
  const { isroPresets, otherPresets } = useMemo(() => {
    const all = presets.data ?? [{ norad: 25544, name: 'ISS (ZARYA)', fleet: 'station', agency: 'International' }]
    const isro: Preset[] = []
    const others: Preset[] = []
    for (const p of all) {
      const isInd = p.fleet === 'isro' || /CARTOSAT|ASTROSAT|RISAT|OCEANSAT|EOS|RESOURCESAT|INSAT|GSAT/i.test(p.name)
      if (isInd) isro.push(p)
      else others.push(p)
    }
    return { isroPresets: isro, otherPresets: others }
  }, [presets.data])

  // The primary's trail follows the simulation clock: refresh it with each new track window.
  const [orbit, setOrbit] = useState<OrbitPath | null>(null)
  const trackStart = tracks?.start
  useEffect(() => {
    let alive = true
    api.liveOrbit(norad, 95, 30, new Date(clock.now()).toISOString().slice(0, 19) + 'Z')
      .then((o) => { if (alive) setOrbit(o) }).catch(() => {})
    return () => { alive = false }
  }, [norad, trackStart, clock])

  const shown = tracks?.objects.length ?? catalog.data?.objects.length ?? 0

  return (
    <main className="mission">
      <section className="panel globe-panel enter" style={{ animationDelay: '0ms' }}>
        <div className="panel-title panel-title-split">
          <div className="title-left">
            <span>{source === 'live' ? `Live sky · ${conj.data?.primary.name ?? norad} · next 72 h` : 'Catalog in motion'}</span>
            {shown > 0 && <span className="muted"> · {shown.toLocaleString()} objects{tracks ? ' moving' : ''}</span>}
          </div>
          <div className="globe-toolbar">
            <button
              type="button"
              className={`layer-btn ${highlightIsro ? 'active isro-active' : ''}`}
              onClick={() => setHighlightIsro(!highlightIsro)}
              title="Highlight India ISRO NETRA satellites"
            >
              <span className="dot dot-isro" /> 🇮🇳 ISRO NETRA
            </button>
            <button
              type="button"
              className={`layer-btn ${highlightSwarm ? 'active swarm-active' : ''}`}
              onClick={() => setHighlightSwarm(!highlightSwarm)}
              title="Highlight Cosmos-1408 and ASAT debris cloud"
            >
              <span className="dot dot-swarm" /> 🔥 Cosmos-1408 Swarm
            </button>
            <button
              type="button"
              className={`layer-btn ${showWeather ? 'active sw-active' : ''}`}
              onClick={() => setShowWeather(!showWeather)}
              title="Inspect Solar Activity & Atmospheric Drag Impact"
            >
              <span className="dot dot-sun" /> ☀️ Solar Drag Gauge
            </button>
          </div>
        </div>

        {catalog.error && !tracks && <ErrorBox message={catalog.error} onRetry={catalog.reload} />}

        <div className="globe-wrap">
          <Globe
            objects={catalog.data?.objects ?? []}
            tracks={tracks}
            clock={clock}
            primaryNorad={norad}
            orbit={orbit?.points ?? []}
            conjunctions={source === 'live' ? conj.data?.conjunctions ?? [] : []}
            spin
            highlightIsro={highlightIsro}
            highlightSwarm={highlightSwarm}
            onSelectObject={(selectedNorad) => setNorad(selectedNorad)}
          />
          {tracks && <SimBar clock={clock} />}
        </div>

        <div className="globe-legend">
          <span><i style={{ background: '#22d3ee' }} /> {conj.data?.primary.name ?? 'primary'} orbit</span>
          <span><i style={{ background: '#10b981' }} /> 🇮🇳 ISRO satellite</span>
          <span><i style={{ background: '#ff4500' }} /> 🔥 Cosmos-1408 ASAT</span>
          <span><i style={{ background: '#ffffff' }} /> active payloads</span>
          <span><i style={{ background: '#64748b' }} /> general debris</span>
          {source === 'live' && <span><i style={{ background: '#ef4444' }} /> conjunction geometry</span>}
        </div>
      </section>

      <section className="panel list-panel enter" style={{ animationDelay: '120ms' }}>
        {showWeather && (
          <SpaceWeatherGauge data={spaceWeather.data} onClose={() => setShowWeather(false)} />
        )}
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
              <select id="primary-select" value={norad} onChange={(e) => setNorad(Number(e.target.value))} aria-label="Primary satellite">
                {isroPresets.length > 0 && (
                  <optgroup label="🇮🇳 ISRO NETRA Fleet (India)">
                    {isroPresets.map((p) => (
                      <option key={p.norad} value={p.norad}>{p.name} ({p.norad})</option>
                    ))}
                  </optgroup>
                )}
                <optgroup label="International Space Stations & Assets">
                  {otherPresets.map((p) => (
                    <option key={p.norad} value={p.norad}>{p.name} ({p.norad})</option>
                  ))}
                </optgroup>
              </select>
            </div>

            <div className="fleet-quickbar">
              <span className="quick-label muted small">Quick screen:</span>
              <button
                type="button"
                className={`quick-pill ${norad === 25544 ? 'active' : ''}`}
                onClick={() => setNorad(25544)}
              >
                ISS (25544)
              </button>
              {isroPresets.slice(0, 4).map((p) => (
                <button
                  key={p.norad}
                  type="button"
                  className={`quick-pill isro-pill ${norad === p.norad ? 'active' : ''}`}
                  onClick={() => setNorad(p.norad)}
                >
                  🇮🇳 {p.name.replace(/ \(.*\)/, '')}
                </button>
              ))}
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
                  {conj.data.conjunctions.map((c: Conjunction, i: number) => {
                    const dec = c.pc_est >= 1e-4 ? 'maneuver' : c.pc_est >= 1e-6 ? 'watch' : 'hold'
                    return (
                      <li key={`${c.secondary.norad}-${c.tca}`} className="alert-row row-in" style={{ animationDelay: `${150 + i * 55}ms` }}
                        onClick={() => c.event_id && go.alert(c.event_id)}>
                        <span className="rank mono">{i + 1}</span>
                        <span className={`decision decision-${dec}`}>{dec.toUpperCase()}</span>
                        <div className="alert-main">
                          <div className="alert-title">
                            <span className="mono">{conj.data!.primary.name}</span>
                            <span className="muted"> × {c.secondary.name} ({c.secondary.type})</span>
                          </div>
                          <div className="muted mono">
                            TCA in <span className="tick">{countdown(c.tca, now)}</span> · {c.rel_speed_kms.toFixed(1)} km/s
                          </div>
                        </div>
                        <div className="alert-nums">
                          <div className="mono big">{c.miss_km.toFixed(2)} km</div>
                          <div className="muted mono">Pc est {pcSci(c.pc_est)}</div>
                        </div>
                      </li>
                    )
                  })}
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
