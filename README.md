# OrbitGuard

**KLE Tech Hackfest 2026 · Challenge 1C: Space Debris Risk Prediction.**
OrbitGuard turns noisy conjunction alerts into calibrated, explained, fuel-aware **Go / No-Go** decisions
for satellites in Low Earth Orbit. It's built on real ESA conjunction data and the live US catalog.
Full build spec: [SPEC.md](SPEC.md).

| What the brief asks for | What OrbitGuard does |
|---|---|
| Parse noisy orbital data | ESA Kelvins CDMs (162k rows / 13k events), the live CelesTrak OMM catalog (19k objects), and CelesTrak space weather |
| Calibrated confidence | Isotonic-calibrated P(high risk) plus a P10–P90 band on the final risk |
| Ranked alerts | MANEUVER / WATCH / HOLD, ranked by calibrated probability |
| Fuel-efficient maneuvers | Clohessy–Wiltshire burn search over size × direction × timing, Pareto front, propellant mass, and an **interactive "What-If" thruster simulator** |
| Explain why | SHAP drivers in plain English plus a three-line operator briefing (LLM or template fallback) |
| Space weather & drag impact | Real-time NOAA geomagnetic storm scales (G0–G5), thermospheric density swelling multiplier, and live solar storm simulator |
| Fleet & swarm tracking | **ISRO NETRA fleet screening** (Cartosat, RISAT, Oceansat, EOS) + targeted tracking for Cosmos-1408 & ASAT debris clouds |

> 📘 **See [UPDATES_FROM_BASE.md](UPDATES_FROM_BASE.md) for a complete list of all features, enhancements, and architectural upgrades added to the base specification.**

## Quick start

Requirements: Python 3.11+ (developed on 3.14) and Node 20+. On Windows, use `.\make.ps1 <target>`
anywhere this README says `make <target>`.

```
make setup     # venv + pip install -r requirements.txt + npm install (web/)
make data      # cached downloads: ESA Kelvins (Zenodo, ~216 MB), CelesTrak groups, SW-All.csv
make train     # event tables for cutoffs 2-6 d + LightGBM fold ensembles  (~3 min)
make eval      # metrics.json + plots, Pc-engine validation vs ESA risk
make demo      # artifacts/demo_events.json (30 held-out events, precomputed)
make live      # screen the ISS against the cached catalog (also runs at API startup)
make api       # FastAPI on http://localhost:8000/api
make web       # dashboard on http://localhost:5173
make test      # pytest (100 collected / 93 passed tests)
```

To share it: `make serve` (dashboard and API on one port), then `make share` for a public Cloudflare link.

In the dashboard, the globe animates about 1,500 real catalog objects along their SGP4 tracks (time warp
1× / 10× / 60×), charts and numbers build in, and ambient space music (generated live in the browser with the
Web Audio API) plays continuously from the visitor's first click, because browsers block sound until then.

### Key Extended Capabilities
- **🎯 Interactive "What-If" Maneuver Sandbox:** Adjust $\Delta v$ magnitude (0.001 to 1.5 m/s), thrust direction (+along, -along, +radial, -radial), and burn lead time. Real-time Tsiolkovsky propellant calculation ($\Delta m = m_0(1 - e^{-\Delta v / I_{sp} g_0})$) and dynamic Pareto frontier plotting.
- **☀️ Space Weather & Atmospheric Drag Gauge:** Real-time solar radio flux ($F_{10.7}$) and geomagnetic ($A_p$) indices, NOAA storm scale ratings (G0–G5), thermospheric density multiplier, and an interactive G4 solar storm simulation toggle.
- **🇮🇳 ISRO NETRA Fleet Monitoring:** Dedicated one-click screening shortcuts for Indian satellites (Cartosat, RISAT, Oceansat, Astrosat, EOS).
- **🔥 Cosmos-1408 ASAT & Debris Swarms:** Visual overlay toggles for major fragmentation clouds with Cesium HUD mouse hover inspection and click-to-select tracking.
- **🎙️ Nova Voice Assistant:** Voice-enabled operations agent (speech in/out) for hands-free telemetry queries, Go/No-Go status briefings, and event diagnostics.

All artifacts (models, metrics, demo events, catalog snapshot) are committed, so **`make api` + `make web`
runs the full demo offline on a fresh clone**. You don't need a Cesium Ion token (the globe uses Cesium's
bundled Natural Earth II imagery) or an LLM key (the template briefing is always available).

