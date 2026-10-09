"""OrbitGuard FastAPI app — SPEC Section 13.

Milestone 0: every endpoint serves mock JSON from api/mock/. Later milestones swap in real
artifacts (demo_events.json, metrics.json, screening cache) behind API_MODE=real.
Run: uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api import schemas
from orbitguard import download

MOCK_DIR = Path(__file__).resolve().parent / "mock"

app = FastAPI(title="OrbitGuard API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
router = APIRouter(prefix="/api")


@lru_cache(maxsize=None)
def mock(name: str) -> Any:
    return json.loads((MOCK_DIR / name).read_text())


def ranked(alerts: list[dict]) -> list[dict]:
    """Rank by calibrated probability, then P50 risk (both descending)."""
    return sorted(alerts, key=lambda a: (a["p_high"], a["risk_p50"]), reverse=True)


@router.get("/health", response_model=schemas.Health)
def health() -> dict:
    h = dict(mock("health.json"))
    h["catalog_age_hours"] = download.catalog_age_hours()
    return h


@router.get("/alerts", response_model=list[schemas.AlertItem])
def alerts(source: schemas.Source = "historical", limit: int = Query(50, ge=1, le=1000)) -> list[dict]:
    items = [a for a in mock("alerts.json") if a["source"] == source]
    return ranked(items)[:limit]


@router.get("/alerts/{event_id}", response_model=schemas.AlertDetail)
def alert_detail(event_id: str, cutoff: int = 2) -> dict:
    detail = mock("alert_details.json").get(event_id)
    if detail is None:
        raise HTTPException(404, f"event {event_id} not found")
    if cutoff not in detail["available_cutoffs"]:
        raise HTTPException(422, f"cutoff must be one of {detail['available_cutoffs']}")
    return detail


@router.get("/alerts/{event_id}/maneuver", response_model=schemas.ManeuverResult)
def alert_maneuver(event_id: str) -> dict:
    result = mock("maneuvers.json").get(event_id)
    if result is None:
        raise HTTPException(404, f"no maneuver for event {event_id}")
    return result


@router.get("/live/catalog", response_model=schemas.LiveCatalog)
def live_catalog(limit: int = Query(3000, ge=1, le=50000)) -> dict:
    cat = mock("live_catalog.json")
    return {"epoch": cat["epoch"], "objects": cat["objects"][:limit]}


@router.get("/live/conjunctions", response_model=schemas.LiveConjunctions)
def live_conjunctions(norad: int = 25544, hours: float = 72) -> dict:
    return mock("live_conjunctions.json")


@router.get("/live/orbit/{norad}", response_model=schemas.OrbitPath)
def live_orbit(norad: int, minutes: float = 90, step_s: float = 30) -> dict:
    return mock("live_orbit.json")


@router.get("/metrics", response_model=schemas.Metrics)
def metrics() -> dict:
    return mock("metrics.json")


@router.get("/space-weather", response_model=schemas.SpaceWeather)
def space_weather() -> dict:
    return mock("space_weather.json")


app.include_router(router)
