# OrbitGuard

KLE Tech Hackfest 2026 · Challenge 1C: Space Debris Risk Prediction.
Calibrated, explained, fuel-aware Go / No-Go collision decisions for LEO. Full spec: [SPEC.md](SPEC.md).

## Run (Windows: use `.\make.ps1 <target>`; elsewhere `make <target>`)

```
make setup     # venv + pip install + npm install (web/)
make data      # cached downloads: ESA Kelvins CDMs, CelesTrak OMM groups, SW-All.csv
make api       # FastAPI on http://localhost:8000/api  (mock JSON until Milestone 2)
make web       # dashboard on http://localhost:5173
make test      # pytest
make mocks     # regenerate api/mock/*.json
```

Copy `.env.example` to `.env`. No Cesium Ion token is needed — the globe uses Cesium's bundled
Natural Earth II imagery and works offline.

**CelesTrak etiquette:** each group is cached for 2 h and never re-downloaded sooner; any non-200
stops all CelesTrak requests for that run. A snapshot is kept in `artifacts/catalog_snapshot/` for offline demos.

## Status

- [x] Milestone 0 — skeleton, cached downloads, API contract with mocks, React + Cesium shell
- [ ] Milestone 1 — ML core
- [ ] Milestone 2 — trust layer
- [ ] Milestone 3 — physics
- [ ] Milestone 4 — historical dashboard (MVP)
- [ ] Milestone 5 — live mode
- [ ] Milestone 6 — polish

Imagery: Natural Earth II (public domain), via CesiumJS (Apache-2.0).
