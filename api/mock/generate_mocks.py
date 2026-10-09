"""Generate deterministic mock JSON for every Section 13 endpoint (Milestone 0).

The numbers are synthetic placeholders so the frontend can be built before the models exist.
They are NOT results. Run: python -m api.mock.generate_mocks
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

MOCK_DIR = Path(__file__).resolve().parent
EPOCH = datetime(2026, 10, 9, 6, 0, 0, tzinfo=timezone.utc)
rng = np.random.default_rng(42)

CHASER_TYPES = ["DEBRIS", "PAYLOAD", "ROCKET BODY", "UNKNOWN"]
SHAP_POOL = [
    ("last_risk", "Latest CDM risk"),
    ("last_c_sigma_r", "Debris radial uncertainty"),
    ("delta_miss_distance", "Change in miss distance since previous CDM"),
    ("slope_risk", "Risk trend over time"),
    ("mahalanobis_proxy", "Miss distance in units of uncertainty"),
    ("last_c_sigma_t", "Debris along-track uncertainty"),
    ("last_miss_distance", "Latest miss distance"),
    ("risk_max", "Highest risk seen so far"),
    ("last_AP", "Geomagnetic activity (Ap)"),
]
DIRECTIONS = ["+along", "-along", "+radial", "-radial"]
LEADS_H = [6, 12, 24, 36, 48, 72]


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def r(x: float, n: int = 3) -> float:
    return float(round(x, n))


def decide(p_high: float, p90: float, tau: float = 0.35) -> str:
    if p_high >= tau and p90 >= -4:
        return "MANEUVER"
    if p_high >= tau:
        return "WATCH"
    return "HOLD"


def make_alerts(n: int = 14) -> tuple[list[dict], dict, dict]:
    alerts, details, maneuvers = [], {}, {}
    # A spread of final risks: a few severe, some borderline, many benign.
    p50s = [-3.4, -3.9, -4.3, -4.8, -5.3, -5.7, -6.2, -6.9, -7.6, -8.4, -9.5, -11.0, -14.5, -20.0][:n]
    for i, p50 in enumerate(p50s):
        eid = str(1000 + 37 * i)
        width = 0.6 + 0.15 * i
        p10, p90 = p50 - width, p50 + width * 0.8
        p_high = float(1 / (1 + math.exp(-(p50 + 6.0) * 1.8)))
        decision = decide(p_high, p90)
        miss = float(10 ** (2.0 + 0.12 * i + rng.normal(0, 0.05)))
        ttca = r(2.0 + rng.uniform(0, 0.4), 2)
        baseline = p50 + rng.normal(0, 0.5)
        item = {
            "event_id": eid,
            "source": "historical",
            "decision": decision,
            "time_to_tca_days": ttca,
            "p_high": r(p_high),
            "risk_p10": r(p10), "risk_p50": r(p50), "risk_p90": r(p90),
            "baseline_risk": r(baseline),
            "miss_distance_m": r(miss, 1),
            "chaser_type": CHASER_TYPES[i % len(CHASER_TYPES)],
        }
        alerts.append(item)

        # CDM history: ~1 CDM per 8 h from 7 days out, noisy drift towards the final risk.
        times = np.arange(7.0, 0.3, -0.35) + rng.uniform(-0.05, 0.05, size=len(np.arange(7.0, 0.3, -0.35)))
        start = p50 - 2.0
        hist = []
        for t in times:
            frac = 1 - (t - 0.3) / 6.7
            risk = start + (p50 - start) * frac + rng.normal(0, 0.35)
            md = miss * (1 + 2.5 * (1 - frac)) * (1 + rng.normal(0, 0.05))
            hist.append({"time_to_tca": r(t, 3), "risk": r(risk), "miss_distance_m": r(md, 1)})
        picks = rng.choice(len(SHAP_POOL), size=5, replace=False)
        shap_top = []
        for k, j in enumerate(picks):
            feat, label = SHAP_POOL[j]
            mag = (1.2 - 0.2 * k) * (1 if p50 > -6 else -1) * (1 if k % 3 else -0.6)
            shap_top.append({"feature": feat, "label": label, "value": r(float(rng.uniform(-5, 500)), 2), "shap": r(mag)})
        one_in = int(round(10 ** (-p50)))
        action = {
            "MANEUVER": "Plan avoidance: +0.12 m/s along-track, 24 h before TCA.",
            "WATCH": "Monitor; re-assess at next CDM, maneuver option on standby.",
            "HOLD": "No action, re-assess at next CDM.",
        }[decision]
        details[eid] = {
            **item,
            "cdm_history": hist,
            "available_cutoffs": [7, 5, 4, 3, 2],
            "shap_top": shap_top,
            "briefing": [
                f"[ALERT] Final risk about 1 in {one_in:,} with {item['chaser_type'].lower()}, TCA in {ttca} days.",
                f"[DIAGNOSTIC] Driven mainly by {shap_top[0]['label'].lower()} and {shap_top[1]['label'].lower()}.",
                f"[ACTION] {decision}: {action}",
            ],
            "briefing_source": "template",
            "true_final_risk": r(p50 + rng.normal(0, 0.4)),
        }
        maneuvers[eid] = make_maneuver(eid, 10 ** p50)
    return alerts, details, maneuvers


def make_maneuver(eid: str, pre_pc: float, target_pc: float = 1e-6) -> dict:
    """Synthetic but physically-shaped: along-track burns earlier are most effective."""
    dvs = np.logspace(-3, math.log10(2), 40)
    eff = {"+along": 1.0, "-along": 0.95, "+radial": 0.25, "-radial": 0.22}
    points = []
    for dv in dvs:
        for d in DIRECTIONS:
            for lead in LEADS_H:
                shift = dv * eff[d] * lead * 9.0  # pseudo km of separation
                post = max(pre_pc * math.exp(-(shift ** 2) / 0.8), 1e-30)
                points.append({"dv_ms": r(dv, 5), "direction": d, "burn_lead_h": lead, "post_pc": float(f"{post:.3e}")})
    pareto = []
    for dv in dvs:
        best = min(p["post_pc"] for p in points if p["dv_ms"] == r(dv, 5))
        pareto.append({"dv_ms": r(dv, 5), "post_pc": best})
    ok = [p for p in points if p["post_pc"] <= target_pc]
    if ok:
        rec = min(ok, key=lambda p: (p["dv_ms"], -p["burn_lead_h"]))
        met = True
    else:
        rec = min(points, key=lambda p: p["post_pc"])
        met = False
    m_prop_g = 500.0 * (1 - math.exp(-rec["dv_ms"] / (220 * 9.80665))) * 1000
    return {
        "event_id": eid,
        "target_pc": target_pc,
        "target_met": met,
        "pre_burn_pc": float(f"{pre_pc:.3e}"),
        "recommended": {**rec, "propellant_g": r(m_prop_g, 2)},
        "points": points,
        "pareto": pareto,
        "secondary_check": {"applicable": False, "new_conjunctions": [],
                            "note": "not applicable — no catalog context (historical ESA CDM)"},
    }


def ground_track(inc_deg: float, period_min: float, raan0: float, u0: float, t_s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Circular-orbit ground track (display-only mock)."""
    inc = math.radians(inc_deg)
    n = 2 * math.pi / (period_min * 60)
    u = u0 + n * t_s
    lat = np.degrees(np.arcsin(np.sin(inc) * np.sin(u)))
    lon = np.degrees(np.arctan2(np.cos(inc) * np.sin(u), np.cos(u)) + raan0 - 7.2921159e-5 * t_s)
    lon = (lon + 180) % 360 - 180
    return lat, lon


