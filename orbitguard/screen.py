"""Module 6 — live conjunction screener over the cached CelesTrak catalog (SPEC Section 11).

Pipeline: OMM → Satrec → drop stale elements → perigee/apogee band prefilter → vectorised SGP4 over
the time grid in chunks → coarse minima < 50 km → bounded 1-D refinement of each TCA → report pairs
under the threshold with RTN geometry and an *estimated* Pc (catalog data has no covariance).

Run: python -m orbitguard.screen [--norad 25544] [--hours 72]
"""
from __future__ import annotations

import argparse
import csv
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.optimize import minimize_scalar
from sgp4 import omm
from sgp4.api import SatrecArray, Satrec, jday

from orbitguard import config, download, pc

log = logging.getLogger("orbitguard.screen")

R_EARTH_KM = 6378.137
MU_KM = 398600.4418
MAX_EPOCH_AGE_DAYS = 30
BAND_MARGIN_KM = 25
COARSE_KM = 50                    # SPEC's coarse gate; widened below so fast crossings aren't skipped
MAX_REL_SPEED_KMS = 15.5          # head-on LEO closing speed upper bound


def coarse_gate_km(step_s: float) -> float:
    """At 15 km/s a 60 s grid samples a crossing every ~900 km, so the sampled minimum can sit ~450 km from
    the true one. The gate must cover half a step of relative motion or real conjunctions are never refined."""
    return max(COARSE_KM, 0.5 * MAX_REL_SPEED_KMS * step_s)
CHUNK = 256
LIVE_HARD_BODY_M = 20.0           # assumed combined hard-body radius for live Pc (stated in the UI)
DEBRIS_GROUPS = {"cosmos-1408-debris", "fengyun-1c-debris", "iridium-33-debris", "cosmos-2251-debris"}


@dataclass
class CatalogEntry:
    norad: int
    name: str
    type: str
    sat: Satrec
    perigee_km: float
    apogee_km: float
    epoch_jd: float


def _object_type(name: str, group: str) -> str:
    n = name.upper()
    if group in DEBRIS_GROUPS or " DEB" in n:
        return "DEBRIS"
    if " R/B" in n:
        return "ROCKET BODY"
    return "PAYLOAD"


def load_catalog(now: datetime | None = None) -> tuple[list[CatalogEntry], dict]:
    """Parse every cached group CSV (live cache, else snapshot); dedupe by NORAD id; drop stale epochs."""
    now = now or datetime.now(timezone.utc)
    jd_now = sum(jday(now.year, now.month, now.day, now.hour, now.minute, now.second))
    seen: dict[int, CatalogEntry] = {}
    stats = {"rows": 0, "stale": 0, "bad": 0, "files": []}
    for path in download.catalog_csv_paths():
        group = path.stem
        stats["files"].append(group)
        with open(path, newline="") as fh:
            for fields in omm.parse_csv(fh):
                stats["rows"] += 1
                try:
                    norad = int(fields["NORAD_CAT_ID"])
                    if norad in seen and seen[norad].type != "PAYLOAD":
                        continue
                    sat = Satrec()
                    omm.initialize(sat, fields)
                except (KeyError, ValueError):
                    stats["bad"] += 1
                    continue
                epoch = sat.jdsatepoch + sat.jdsatepochF
                if jd_now - epoch > MAX_EPOCH_AGE_DAYS:
                    stats["stale"] += 1
                    continue
                n_rad_s = sat.no_kozai / 60.0
                a = (MU_KM / n_rad_s ** 2) ** (1 / 3)
                typ = _object_type(fields.get("OBJECT_NAME", ""), group)
                seen[norad] = CatalogEntry(norad, fields.get("OBJECT_NAME", str(norad)).strip(), typ, sat,
                                           a * (1 - sat.ecco) - R_EARTH_KM, a * (1 + sat.ecco) - R_EARTH_KM, epoch)
    stats["objects"] = len(seen)
    return list(seen.values()), stats


def time_grid(start: datetime, hours: float, step_s: float) -> tuple[np.ndarray, np.ndarray]:
    jd0, fr0 = jday(start.year, start.month, start.day, start.hour, start.minute, start.second + start.microsecond / 1e6)
    steps = np.arange(0, hours * 3600 + 1e-9, step_s) / 86400.0
    fr = fr0 + steps
    jd = np.full_like(fr, jd0)
    return jd, fr


