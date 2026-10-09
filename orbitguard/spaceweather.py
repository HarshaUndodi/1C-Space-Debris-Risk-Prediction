"""Current space weather from CelesTrak SW-All.csv (cached by download.py) — SPEC 5.3."""
from __future__ import annotations

from datetime import date

import pandas as pd

from orbitguard import config, download

AP_ELEVATED = 30
F107_ELEVATED = 200


def latest(today: date | None = None) -> dict | None:
    """Most recent observed day: F10.7 (observed) and daily Ap. None if no file is available."""
    path = download.space_weather_path()
    if not path.exists():
        path = config.CATALOG_SNAPSHOT_DIR / "SW-All.csv"
    if not path.exists():
        return None
    sw = pd.read_csv(path, usecols=["DATE", "AP_AVG", "F10.7_OBS", "F10.7_DATA_TYPE"])
    sw = sw.dropna(subset=["AP_AVG", "F10.7_OBS"])
    sw = sw[sw["DATE"] <= (today or date.today()).isoformat()]
    obs = sw[sw["F10.7_DATA_TYPE"].astype(str).str.startswith("OBS")]
    row = (obs if len(obs) else sw).iloc[-1]
    f107, ap = float(row["F10.7_OBS"]), float(row["AP_AVG"])
    # Heuristic label only: high Ap / F10.7 inflate thermospheric density → larger drag uncertainty.
    flag = "elevated" if ap >= AP_ELEVATED or f107 >= F107_ELEVATED else "normal"
    return {"date": str(row["DATE"]), "f107": f107, "ap": ap, "heuristic_drag_flag": flag}
