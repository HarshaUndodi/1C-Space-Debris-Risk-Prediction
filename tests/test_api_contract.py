"""SPEC 14.7 — every endpoint returns JSON that validates against api/schemas.py (mock mode for now)."""
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from api import schemas
from api.main import app

client = TestClient(app)


def get_ok(path: str):
    r = client.get(path)
    assert r.status_code == 200, (path, r.status_code, r.text[:300])
    return r.json()


def test_health():
    schemas.Health.model_validate(get_ok("/api/health"))


def test_alert_list_ranked_and_valid():
    items = TypeAdapter(list[schemas.AlertItem]).validate_python(get_ok("/api/alerts?source=historical&limit=50"))
    assert items, "mock alert list must not be empty"
    keys = [(a.p_high, a.risk_p50) for a in items]
    assert keys == sorted(keys, reverse=True)
    for a in items:
        assert a.risk_p10 <= a.risk_p50 <= a.risk_p90


def test_alert_detail_and_maneuver_for_every_alert():
    for a in get_ok("/api/alerts"):
        d = schemas.AlertDetail.model_validate(get_ok(f"/api/alerts/{a['event_id']}?cutoff=2"))
        assert len(d.briefing) == 3
        assert d.briefing[0].startswith("[ALERT]") and d.briefing[1].startswith("[DIAGNOSTIC]") and d.briefing[2].startswith("[ACTION]")
        schemas.ManeuverResult.model_validate(get_ok(f"/api/alerts/{a['event_id']}/maneuver"))


def test_unknown_event_404():
    assert client.get("/api/alerts/does-not-exist").status_code == 404


def test_live_endpoints():
    schemas.LiveCatalog.model_validate(get_ok("/api/live/catalog?limit=3000"))
    schemas.LiveConjunctions.model_validate(get_ok("/api/live/conjunctions?norad=25544&hours=72"))
    schemas.OrbitPath.model_validate(get_ok("/api/live/orbit/25544?minutes=90&step_s=30"))


def test_metrics_and_space_weather():
    schemas.Metrics.model_validate(get_ok("/api/metrics"))
    schemas.SpaceWeather.model_validate(get_ok("/api/space-weather"))


def test_cors_for_vite_dev_server():
    r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