def rtn_basis(r: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Rows R̂, T̂, N̂ of the primary's RTN frame: R̂ = r/|r|, N̂ = r×v/|r×v|, T̂ = N̂×R̂."""
    R = r / np.linalg.norm(r)
    N = np.cross(r, v)
    N /= np.linalg.norm(N)
    return np.vstack([R, np.cross(N, R), N])


def gmst_rad(jd_ut1: float) -> float:
    """Greenwich mean sidereal time (IAU-82, adequate for display)."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    g = 280.46061837 + 360.98564736629 * (jd_ut1 - 2451545.0) + 0.000387933 * t * t - t ** 3 / 38710000.0
    return np.radians(g % 360.0)


def teme_to_latlonalt(r_km: np.ndarray, jd_full: float | np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """TEME → Earth-fixed by GMST rotation; spherical-Earth lat/lon/alt (display only)."""
    r = np.atleast_2d(r_km)
    th = np.atleast_1d(gmst_rad(np.asarray(jd_full)) if np.ndim(jd_full) == 0 else np.array([gmst_rad(j) for j in np.atleast_1d(jd_full)]))
    x = r[:, 0] * np.cos(th) + r[:, 1] * np.sin(th)
    y = -r[:, 0] * np.sin(th) + r[:, 1] * np.cos(th)
    z = r[:, 2]
    rn = np.sqrt(x * x + y * y + z * z)
    return np.degrees(np.arcsin(z / rn)), np.degrees(np.arctan2(y, x)), rn - R_EARTH_KM


def assumed_sigmas_km(age_days: float) -> np.ndarray:
    """SPEC 11.7: σR = 0.1 + 0.05·d, σT = 0.3 + 0.3·d, σN = 0.1 + 0.05·d (km), d = element age at TCA."""
    d = max(0.0, age_days)
    return np.array([0.1 + 0.05 * d, 0.3 + 0.3 * d, 0.1 + 0.05 * d])


def estimated_pc(rel_r_rtn_km, rel_v_rtn_kms, age_p_days, age_s_days, radius_m=LIVE_HARD_BODY_M) -> tuple[float, dict]:
    """Pc from assumed age-grown sigmas (both approximated in the primary RTN frame), plus a P10/P90-style
    band from scaling the assumed sigmas by 0.5× and 2× (the assumption is the dominant uncertainty)."""
    r = np.asarray(rel_r_rtn_km) * 1e3
    v = np.asarray(rel_v_rtn_kms) * 1e3
    cp = np.diag((assumed_sigmas_km(age_p_days) * 1e3) ** 2)
    cs = np.diag((assumed_sigmas_km(age_s_days) * 1e3) ** 2)
    p, _ = pc.collision_probability(r, v, cp, cs, radius_m)
    band = {k: pc.collision_probability(r, v, cp * f * f, cs * f * f, radius_m)[0] for k, f in (("half", 0.5), ("double", 2.0))}
    return p, {"cov_t": cp, "cov_c": cs, "r_m": r, "v_ms": v, "band": band}


def _dist(sp: Satrec, ss: Satrec, jd: float, fr: float) -> float:
    e1, r1, _ = sp.sgp4(jd, fr)
    e2, r2, _ = ss.sgp4(jd, fr)
    if e1 or e2:
        return 1e9
    return float(np.linalg.norm(np.subtract(r2, r1)))


def screen(primary_norad: int = config.DEFAULT_PRIMARY_NORAD, hours: float = 72, step_s: float = 60,
           threshold_km: float = 10, start: datetime | None = None, catalog: list[CatalogEntry] | None = None) -> dict:
    """Screen one primary against the catalog. Returns a dict with conjunctions + timing stats."""
    t0 = time.perf_counter()
    start = (start or datetime.now(timezone.utc)).replace(microsecond=0)
    if catalog is None:
        catalog, cstats = load_catalog(start)
    else:
        cstats = {"objects": len(catalog)}
    by_id = {c.norad: c for c in catalog}
    if primary_norad not in by_id:
        raise KeyError(f"NORAD {primary_norad} not in the cached catalog")
    prim = by_id[primary_norad]

    # 1) altitude-band prefilter
    lo, hi = prim.perigee_km - BAND_MARGIN_KM, prim.apogee_km + BAND_MARGIN_KM
    cands = [c for c in catalog if c.norad != primary_norad and c.apogee_km >= lo and c.perigee_km <= hi]

    # 2) vectorised SGP4 over the grid, chunked
    jd, fr = time_grid(start, hours, step_s)
    ep, rp, _ = prim.sat.sgp4_array(jd, fr)
    hits: list[tuple[CatalogEntry, int]] = []
    n_attached = 0
    gate = coarse_gate_km(step_s)
    for i in range(0, len(cands), CHUNK):
        chunk = cands[i:i + CHUNK]
        e, r, _ = SatrecArray([c.sat for c in chunk]).sgp4(jd, fr)
        d = np.linalg.norm(r - rp[None, :, :], axis=2)
        d[(e != 0) | (ep[None, :] != 0)] = np.inf
        # Attached / co-located objects (ISS modules, docked vehicles share the station's elements):
        # median separation under 1 km over the whole window → not a conjunction, skip.
        attached = np.median(d, axis=1) < 1.0
        n_attached += int(attached.sum())
        d[attached] = np.inf
        # 3) coarse minima: strict local minima below the gate (a pair can meet several times in 72 h)
        close = d < gate
        if not close.any():
            continue
        left = np.concatenate([np.full((len(chunk), 1), np.inf), d[:, :-1]], axis=1)
        right = np.concatenate([d[:, 1:], np.full((len(chunk), 1), np.inf)], axis=1)
        for si, ti in zip(*np.nonzero(close & (d < left) & (d <= right))):
            hits.append((chunk[si], int(ti)))
    t_coarse = time.perf_counter() - t0

    # 4) refine each TCA at ~1 s resolution
    conj = []
    step_d = step_s / 86400.0
    for c, ti in hits:
        jd0 = jd[ti]
        res = minimize_scalar(lambda f: _dist(prim.sat, c.sat, jd0, f),
                              bounds=(fr[ti] - 2 * step_d, fr[ti] + 2 * step_d), method="bounded",
                              options={"xatol": 1.0 / 86400.0})
        miss = float(res.fun)
        if miss >= threshold_km:
            continue
        f_tca = float(res.x)
        _, r1, v1 = prim.sat.sgp4(jd0, f_tca)
        _, r2, v2 = c.sat.sgp4(jd0, f_tca)
        r1, v1, r2, v2 = map(np.asarray, (r1, v1, r2, v2))
        B = rtn_basis(r1, v1)
        rel_r, rel_v = B @ (r2 - r1), B @ (v2 - v1)
        if np.linalg.norm(rel_v) < 1e-6:
            continue
        jd_tca = jd0 + f_tca
        pc_est, extra = estimated_pc(rel_r, rel_v, jd_tca - prim.epoch_jd, jd_tca - c.epoch_jd)
        tca = datetime(2000, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=jd_tca - 2451545.0)
        lat_s, lon_s, alt_s = teme_to_latlonalt(r2, jd_tca)
        lat_p, lon_p, alt_p = teme_to_latlonalt(r1, jd_tca)
        conj.append({
            "secondary": {"norad": c.norad, "name": c.name, "type": c.type,
                          "lat": float(lat_s[0]), "lon": float(lon_s[0]), "alt_km": float(alt_s[0])},
            "primary_at_tca": {"norad": prim.norad, "name": prim.name, "type": prim.type,
                               "lat": float(lat_p[0]), "lon": float(lon_p[0]), "alt_km": float(alt_p[0])},
            "tca": tca.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "miss_km": round(miss, 4),
            "rel_speed_kms": round(float(np.linalg.norm(rel_v)), 4),
            "pc_est": float(pc_est),
            "pc_band": {k: float(v) for k, v in extra["band"].items()},
            "rtn_km": [round(float(x), 4) for x in rel_r],
            "rel_v_rtn_kms": [round(float(x), 5) for x in rel_v],
            "hours_to_tca": round((jd_tca - (jd[0] + fr[0])) * 24, 3),
            "element_age_days": {"primary": round(jd_tca - prim.epoch_jd, 2), "secondary": round(jd_tca - c.epoch_jd, 2)},
            "primary_sma_km": float((MU_KM / (prim.sat.no_kozai / 60.0) ** 2) ** (1 / 3)),
        })
    conj.sort(key=lambda x: (-x["pc_est"], x["miss_km"]))
    seconds = time.perf_counter() - t0
    lat, lon, alt = teme_to_latlonalt(rp[0], jd[0] + fr[0])
    return {
        "primary": {"norad": prim.norad, "name": prim.name, "type": prim.type,
                    "lat": float(lat[0]), "lon": float(lon[0]), "alt_km": float(alt[0])},
        "conjunctions": conj,
        "compute_seconds": round(seconds, 2),
        "start_utc": start.isoformat().replace("+00:00", "Z"),
        "stats": {"objects": cstats.get("objects", len(catalog)), "prefiltered_objects": len(cands),
                  "attached_skipped": n_attached, "coarse_gate_km": gate,
                  "coarse_candidates": len(hits), "hours": hours, "step_s": step_s,
                  "threshold_km": threshold_km, "coarse_seconds": round(t_coarse, 2), "seconds": round(seconds, 2)},
    }


def positions_now(catalog: list[CatalogEntry], when: datetime | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Lat/lon/alt for many objects at one instant (vectorised). Returns (lat, lon, alt, ok)."""
    when = when or datetime.now(timezone.utc)
    jd, fr = jday(when.year, when.month, when.day, when.hour, when.minute, when.second)
    e, r, _ = SatrecArray([c.sat for c in catalog]).sgp4(np.array([jd]), np.array([fr]))
    r = r[:, 0, :]
    ok = (e[:, 0] == 0) & np.isfinite(r).all(axis=1)
    lat, lon, alt = teme_to_latlonalt(np.where(ok[:, None], r, 7000.0), jd + fr)
    return lat, lon, alt, ok


def orbit_track(entry: CatalogEntry, minutes: float, step_s: float, start: datetime | None = None) -> list[dict]:
    start = start or datetime.now(timezone.utc)
    jd, fr = time_grid(start, minutes / 60.0, step_s)
    e, r, _ = entry.sat.sgp4_array(jd, fr)
    out = []
    for i in np.flatnonzero(e == 0):
        lat, lon, alt = teme_to_latlonalt(r[i], jd[i] + fr[i])
        t = start + timedelta(seconds=float(i) * step_s)
        out.append({"t": t.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "lat": round(float(lat[0]), 4), "lon": round(float(lon[0]), 4), "alt_km": round(float(alt[0]), 2)})
    return out


def find_by_name(catalog: list[CatalogEntry], *needles: str) -> list[dict]:
    """Preset lookup (e.g. Indian satellites) — ids come from the catalog itself, never hard-coded."""
    out = []
    for c in catalog:
        if c.type == "PAYLOAD" and any(n in c.name.upper() for n in needles):
            out.append({"norad": c.norad, "name": c.name})
    return sorted(out, key=lambda x: x["name"])


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--norad", type=int, default=config.DEFAULT_PRIMARY_NORAD)
    ap.add_argument("--hours", type=float, default=72)
    ap.add_argument("--step", type=float, default=60)
    ap.add_argument("--threshold-km", type=float, default=10)
    args = ap.parse_args(argv)
    res = screen(args.norad, args.hours, args.step, args.threshold_km)
    s = res["stats"]
    print(f"primary {res['primary']['name']}: {s['objects']} objects, {s['prefiltered_objects']} in band, "
          f"{s['coarse_candidates']} coarse candidates, {len(res['conjunctions'])} under {args.threshold_km} km, "
          f"{s['seconds']} s")
    for c in res["conjunctions"][:10]:
        print(f"  {c['tca']}  {c['secondary']['name']:<28} miss {c['miss_km']:7.3f} km  "
              f"v {c['rel_speed_kms']:6.2f} km/s  Pc~{c['pc_est']:.1e}")
    with open(config.ARTIFACTS_DIR / "screening_last_run.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tca", "norad", "name", "type", "miss_km", "rel_speed_kms", "pc_est"])
        for c in res["conjunctions"]:
            w.writerow([c["tca"], c["secondary"]["norad"], c["secondary"]["name"], c["secondary"]["type"],
                        c["miss_km"], c["rel_speed_kms"], c["pc_est"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
