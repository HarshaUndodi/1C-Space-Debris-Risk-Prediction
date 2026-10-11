"""SPEC 14.7 — every endpoint returns JSON that validates against api/schemas.py, in mock AND real mode."""
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from api import main, schemas
from orbitguard import config


@pytest.fixture(params=["mock", "real"])
def client(request, monkeypatch):
    if request.param == "real" and not config.DEMO_EVENTS_PATH.exists():
        pytest.skip("artifacts/demo_events.json not built (python -m orbitguard.build_demo)")
    monkeypatch.setattr(main, "store", main.Store(request.param))
    with TestClient(main.app) as c:   # runs lifespan (starts live screening thread in real mode)
        yield c


def get_ok(client, path: str):
    r = client.get(path)
    assert r.status_code == 200, (path, r.status_code, r.text[:300])
    return r.json()


def test_health(client):
    h = schemas.Health.model_validate(get_ok(client, "/api/health"))
    assert h.mode == main.store.mode


def test_alert_list_ranked_and_valid(client):
    items = TypeAdapter(list[schemas.AlertItem]).validate_python(get_ok(client, "/api/alerts?source=historical&limit=50"))
    assert items, "alert list must not be empty"
    keys = [(a.p_high, a.risk_p50) for a in items]
    assert keys == sorted(keys, reverse=True)
    for a in items:
        assert a.risk_p10 <= a.risk_p50 <= a.risk_p90


def test_alert_detail_every_alert_every_cutoff(client):
    for a in get_ok(client, "/api/alerts"):
        d = schemas.AlertDetail.model_validate(get_ok(client, f"/api/alerts/{a['event_id']}?cutoff=2"))
        assert [ln.split("]")[0] + "]" for ln in d.briefing] == ["[ALERT]", "[DIAGNOSTIC]", "[ACTION]"]
        assert len(d.shap_top) <= 5
        for c in d.available_cutoffs:
            schemas.AlertDetail.model_validate(get_ok(client, f"/api/alerts/{a['event_id']}?cutoff={c}"))


def test_maneuver_for_every_maneuver_or_watch_alert(client):
    for a in get_ok(client, "/api/alerts"):
        if a["decision"] in ("MANEUVER", "WATCH"):
            m = schemas.ManeuverResult.model_validate(get_ok(client, f"/api/alerts/{a['event_id']}/maneuver"))
            assert m.pareto and m.points
            front = [p.post_pc for p in m.pareto]
            assert all(b <= a_ * (1 + 1e-6) for a_, b in zip(front, front[1:]))


def test_unknown_event_404(client):
    assert client.get("/api/alerts/does-not-exist").status_code == 404


def test_live_endpoints(client):
    schemas.LiveCatalog.model_validate(get_ok(client, "/api/live/catalog?limit=3000"))
    r = None
    for _ in range(60):   # 503 = screening still running in the background thread
        r = client.get("/api/live/conjunctions?norad=25544&hours=72")
        if r.status_code != 503:
            break
        time.sleep(1)
    assert r.status_code == 200, r.text[:200]
    lc = schemas.LiveConjunctions.model_validate(r.json())
    schemas.OrbitPath.model_validate(get_ok(client, "/api/live/orbit/25544?minutes=90&step_s=30"))
    tr = schemas.LiveTracks.model_validate(get_ok(client, "/api/live/tracks?limit=200&minutes=10&step_s=30"))
    assert tr.objects and all(len(s) == 3 * tr.n_steps for s in tr.samples_km)
    if main.store.mode == "real":
        r0 = tr.samples_km[0][:3]
        assert 6400 < sum(v * v for v in r0) ** 0.5 < 50000, "ECEF radius should be in km above Earth"
    if main.store.mode == "real" and lc.conjunctions:
        eid = r.json()["conjunctions"][0]["event_id"]
        d = schemas.AlertDetail.model_validate(get_ok(client, f"/api/alerts/{eid}"))
        assert d.source == "live" and d.p_high is None and len(d.briefing) == 3
        schemas.ManeuverResult.model_validate(get_ok(client, f"/api/alerts/{eid}/maneuver"))


def test_metrics_and_space_weather(client):
    schemas.Metrics.model_validate(get_ok(client, "/api/metrics"))
    schemas.SpaceWeather.model_validate(get_ok(client, "/api/space-weather"))


def test_cors_for_vite_dev_server(client):
    r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_live_cdm_prediction(client):
    # Test sample CDMs endpoint
    samples = get_ok(client, "/api/live/cdm/samples")
    assert len(samples) >= 3 and "data" in samples[0]

    # Test prediction on a sample live CDM
    sample = samples[0]["data"]
    res = client.post("/api/live/cdm/predict", json=sample)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["source"] == "live"
    assert data["decision"] in ("MANEUVER", "WATCH", "HOLD")
    assert data["p_high"] is not None
    assert len(data["shap_top"]) >= 3
    assert len(data["briefing"]) == 3
    assert "recommended" in data["maneuver"]
