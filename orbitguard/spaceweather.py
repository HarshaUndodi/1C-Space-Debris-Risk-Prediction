"""Current space weather from CelesTrak SW-All.csv (cached by download.py) — SPEC 5.3."""
from __future__ import annotations

from datetime import date

import pandas as pd

from orbitguard import config, download

AP_ELEVATED = 30
F107_ELEVATED = 200


def noaa_scale(ap: float) -> str:
    if ap >= 250:
        return "G5 (Extreme Storm)"
    if ap >= 150:
        return "G4 (Severe Storm)"
    if ap >= 100:
        return "G3 (Strong Storm)"
    if ap >= 50:
        return "G2 (Moderate Storm)"
    if ap >= 30:
        return "G1 (Minor Storm)"
    if ap >= 15:
        return "G0 (Unsettled)"
    return "G0 (Quiet)"


def latest(today: date | None = None) -> dict | None:
    """Most recent observed day with thermospheric drag and space weather metrics."""
    path = download.space_weather_path()
    if not path.exists():
        path = config.CATALOG_SNAPSHOT_DIR / "SW-All.csv"
    if not path.exists():
        return None
    sw = pd.read_csv(path, usecols=["DATE", "AP_AVG", "F10.7_OBS", "F10.7_DATA_TYPE"])
    sw = sw.dropna(subset=["AP_AVG", "F10.7_OBS"])
    sw = sw[sw["DATE"] <= (today or date.today()).isoformat()]
    obs = sw[sw["F10.7_DATA_TYPE"].astype(str).str.startswith("OBS")]
    target = obs if len(obs) else sw
    if len(target) == 0:
        return None

    row = target.iloc[-1]
    f107, ap = float(row["F10.7_OBS"]), float(row["AP_AVG"])
    flag = "elevated" if ap >= AP_ELEVATED or f107 >= F107_ELEVATED else "normal"
    scale = noaa_scale(ap)

    # Thermospheric density ratio relative to quiet solar minimum (F10.7=70, Ap=5)
    density_mult = round(1.0 + max(0.0, (f107 - 70.0) * 0.011) + max(0.0, (ap - 5.0) * 0.022), 2)
    drag_uncertainty = round(min(300.0, (density_mult - 1.0) * 48.0), 1)

    if ap >= 50 or f107 >= 220:
        impact = "Severe thermospheric swelling: Low LEO (<500 km) ephemerides degrade rapidly. Re-screen every 12 h."
    elif ap >= 30 or f107 >= 160:
        impact = "Moderate drag inflation: In-track position covariance enlarged for assets below 480 km."
    else:
        impact = "Nominal space weather: Thermospheric density stable. SGP4 propagation confidence high over 72 h."

    # 7-day trend
    hist_tail = target.tail(7)
    history_7d = [
        {"date": str(r["DATE"]), "f107": round(float(r["F10.7_OBS"]), 1), "ap": round(float(r["AP_AVG"]), 1)}
        for _, r in hist_tail.iterrows()
    ]

    return {
        "date": str(row["DATE"]),
        "f107": f107,
        "ap": ap,
        "heuristic_drag_flag": flag,
        "noaa_scale": scale,
        "density_multiplier": density_mult,
        "drag_uncertainty_pct": drag_uncertainty,
        "leo_impact": impact,
        "history_7d": history_7d,
    }
