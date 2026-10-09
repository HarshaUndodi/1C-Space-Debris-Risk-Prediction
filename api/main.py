"""OrbitGuard FastAPI app — SPEC Section 13.

Modes (API_MODE): "mock" serves api/mock/*.json; "real" serves artifacts (demo_events.json,
metrics.json, live screening cache); "auto" (default) = real when artifacts exist, mock otherwise.
Every real endpoint falls back to its mock if its artifact is missing — the demo must never crash.
Nothing is computed in request handlers except cheap lookups (live screening runs in a background
thread at startup, see orbitguard.live).

Run: uvicorn api.main:app --port 8000
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api import schemas
from orbitguard import config, download, spaceweather

log = logging.getLogger("orbitguard.api")
MOCK_DIR = Path(__file__).resolve().parent / "mock"


@lru_cache(maxsize=None)
def mock(name: str) -> Any:
    return json.loads((MOCK_DIR / name).read_text())


class Store:
    """Lazily loaded artifacts; `mode` decides mock vs real."""

    def __init__(self, mode: str | None = None):
        self.requested = (mode or config.API_MODE or "auto").lower()
        self._demo: dict | None = None
        self._demo_mtime: float | None = None

    @property
    def mode(self) -> str:
        if self.requested in ("mock", "real"):
            return self.requested
        return "real" if config.DEMO_EVENTS_PATH.exists() else "mock"

    def demo(self) -> dict | None:
        if self.mode != "real" or not config.DEMO_EVENTS_PATH.exists():
            return None
        mtime = config.DEMO_EVENTS_PATH.stat().st_mtime
        if self._demo is None or mtime != self._demo_mtime:   # pick up a rebuilt file without restart
            self._demo = json.loads(config.DEMO_EVENTS_PATH.read_text())
            self._demo_mtime = mtime
        return self._demo

    def live(self):
        if self.mode != "real":
            return None
        try:
            from orbitguard import live
        except ImportError:
            return None
        return live.service()


store = Store()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    svc = store.live()
    if svc is not None:
        svc.start_background()   # screens the cached catalog once, refreshes every 2 h
    yield


app = FastAPI(title="OrbitGuard API", version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2048)   # tracks are a few MB of numbers; ~4× smaller gzipped
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
router = APIRouter(prefix="/api")

ALERT_KEYS = list(schemas.AlertItem.model_fields)
DETAIL_KEYS = list(schemas.AlertDetail.model_fields)


def ranked(alerts: list[dict]) -> list[dict]:
    """Rank by calibrated probability, then P50 risk (both descending). Live items have no p_high."""
    return sorted(alerts, key=lambda a: (a["p_high"] if a["p_high"] is not None else -1.0, a["risk_p50"]), reverse=True)


def _event(eid: str) -> dict:
    demo = store.demo()
    ev = demo["events"].get(eid) if demo else None
    if ev is None:
        raise HTTPException(404, f"event {eid} not found")
    return ev


@router.get("/health", response_model=schemas.Health)
def health() -> dict:
    return {"status": "ok", "model_loaded": store.demo() is not None,
            "catalog_age_hours": download.catalog_age_hours(), "mode": store.mode}


@router.get("/alerts", response_model=list[schemas.AlertItem])
def alerts(source: schemas.Source = "historical", limit: int = Query(50, ge=1, le=1000), cutoff: int = 2) -> list[dict]:
    demo = store.demo()
    if demo is None:
        items = [a for a in mock("alerts.json") if a["source"] == source]
        return ranked(items)[:limit]
    if source == "live":
        svc = store.live()
        return ranked(svc.alerts())[:limit] if svc else []
    items = [{k: e["cutoffs"][str(cutoff)][k] for k in ALERT_KEYS}
             for e in demo["events"].values() if str(cutoff) in e["cutoffs"]]
    return ranked(items)[:limit]


@router.get("/alerts/{event_id}", response_model=schemas.AlertDetail)
def alert_detail(event_id: str, cutoff: int = 2) -> dict:
    if event_id.startswith("live-") and store.mode == "real":
        svc = store.live()
        detail = svc.detail(event_id) if svc else None
        if detail is None:
            raise HTTPException(404, f"live event {event_id} not found (screening refreshed?)")
        return detail
    if store.demo() is None:
        detail = mock("alert_details.json").get(event_id)
        if detail is None:
            raise HTTPException(404, f"event {event_id} not found")
        if cutoff not in detail["available_cutoffs"]:
            raise HTTPException(422, f"cutoff must be one of {detail['available_cutoffs']}")
        return detail
    ev = _event(event_id)
    available = sorted((int(c) for c in ev["cutoffs"]), reverse=True)
    if str(cutoff) not in ev["cutoffs"]:
        raise HTTPException(422, f"no CDMs >= {cutoff} days before TCA for this event; cutoffs: {available}")
    c = ev["cutoffs"][str(cutoff)]
    return {**{k: c[k] for k in ALERT_KEYS}, "cdm_history": ev["cdm_history"], "available_cutoffs": available,
            "shap_top": c["shap_top"], "briefing": c["briefing"], "briefing_source": c["briefing_source"],
            "true_final_risk": ev["true_final_risk"]}


@router.get("/alerts/{event_id}/maneuver", response_model=schemas.ManeuverResult)
def alert_maneuver(event_id: str) -> dict:
    if store.demo() is None:
        result = mock("maneuvers.json").get(event_id)
        if result is None:
            raise HTTPException(404, f"no maneuver for event {event_id}")
        return result
    if event_id.startswith("live-"):
        svc = store.live()
        result = svc.maneuver(event_id) if svc else None
        if result is None:
            raise HTTPException(404, f"no maneuver for {event_id}")
        return result
    man = _event(event_id)["cutoffs"].get("2", {}).get("maneuver")
    if not man or "points" not in man:
        raise HTTPException(404, f"no maneuver for event {event_id} (incomplete covariance in its CDM)")
    return man


@router.get("/live/catalog", response_model=schemas.LiveCatalog)
def live_catalog(limit: int = Query(3000, ge=1, le=50000)) -> dict:
    svc = store.live()
    if svc is None or (cat := svc.catalog(limit)) is None:
        cat = mock("live_catalog.json")
        return {"epoch": cat["epoch"], "objects": cat["objects"][:limit]}
    return cat


def _mock_tracks(limit: int, minutes: float, step_s: float) -> dict:
    """Mock mode: the mock catalog's fixed positions, repeated (objects don't move)."""
    import math
    cat = mock("live_catalog.json")
    objs, samples = [], []
    n = int(minutes * 60 // step_s) + 1
    for o in cat["objects"][:limit]:
        r = 6371.0 + o["alt_km"]
        la, lo = math.radians(o["lat"]), math.radians(o["lon"])
        xyz = [round(r * math.cos(la) * math.cos(lo), 1), round(r * math.cos(la) * math.sin(lo), 1), round(r * math.sin(la), 1)]
        objs.append({"norad": o["norad"], "name": o["name"], "type": o["type"]})
        samples.append(xyz * n)
    return {"start": cat["epoch"], "step_s": step_s, "n_steps": n, "objects": objs, "samples_km": samples}


@router.get("/live/tracks", response_model=schemas.LiveTracks)
def live_tracks(limit: int = Query(2000, ge=1, le=6000), minutes: float = Query(30, gt=0, le=120),
                step_s: float = Query(30, ge=5, le=300), start: str | None = None) -> dict:
    """Short-window SGP4 tracks for real-time globe animation (start = ISO UTC, default now)."""
    svc = store.live()
    if svc is None:
        return _mock_tracks(limit, minutes, step_s)
    when = None
    if start:
        try:
            when = datetime.fromisoformat(start.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "start must be ISO-8601 UTC, e.g. 2026-10-09T12:00:00Z")
    res = svc.tracks(limit, minutes, step_s, when)
    if res is None:
        raise HTTPException(503, "catalog not loaded yet")
    return res


@router.get("/live/conjunctions", response_model=schemas.LiveConjunctions)
def live_conjunctions(norad: int = config.DEFAULT_PRIMARY_NORAD, hours: float = 72) -> dict:
    svc = store.live()
    if svc is None:
        return mock("live_conjunctions.json")
    res = svc.conjunctions(norad, hours)
    if res is None:
        raise HTTPException(503, "screening in progress — retry in a few seconds")
    return res


@router.get("/live/orbit/{norad}", response_model=schemas.OrbitPath)
def live_orbit(norad: int, minutes: float = Query(90, gt=0, le=1440), step_s: float = Query(30, ge=5, le=600),
               start: str | None = None) -> dict:
    svc = store.live()
    if svc is None:
        return mock("live_orbit.json")
    when = None
    if start:
        try:
            when = datetime.fromisoformat(start.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "start must be ISO-8601 UTC")
    res = svc.orbit(norad, minutes, step_s, when)
    if res is None:
        raise HTTPException(404, f"NORAD {norad} not in the cached catalog")
    return res


@router.get("/live/presets")
def live_presets() -> list[dict]:
    """Selectable primaries: ISS + Indian satellites found by name in the cached catalog (ids never hard-coded)."""
    svc = store.live()
    if svc is None:
        return [{"norad": 25544, "name": "ISS (ZARYA)"}]
    return svc.presets()


@router.get("/metrics", response_model=schemas.Metrics)
def metrics() -> dict:
    if store.mode == "real" and config.METRICS_PATH.exists():
        return json.loads(config.METRICS_PATH.read_text())
    return mock("metrics.json")


@router.get("/space-weather", response_model=schemas.SpaceWeather)
def space_weather() -> dict:
    if store.mode == "real":
        sw = spaceweather.latest()
        if sw:
            return sw
    return mock("space_weather.json")


app.include_router(router)

# Serve the built dashboard (web/dist) from the same origin, so one port / one tunnel URL carries
# both the UI and /api. The app uses hash routing, so index.html is the only page.
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if WEB_DIST.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
