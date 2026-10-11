import { useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import type { LiveCdmPredictionResult, LiveCdmSample } from '../types'
import { oneInN, pcSci } from '../format'

export function LiveCdmPredictor({ onClose }: { onClose?: () => void }) {
  const [samples, setSamples] = useState<LiveCdmSample[]>([])
  const [selectedSampleId, setSelectedSampleId] = useState<string>('')

  // Form fields
  const [eventId, setEventId] = useState('ISRO-CARTOSAT-2F-2026-10')
  const [daysToTca, setDaysToTca] = useState(2.1)
  const [missM, setMissM] = useState(165.0)
  const [relSpeedKms, setRelSpeedKms] = useState(12.4)
  const [risk, setRisk] = useState(2.4e-4)
  const [chaserType, setChaserType] = useState('DEBRIS')
  const [tSigmaR, setTSigmaR] = useState(35.0)
  const [tSigmaT, setTSigmaT] = useState(110.0)
  const [tSigmaN, setTSigmaN] = useState(35.0)
  const [cSigmaR, setCSigmaR] = useState(130.0)
  const [cSigmaT, setCSigmaT] = useState(480.0)
  const [cSigmaN, setCSigmaN] = useState(130.0)
  const [cutoff, setCutoff] = useState(2)

  // Prediction state
  const [predicting, setPredicting] = useState(false)
  const [result, setResult] = useState<LiveCdmPredictionResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const applySample = (s: LiveCdmSample) => {
    setSelectedSampleId(s.id)
    setEventId(s.data.event_id)
    setDaysToTca(s.data.time_to_tca_days)
    setMissM(s.data.miss_distance_m)
    setRelSpeedKms(s.data.rel_speed_kms)
    setRisk(s.data.risk)
    setChaserType(s.data.chaser_type)
    if (s.data.target_sigmas_m) {
      setTSigmaR(s.data.target_sigmas_m[0])
      setTSigmaT(s.data.target_sigmas_m[1])
      setTSigmaN(s.data.target_sigmas_m[2])
    }
    if (s.data.chaser_sigmas_m) {
      setCSigmaR(s.data.chaser_sigmas_m[0])
      setCSigmaT(s.data.chaser_sigmas_m[1])
      setCSigmaN(s.data.chaser_sigmas_m[2])
    }
    if (s.data.cutoff) {
      setCutoff(s.data.cutoff)
    }
  }

  // Load sample CDMs on mount
  useEffect(() => {
    let active = true
    api.liveCdmSamples()
      .then((data) => {
        if (!active) return
        setSamples(data)
        if (data.length > 0) {
          applySample(data[0])
        }
      })
      .catch((err) => {
        if (!active) return
        setError(errorMessage(err))
      })
    return () => {
      active = false
    }
  }, [])

  const handlePredict = async () => {
    setPredicting(true)
    setError(null)
    try {
      const payload = {
        event_id: eventId,
        time_to_tca_days: Number(daysToTca),
        miss_distance_m: Number(missM),
        rel_speed_kms: Number(relSpeedKms),
        risk: Number(risk),
        chaser_type: chaserType,
        target_sigmas_m: [Number(tSigmaR), Number(tSigmaT), Number(tSigmaN)],
        chaser_sigmas_m: [Number(cSigmaR), Number(cSigmaT), Number(cSigmaN)],
        cutoff: Number(cutoff),
      }
      const res = await api.predictLiveCdm(payload)
      setResult(res)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setPredicting(false)
    }
  }

  return (
    <div className="live-cdm-card">
      <div className="live-cdm-header">
        <div className="live-cdm-title-wrap">
          <span className="live-cdm-badge-pulse" />
          <span className="live-cdm-title">Live Conjunction Data Message (CDM) Ingestion & Predictor</span>
          <span className="live-cdm-tag mono">LIGHTGBM + CW ENGINE</span>
        </div>
        {onClose && (
          <button type="button" className="sw-close" onClick={onClose} aria-label="Close CDM predictor">
            ×
          </button>
        )}
      </div>

      <p className="live-cdm-subtitle muted small">
        Inject real-time radar Conjunction Data Messages (CDMs) from ISRO NETRA, ESA, or Space-Track to instantly
        evaluate collision risk, calculate LightGBM TreeSHAP drivers, and plan optimal thruster avoidance maneuvers.
      </p>

      {/* Preset Quick Select */}
      <div className="cdm-preset-bar">
        <span className="quick-label muted small">Sample Live CDMs:</span>
        {samples.map((s) => (
          <button
            key={s.id}
            type="button"
            className={`quick-pill ${selectedSampleId === s.id ? 'active' : ''}`}
            onClick={() => applySample(s)}
          >
            {s.title}
          </button>
        ))}
      </div>

      {/* Form Fields Grid */}
      <div className="cdm-grid">
        <div className="cdm-field">
          <label className="cdm-label">Event Identifier</label>
          <input
            type="text"
            className="cdm-input mono"
            value={eventId}
            onChange={(e) => setEventId(e.target.value)}
          />
        </div>

        <div className="cdm-field">
          <label className="cdm-label">Time to TCA (Days)</label>
          <input
            type="number"
            step="0.1"
            className="cdm-input mono"
            value={daysToTca}
            onChange={(e) => setDaysToTca(Number(e.target.value))}
          />
        </div>

        <div className="cdm-field">
          <label className="cdm-label">Miss Distance (meters)</label>
          <input
            type="number"
            step="1"
            className="cdm-input mono"
            value={missM}
            onChange={(e) => setMissM(Number(e.target.value))}
          />
        </div>

        <div className="cdm-field">
          <label className="cdm-label">Closing Speed (km/s)</label>
          <input
            type="number"
            step="0.1"
            className="cdm-input mono"
            value={relSpeedKms}
            onChange={(e) => setRelSpeedKms(Number(e.target.value))}
          />
        </div>

        <div className="cdm-field">
          <label className="cdm-label">Initial PoC (1e-N)</label>
          <input
            type="number"
            step="1e-6"
            className="cdm-input mono"
            value={risk}
            onChange={(e) => setRisk(Number(e.target.value))}
          />
        </div>

        <div className="cdm-field">
          <label className="cdm-label">Chaser Object Type</label>
          <select
            className="cdm-input mono"
            value={chaserType}
            onChange={(e) => setChaserType(e.target.value)}
          >
            <option value="DEBRIS">DEBRIS</option>
            <option value="PAYLOAD">PAYLOAD</option>
            <option value="ROCKET BODY">ROCKET BODY</option>
            <option value="UNKNOWN">UNKNOWN</option>
          </select>
        </div>

        <div className="cdm-field">
          <label className="cdm-label">Target Uncertainty (R, T, N m)</label>
          <div className="sigmas-row mono small">
            <input
              type="number"
              className="cdm-input-sub mono"
              title="Radial"
              value={tSigmaR}
              onChange={(e) => setTSigmaR(Number(e.target.value))}
            />
            <input
              type="number"
              className="cdm-input-sub mono"
              title="Along-track"
              value={tSigmaT}
              onChange={(e) => setTSigmaT(Number(e.target.value))}
            />
            <input
              type="number"
              className="cdm-input-sub mono"
              title="Cross-track"
              value={tSigmaN}
              onChange={(e) => setTSigmaN(Number(e.target.value))}
            />
          </div>
        </div>

        <div className="cdm-field">
          <label className="cdm-label">Chaser Uncertainty (R, T, N m)</label>
          <div className="sigmas-row mono small">
            <input
              type="number"
              className="cdm-input-sub mono"
              title="Radial"
              value={cSigmaR}
              onChange={(e) => setCSigmaR(Number(e.target.value))}
            />
            <input
              type="number"
              className="cdm-input-sub mono"
              title="Along-track"
              value={cSigmaT}
              onChange={(e) => setCSigmaT(Number(e.target.value))}
            />
            <input
              type="number"
              className="cdm-input-sub mono"
              title="Cross-track"
              value={cSigmaN}
              onChange={(e) => setCSigmaN(Number(e.target.value))}
            />
          </div>
        </div>
      </div>

      <div className="cdm-action-row">
        <button
          type="button"
          className="cdm-predict-btn"
          onClick={handlePredict}
          disabled={predicting}
        >
          {predicting ? '⚡ Evaluating LightGBM ML Core...' : '⚡ Predict Risk & Plan Avoidance'}
        </button>
      </div>

      {error && <div className="error-box mt-2">{error}</div>}

      {/* Results View */}
      {result && (
        <div className="cdm-results-container enter">
          <div className="cdm-results-header">
            <div className="cdm-decision-badge-wrap">
              <span className={`pill pill-${result.decision.toLowerCase()}`}>
                {result.decision}
              </span>
              <span className="mono bold cdm-res-title">
                {result.event_id} · TCA in {result.time_to_tca_days}d
              </span>
            </div>
            <div className="cdm-probs mono">
              <span>
                P(high risk): <strong>{(result.p_high ? (result.p_high * 100).toFixed(1) : '0.0')}%</strong>
              </span>
              <span className="sep">·</span>
              <span>
                Risk P50: <strong>{oneInN(result.risk_p50)}</strong>
              </span>
              <span className="sep">·</span>
              <span className="muted">
                Band: [{oneInN(result.risk_p10)} – {oneInN(result.risk_p90)}]
              </span>
            </div>
          </div>

          {/* 3-line Operator Briefing */}
          <div className="cdm-briefing-box">
            {result.briefing.map((ln, i) => (
              <div key={i} className="briefing-line mono small">
                {ln}
              </div>
            ))}
          </div>

          {/* Side-by-side SHAP + Maneuver */}
          <div className="cdm-split-grid">
            {/* SHAP drivers */}
            <div className="cdm-shap-box">
              <span className="box-heading mono small muted">TOP EXPLAINABILITY DRIVERS (TreeSHAP)</span>
              <div className="shap-list">
                {result.shap_top.map((s) => (
                  <div key={s.feature} className="shap-item-row">
                    <div className="shap-label-row">
                      <span className="shap-name">{s.label}</span>
                      <span className="shap-val mono small">{s.shap >= 0 ? `+${s.shap.toFixed(2)}` : s.shap.toFixed(2)}</span>
                    </div>
                    <div className="shap-bar-bg">
                      <div
                        className={`shap-bar-fill ${s.shap >= 0 ? 'shap-pos' : 'shap-neg'}`}
                        style={{ width: `${Math.min(100, Math.abs(s.shap) * 45)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Recommended Avoidance Burn */}
            <div className="cdm-maneuver-box">
              <span className="box-heading mono small muted">RECOMMENDED AVOIDANCE BURN (CW Engine)</span>
              {result.maneuver && result.maneuver.recommended ? (
                <div className="maneuver-rec-body">
                  <div className="rec-stat-row">
                    <span className="muted small">Required Burn:</span>
                    <span className="mono bold rec-val">
                      {result.maneuver.recommended.dv_ms.toFixed(3)} m/s ({result.maneuver.recommended.direction})
                    </span>
                  </div>
                  <div className="rec-stat-row">
                    <span className="muted small">Execution Time:</span>
                    <span className="mono rec-val">
                      {result.maneuver.recommended.burn_lead_h} hours before TCA
                    </span>
                  </div>
                  <div className="rec-stat-row">
                    <span className="muted small">Residual Pc:</span>
                    <span className="mono rec-val safe-green">
                      {pcSci(result.maneuver.recommended.post_pc)} (Safe: &lt; 1e-6)
                    </span>
                  </div>
                  <div className="rec-stat-row">
                    <span className="muted small">Propellant Cost:</span>
                    <span className="mono rec-val text-warning">
                      {result.maneuver.recommended.propellant_g.toFixed(1)} g fuel
                    </span>
                  </div>
                </div>
              ) : (
                <p className="muted small">No maneuver required. Trajectory is nominal.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