Optional `.env` (copy `.env.example`): set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=...` for
LLM-written briefings (Claude Haiku 4.5, 8 s timeout, template fallback). Set `API_MODE=mock` to serve
the Milestone-0 mock JSON instead.

**CelesTrak etiquette (mandatory):** each group is cached for 2 h and is never re-downloaded sooner. Any
non-200 response stops all CelesTrak requests for that run. Live mode reads only the cache or the snapshot.

## Results: held-out ESA Kelvins test set

Every number below is from `artifacts/metrics.json`: 2,167 test events, **150 high-risk** (PoC ≥ 1e-6).
Decisions are made 2 days before TCA. The test set was never used to make any modelling choice.

| Metric | Model | Baseline (latest CDM) | Verdict |
|---|---|---|---|
| Recall on high-risk events at the ≥95%-recall operating point | **94.7%** | 94.0% | tie |
| False-alarm rate at that operating point | **18.4%** | 21.4% | model |
| False-alarm rate at 94% recall (curve diagnostic) | **12.0%** | 19.4% | model |
| Recall ≥ 97% achievable? | yes, at a 31.8% false-alarm rate | **no**: needs 100% flagged | model |
| Brier score (calibration) | **0.0530** | 0.0563 | model |
| AUC-PR / ROC-AUC | **0.680 / 0.962** | 0.665 / 0.945 | model |
| Kelvins score L = MSE_HR / F2 (lower is better) | 0.995 | **0.981** (floored at 1e-6.5) · 36.05 raw | tie (baseline marginally) |
| P10–P90 band coverage | 93.9% (target ≈ 80%) | n/a | band is conservative |

**What we claim:** the model matches the naive baseline at its operating point and beats it on
calibration and ranking. It is the only one of the two that reaches **>95% recall without flagging
everything**: some real threats have a negligible latest-CDM risk, so the baseline would have to flag
every event to catch them.

**What we don't claim:** the risk *regressor* does not beat the (floored) latest-CDM baseline on the
Kelvins score (0.995 vs 0.981, MSE_HR 0.737 vs 0.725, F2 0.741 vs 0.739). That's a tie, matching the
original competition, where the naive baseline was famously hard to beat. Flooring alone takes the raw
baseline from 36.05 to 0.98.

**Lead time** (recall / false-alarm rate, model vs baseline, same 150 events):

| Days before TCA | 6 | 5 | 4 | 3 | 2 |
|---|---|---|---|---|---|
| Model recall | 64% | 66% | 81% | 90% | 95% |
| Baseline recall | 60% | 65% | 74% | 85% | 94% |
| Model false alarms | 76% | 36% | 88% | 54% | 18% |
| Baseline false alarms | 46% | 40% | 47% | 38% | 21% |

Earlier warnings cost far more false alarms. At 3+ days, ≥95%-recall thresholds flag most events.

**Physics validation:** our 2D Foster Pc engine against ESA's own `risk` on 20k CDMs gives Spearman **0.975**,
a median difference of 0.12 orders of magnitude, and 82% agreement within 10×.
**Throughput:** ISS against **19,376 catalog objects over 72 h** (60 s grid + 1 s TCA refinement) takes
**1.2 s**, plus 0.5 s of catalog parsing. The optional all-vs-all benchmark
(`python -m orbitguard.screen --all-vs-all --hours 24`) checks every pair of 18,589 LEO objects over 24 h
with KD-trees in **34 s**. Pairs are sampled, not refined, so this is a throughput figure, not a risk list.

## Architecture

```
ESA Kelvins CDMs ─▶ features.py (no-leakage event table, cutoffs 2–6 d)
                    models.py   (5-fold LightGBM ensembles: regressor, classifier, P10/P90)
                    calibrate.py(isotonic on out-of-fold, τ for ≥95% recall)
                    explain.py  (TreeSHAP drivers, LLM/template briefing)  decision.py (Go/No-Go)
                    pc.py       (2D Foster Pc)  cw.py (Clohessy–Wiltshire)  maneuver.py (burn search)
CelesTrak OMM ───▶  screen.py   (SGP4 catalog screening)  live.py (background service, J2 check)
                    evaluate.py → artifacts/metrics.json     build_demo.py → artifacts/demo_events.json
                                          │
                              api/ (FastAPI, Section 13 contract, mock + real)
                                          │
                     web/ (React + Vite + CesiumJS + Recharts mission-control dashboard)