def make_live() -> tuple[dict, dict, dict]:
    objects = [{"norad": 25544, "name": "ISS (ZARYA)", "type": "PAYLOAD", "lat": 0.0, "lon": 0.0, "alt_km": 420.0}]
    lat, lon = ground_track(51.64, 92.9, 0.3, 0.0, np.array([0.0]))
    objects[0]["lat"], objects[0]["lon"] = r(lat[0]), r(lon[0])
    for k in range(600):
        is_debris = k % 3 != 0
        alt = float(rng.choice([rng.uniform(350, 600), rng.uniform(600, 1200)], p=[0.4, 0.6]))
        inc = float(rng.uniform(0, 100))
        la, lo = ground_track(inc, 90 + (alt - 300) / 20, rng.uniform(0, 6.28), rng.uniform(0, 6.28), np.array([0.0]))
        objects.append({
            "norad": 40000 + k,
            "name": f"MOCK {'DEB' if is_debris else 'SAT'} {k}",
            "type": "DEBRIS" if is_debris else "PAYLOAD",
            "lat": r(la[0]), "lon": r(lo[0]), "alt_km": r(alt, 1),
        })
    catalog = {"epoch": iso(EPOCH), "objects": objects}

    t = np.arange(0, 90 * 60 + 1, 30.0)
    la, lo = ground_track(51.64, 92.9, 0.3, 0.0, t)
    orbit = {"points": [{"t": iso(EPOCH + timedelta(seconds=float(s))), "lat": r(a), "lon": r(b), "alt_km": 420.0}
                        for s, a, b in zip(t, la, lo)]}

    conj = []
    for k, (miss, hours) in enumerate([(1.8, 9.5), (3.2, 22.0), (6.7, 41.3), (8.9, 63.0)]):
        sec = objects[1 + 2 * k + 1]
        rtn = rng.normal(0, 1, 3)
        rtn = rtn / np.linalg.norm(rtn) * miss
        conj.append({
            "secondary": {**sec, "alt_km": r(420 + rng.normal(0, 3), 1)},
            "tca": iso(EPOCH + timedelta(hours=hours)),
            "miss_km": miss,
            "rel_speed_kms": r(rng.uniform(7, 14.5), 2),
            "pc_est": float(f"{1e-4 * math.exp(-miss):.3e}"),
            "rtn_km": [r(x) for x in rtn],
        })
    conjunctions = {"primary": objects[0], "conjunctions": conj, "compute_seconds": 0.0}
    return catalog, conjunctions, orbit


