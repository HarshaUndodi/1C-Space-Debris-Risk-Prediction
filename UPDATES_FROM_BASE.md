# OrbitGuard — Updates and Enhancements from Base Build

This document outlines all feature additions, UI/UX upgrades, physics modeling extensions, and architectural enhancements built on top of the base OrbitGuard specification (`SPEC.md` Milestones 0–7).

---

## Executive Summary of Enhancements

While the base build completed the core hackathon pipeline (ESA Kelvins ML model, 2D Foster $P_c$ engine, Clohessy–Wiltshire maneuver grid, and basic CesiumJS viewer), the updated system transforms OrbitGuard into an interactive, operations-grade mission control suite tailored for real-world satellite operators and space safety organizations (such as ISRO NETRA).

| Capability | Base Specification | Updated Platform |
|---|---|---|
| **Maneuver Planning** | Static Pareto front table and recommended burn point | **Interactive "What-If" Maneuver Sandbox** with custom $\Delta v$ slider, directional vector selection, lead-time tuning, live Tsiolkovsky fuel calculations, and custom plan plotting on the Pareto chart |
| **Space Weather & Drag** | Raw static F10.7 / Ap values in table | **Dynamic Space Weather & Atmospheric Drag Gauge** with NOAA storm scales (G0–G5), thermospheric density multipliers, drag uncertainty percentages, and **interactive G4 solar storm simulation** |
| **Fleet Monitoring** | ISS single primary screening | **ISRO NETRA Fleet Support** (Cartosat, RISAT, Oceansat, EOS, Astrosat) with quick-screen toolbar and custom fleet presets |
| **Debris Swarm Tracking** | Generic debris dots on globe | **Targeted Debris Cloud Overlays** (Cosmos-1408 ASAT swarm, Fengyun-1C, Iridium/Cosmos debris) with Cesium HUD mouse-hover inspection and click-to-select |
| **Voice Decision Support** | Text-only briefings | **Nova Voice Agent**: Speech recognition & synthesized voice assistant with domain glossary, casual dialogue, and telemetry query capabilities |
| **Audio-Visual Experience** | Standard static globe | Real-time SGP4 orbit animation (1×–60× time warp), micro-motion transitions, and ambient space soundscape generated via Web Audio API |
| **Single-Server Deployment** | Independent Vite dev server and FastAPI | Single-command combined production build (`make serve`) and Cloudflare tunnel sharing (`make share`) |
| **Test Suite Coverage** | ~61 core tests | **100 collected / 93 passed unit tests** covering physics, SGP4 screening, ML baselines, and API schemas |

---

## Detailed Breakdown of Updates

### 1. Interactive "What-If" Maneuver Sandbox (`ManeuverSandbox.tsx`)
In the base version, operators could only view the pre-calculated Pareto-optimal burn. In the updated version:
- **Real-Time Sliders:** Operators can adjust $\Delta v$ (from 0.001 m/s up to 1.5 m/s), burn direction (`+along`, `-along`, `+radial`, `-radial`), and lead time (6 h to 72 h).
- **Logarithmic $P_c$ Interpolation:** Dynamically computes post-burn collision probability by interpolating across the CW burn grid.
- **Tsiolkovsky Rocket Equation:** Computes exact fuel consumption:
  $$\Delta m = m_0 \left(1 - e^{-\frac{\Delta v}{I_{sp} g_0}}\right)$$
  (calibrated for typical 500 kg LEO spacecraft with 220 s $I_{sp}$).
- **Secular Drift Estimation:** Calculates physical along-track and radial separation distance at TCA.
- **Dynamic Pareto Overlay:** Directly plots the operator's custom plan alongside the automated recommendation on the Pareto frontier.

### 2. Live Space Weather & Atmospheric Drag Gauge (`SpaceWeatherGauge.tsx`, `spaceweather.py`)
Thermospheric density fluctuations during solar storms drastically degrade orbital ephemerides for low-LEO satellites:
- **NOAA Geomagnetic Scale:** Categorizes geomagnetic disturbances from G0 (Quiet) up to G5 (Extreme Storm) using real $A_p$ indices.
- **Thermospheric Density Multiplier:** Computes relative density swelling relative to quiet solar minimum conditions ($F_{10.7} = 70, A_p = 5$):
  $$\text{Multiplier} = 1.0 + \max(0, (F_{10.7} - 70) \times 0.011) + \max(0, (A_p - 5) \times 0.022)$$
- **Drag Uncertainty & Ephemeris Degradation Alerts:** Directly warns operators when low-altitude satellites (<500 km) suffer heightened in-track error.
- **Storm Simulator:** An interactive toggle to simulate a G4/G5 Extreme Coronal Mass Ejection, demonstrating how OrbitGuard advises re-screening intervals under severe space weather.

### 3. ISRO NETRA Fleet Monitoring & Debris Cloud Overlays (`Globe.tsx`, `live.py`)
- **ISRO Quick-Screen Toolbar:** Pre-configured screening shortcuts for India's primary remote sensing and earth observation assets:
  - Cartosat-2 / Cartosat-3
  - RISAT-2B / RISAT-2BR1
  - EOS-04 / EOS-06 (Oceansat-3)
  - Astrosat & Resourcesat
- **ASAT Debris Tracking:** High-visibility layer toggles for high-profile fragmentation events:
  - **Cosmos-1408 ASAT Debris Cloud** (Russian ASAT test, ~480 km altitude, intersecting ISS and SSO orbits)
  - **Fengyun-1C Debris Swarm** (~850 km altitude)
- **Cesium HUD Telemetry on Hover:** Hovering over any object in the 3D globe displays its designation, NORAD catalog ID, object class (active payload vs debris), and fleet origin.
- **Click-to-Screen:** Clicking any satellite or debris fragment immediately switches the primary tracking target.

### 4. Nova Voice AI Operations Agent (`VoiceAgent.tsx`, `agent.py`)
- Full bidirectional voice support (SpeechRecognition input + SpeechSynthesis output).
- Can operate using Claude Opus / Haiku via Anthropic API, or fallback to an offline deterministic state-machine agent.
- Capable of answering operator questions regarding:
  - Top conjunction risks and Go/No-Go decisions
  - Specific event telemetry (e.g. "Tell me about event 1568")
  - Live screening status for ISS and ISRO assets
  - Space weather conditions and solar storm status

### 5. Single-Server Mode & Tunnel Sharing (`make.ps1`, `Makefile`, `api/main.py`)
- Integrated static file serving: FastAPI serves the compiled React production bundle directly when running in unified mode.
- One-line launch commands:
  - `.\make.ps1 serve` — Builds the web client and starts FastAPI on port 8000.
  - `.\make.ps1 share` — Automatically opens a secure public Cloudflare Tunnel for live remote judging and demos.

### 6. Expanded Test Suite
- Expanded from the initial 61 tests to **100 collected test items** (`tests/`):
  - `test_physics.py`: Foster 2D $P_c$ integration, Clohessy–Wiltshire state transition matrices, Pareto monotonicity.
  - `test_agent.py`: Nova voice agent intent classification and conversation workflows.
  - `test_live.py`: SGP4 catalog propagation, close approach screening, and preset filtering.
  - `test_celestrak_cache.py`: Cache compliance and rate limiting rules.
  - `test_leakage.py`: Strict temporal cutoff verification on Kelvins CDMs.
  - `test_api_contract.py`: Pydantic schema validation for mock and live endpoints.
- **Pass rate:** 93 passed, 7 skipped (offline mode tests), 0 failures.