```

## Modelling notes (deviations from SPEC.md, each chosen on training data only)

1. **Cutoff 6 replaces 7.** Kelvins CDMs start less than 7 days before TCA (max 6.99 d).
2. **Out-of-fold calibration instead of a 20% validation split.** Only 66 training events are high-risk,
   which would leave about 7 for calibration. τ and the isotonic map use 5-fold out-of-fold predictions,
   and production predictions come from the same fold models (CV bagging), so the threshold transfers.
3. **τ is set on the raw classifier score.** Isotonic output is a step function, and its lowest step
   holds most events. Because the map is monotone, this is the spec's rule with ties broken by the raw score.
4. **Risk floor −6.5.** About 40% of CDMs sit at ESA's −30 "negligible" floor, which dominates any L2
   fit. Only accuracy above −6 is scored, so regressions use max(risk, −6.5) and report "< 1 in 3.2 million".
5. **The regressor predicts the residual from the latest CDM**, shrunk by α (picked out of fold). Direct
   regression lost badly to the baseline.
6. **Test event ids are namespaced.** Kelvins numbers train and test events independently, and all
   2,167 test ids also occur in train.
7. **P10 ≤ P50 ≤ P90 is enforced by widening the band around the point estimate**, not by sorting. At long
   lead times the quantile models collapse to the floor, and sorting dragged P50 down with them.
8. **The live coarse screening gate scales with the time step** (½ · 15.5 km/s · step). A fixed 50 km
   gate at 60 s steps misses most crossings at 6–15 km/s. This was cross-checked against a 10 s grid.

## Demo script (about 5 minutes)

1. **Hook (30 s):** "It's 2 a.m. An operator has 300 alerts this week, and 99% are noise. One is real. Which one?"
2. **Live sky (45 s):** Mission Control → **Live (CelesTrak)**. The real catalog around the ISS:
   "we screened 19,376 objects over 72 hours in 1.2 seconds." Click a close approach to show the
   estimated Pc with its stated assumptions.
3. **Triage (60 s):** **Historical**. The ranked list puts real threats on top. Open **EVT 1568**
   (debris; the actual final risk was about 1 in 134).
4. **Trust (60 s):** the CDM history with the P10–P90 band, the SHAP drivers, and the three-line briefing.
   Drag **replay** to 6 days: WATCH at 6 d, MANEUVER from 5 d onward.
5. **Action (45 s):** the maneuver chart. A 1.5 mm/s along-track burn 48 h out brings Pc from 1.5e-4 to
   2.8e-7 with 0.34 g of fuel. To reach the same target 6 h out takes 4.8× the Δv. Export the regulator report.
6. **Proof (45 s):** the Metrics page. Recall and false alarms vs the ESA baseline, Brier, lead time.
   **Say where we tie and where the baseline wins** (Kelvins score). Show EVT 1259 as an honest false alarm.
7. **Close (15 s):** "OrbitGuard turns noisy alerts into calibrated, explained, fuel-aware decisions, built
   on real ESA data and the live US catalog. Next: covariance-aware live data, RL maneuver planning, ISRO
   operator workflows."

## Known limitations

- Live catalog data has no covariance, so live Pc uses assumed, age-grown sigmas and a 20 m hard-body
  radius. The trained risk model runs on ESA CDMs, which do carry covariance. Live mode is screening;
  historical mode is risk assessment.
- Kelvins covers a handful of ESA missions from 2015–2019. Generalisation to other operators is untested.
- The test set over-represents high-risk events (6.9% vs 0.8% in training), so calibrated probabilities
  read low on test (see the reliability diagram).
- Clohessy–Wiltshire is linear and assumes near-circular orbits. It's suitable for ranking burn options,
  not for flight-ready planning. The grid's smallest burn is 1 mm/s.
- High-risk events are rare (150 test, 66 train), so every metric on them has wide uncertainty.
- Not built (cut list): LSTM sequence model, Space-Track integration.

## Repository layout

```
orbitguard/   Python package (one module per spec section)
api/          FastAPI app, Pydantic schemas (= Section 13 contract), mock JSON
web/          React + Vite + TypeScript + CesiumJS + Recharts dashboard
tests/        pytest: Pc, CW, maneuvers, leakage, baseline, API contract (mock+real), cache, live, briefing
artifacts/    models, metrics.json, plots/, demo_events.json, live_screen.json, catalog_snapshot/
data/         raw downloads + processed parquet (gitignored)
```

Data: ESA Kelvins Collision Avoidance Challenge (Zenodo 4463683); CelesTrak GP/OMM and SW-All.csv.
Imagery: Natural Earth II (public domain), via CesiumJS (Apache-2.0).