def make_metrics() -> dict:
    # Placeholder zeros, exactly as SPEC Section 8 — never presented as results.
    return {
        "cutoff_days": 2,
        "n_test_events": 0,
        "n_test_high_risk": 0,
        "baseline": {"kelvins_score": 0.0, "mse_hr": 0.0, "f2": 0.0, "recall": 0.0, "false_alarm_rate": 0.0, "brier": 0.0},
        "model": {"kelvins_score": 0.0, "mse_hr": 0.0, "f2": 0.0, "recall": 0.0, "false_alarm_rate": 0.0, "brier": 0.0,
                  "brier_uncalibrated": 0.0, "band_coverage_p10_p90": 0.0, "threshold": 0.0},
        "lead_time": [{"cutoff_days": d, "model_recall": 0.0, "baseline_recall": 0.0, "model_f2": 0.0, "baseline_f2": 0.0}
                      for d in [2, 3, 4, 5, 7]],
        "screening": {"objects": 0, "hours": 72, "step_s": 60, "seconds": 0.0},
        "is_mock": True,
    }


def main() -> None:
    alerts, details, maneuvers = make_alerts()
    catalog, conjunctions, orbit = make_live()
    files = {
        "health.json": {"status": "ok", "model_loaded": False, "catalog_age_hours": None, "mode": "mock"},
        "alerts.json": alerts,
        "alert_details.json": details,
        "maneuvers.json": maneuvers,
        "live_catalog.json": catalog,
        "live_conjunctions.json": conjunctions,
        "live_orbit.json": orbit,
        "metrics.json": make_metrics(),
        "space_weather.json": {"date": "2026-10-08", "f107": 150.2, "ap": 12, "heuristic_drag_flag": "normal"},
    }
    for name, payload in files.items():
        (MOCK_DIR / name).write_text(json.dumps(payload, indent=1))
        print(f"wrote api/mock/{name}")


if __name__ == "__main__":
    main()
