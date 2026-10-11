"""Live-mode service used by the API: background screening, caching, positions, live alerts/maneuvers.

* Screens the default primary (ISS) at startup in a background thread; results are cached for 2 h and
  persisted to artifacts/live_screen.json so a restart (or an offline demo) is instant.
* Other primaries are screened on demand in the background (the API answers 503 until ready).
* Works entirely from the cached CelesTrak files / committed snapshot — no network needed.
* Secondary-conjunction check (SPEC 10.3.6) for live maneuvers: the burn's effect is propagated with
  two-body + J2 (solve_ivp, rtol 1e-9) as a *difference* (burned − unburned) added to the SGP4 track, so
  model error cancels; the shifted track is screened against in-band objects for misses < 5 km.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import minimize_scalar
from sgp4.api import SatrecArray, jday

from orbitguard import config, download, maneuver, screen

log = logging.getLogger("orbitguard.live")

CACHE_HOURS = 2.0
LIVE_SCREEN_PATH = config.ARTIFACTS_DIR / "live_screen.json"
NEW_CONJ_KM = 5.0
J2 = 1.08262668e-3
INDIAN_NEEDLES = ("CARTOSAT", "RISAT", "OCEANSAT", "RESOURCESAT", "EOS-0", "ASTROSAT", "INSAT", "GSAT")


def object_tag(name: str) -> str:
    n = name.upper()
    if "COSMOS 1408" in n or "1408 DEB" in n:
        return "cosmos-1408"
    if "FENGYUN 1C" in n or "FY-1C" in n:
        return "fengyun-1c"
    if "COSMOS 2251" in n or "IRIDIUM 33" in n:
        return "collision-debris"
    if any(needle in n for needle in INDIAN_NEEDLES):
        return "isro"
    return "general"


def live_event_id(primary: int, c: dict) -> str:
    return f"live-{primary}-{c['secondary']['norad']}-{c['tca'].replace('-', '').replace(':', '').rstrip('Z')}"


def screening_decision(pc_est: float) -> str:
    """Live screening rule (assumed covariance): MANEUVER ≥ 1e-4, WATCH ≥ 1e-6, else HOLD."""
    return "MANEUVER" if pc_est >= 1e-4 else "WATCH" if pc_est >= 1e-6 else "HOLD"


# --- two-body + J2 ------------------------------------------------------------

def _accel_j2(_t, y):
    r = y[:3]
    rn = np.linalg.norm(r)
    z2 = (r[2] / rn) ** 2
    k = 1.5 * J2 * screen.MU_KM * screen.R_EARTH_KM ** 2 / rn ** 5
    a = -screen.MU_KM * r / rn ** 3 + k * np.array([r[0] * (5 * z2 - 1), r[1] * (5 * z2 - 1), r[2] * (5 * z2 - 3)])
    return np.concatenate([y[3:], a])


def burn_delta(r0, v0, dv_kms, t_end_s):
    """Dense function t ↦ (burned − unburned) position (km), both propagated with two-body + J2."""
    y0 = np.concatenate([r0, v0])
    y1 = np.concatenate([r0, v0 + dv_kms])
    kw = dict(rtol=1e-9, atol=1e-9, dense_output=True, method="DOP853")
    a = solve_ivp(_accel_j2, (0, t_end_s), y0, **kw)
    b = solve_ivp(_accel_j2, (0, t_end_s), y1, **kw)
    return lambda t: b.sol(t)[:3] - a.sol(t)[:3]


def secondary_check(catalog, prim, burn_time: datetime, dv_rtn_ms: np.ndarray, tca: datetime, ignore: set[int]) -> dict:
    """Screen the post-burn primary from burn to TCA+24 h for NEW misses < 5 km."""
    end = tca + timedelta(hours=24)
    span_s = (end - burn_time).total_seconds()
    jd_b, fr_b = jday(burn_time.year, burn_time.month, burn_time.day, burn_time.hour, burn_time.minute, burn_time.second)
    e, r0, v0 = prim.sat.sgp4(jd_b, fr_b)
    if e:
        return {"applicable": False, "new_conjunctions": [], "note": "primary propagation error at burn time"}
    r0, v0 = np.asarray(r0), np.asarray(v0)
    B = screen.rtn_basis(r0, v0)
    delta = burn_delta(r0, v0, B.T @ (np.asarray(dv_rtn_ms) / 1e3), span_s)

    step = 30.0
    jd, fr = screen.time_grid(burn_time, span_s / 3600.0, step)
    t_s = (fr - fr[0]) * 86400.0
    ep, rp, _ = prim.sat.sgp4_array(jd, fr)
    rp_new = rp + delta(t_s).T
    band = [c for c in catalog if c.norad != prim.norad and c.norad not in ignore
            and c.apogee_km >= prim.perigee_km - 50 and c.perigee_km <= prim.apogee_km + 50]
    gate = screen.coarse_gate_km(step)
    found = []
    for i in range(0, len(band), screen.CHUNK):
        chunk = band[i:i + screen.CHUNK]
        es, rs, _ = SatrecArray([c.sat for c in chunk]).sgp4(jd, fr)
        d_new = np.linalg.norm(rs - rp_new[None], axis=2)
        d_old = np.linalg.norm(rs - rp[None], axis=2)
        bad = (es != 0) | (ep[None] != 0)
        d_new[bad] = np.inf
        d_old[bad] = np.inf
        for si in np.flatnonzero(d_new.min(axis=1) < gate):
            ti = int(np.argmin(d_new[si]))
            c = chunk[si]

            def dist(tsec, sat=c.sat):
                j, f = jd[0], fr[0] + tsec / 86400.0
                _, a, _ = prim.sat.sgp4(j, f)
                _, b, _ = sat.sgp4(j, f)
                return float(np.linalg.norm(np.asarray(b) - (np.asarray(a) + delta(tsec))))

            res = minimize_scalar(dist, bounds=(max(0, t_s[ti] - 2 * step), min(span_s, t_s[ti] + 2 * step)),
                                  method="bounded", options={"xatol": 1.0})
            if res.fun < NEW_CONJ_KM and d_old[si].min() >= NEW_CONJ_KM:
                when = burn_time + timedelta(seconds=float(res.x))
                found.append({"norad": c.norad, "name": c.name, "miss_km": round(float(res.fun), 3),
                              "tca": when.isoformat(timespec="seconds").replace("+00:00", "Z")})
    return {"applicable": True, "new_conjunctions": found,
            "note": f"post-burn track screened against {len(band)} in-band objects to TCA+24 h (two-body+J2 delta on SGP4)"}


# --- service --------------------------------------------------------------------

class LiveService:
    def __init__(self):
        self._lock = threading.Lock()
        self._catalog = None
        self._catalog_at: float | None = None
        self._results: dict[int, dict] = {}      # norad -> screening result (+ "computed_at_unix")
        self._running: set[int] = set()
        self._maneuvers: dict[str, dict] = {}
        self._predictions: dict[str, dict] = {}
        self._positions: tuple[float, dict] | None = None
        self._started = False
        self.catalog_load_seconds: float | None = None

    # catalog ------------------------------------------------------------------
    def catalog_entries(self):
        with self._lock:
            if self._catalog is None or (time.time() - (self._catalog_at or 0)) > CACHE_HOURS * 3600:
                t0 = time.perf_counter()
                self._catalog, _ = screen.load_catalog()
                self.catalog_load_seconds = round(time.perf_counter() - t0, 2)
                self._catalog_at = time.time()
            return self._catalog

    # background screening -----------------------------------------------------
    def start_background(self):
        if self._started:
            return
        self._started = True
        self._load_persisted()
        threading.Thread(target=self._loop, name="orbitguard-live", daemon=True).start()

    def _loop(self):
        while True:
            try:
                res = self._results.get(config.DEFAULT_PRIMARY_NORAD)
                if res is None or time.time() - res["computed_at_unix"] > CACHE_HOURS * 3600:
                    self._run(config.DEFAULT_PRIMARY_NORAD)
            except Exception:   # never let the thread die silently; the API keeps serving the last result
                log.exception("live screening failed")
            time.sleep(300)

    def _load_persisted(self):
        try:
            data = json.loads(LIVE_SCREEN_PATH.read_text())
        except (FileNotFoundError, ValueError):
            return
        if time.time() - data.get("computed_at_unix", 0) < CACHE_HOURS * 3600:
            self._results[int(data["primary"]["norad"])] = data
            log.info("loaded persisted live screening (%s)", data.get("start_utc"))

    def _run(self, norad: int, hours: float = 72):
        if norad in self._running:
            return
        self._running.add(norad)
        try:
            res = screen.screen(norad, hours=hours, catalog=self.catalog_entries())
            res["computed_at_unix"] = time.time()
            for c in res["conjunctions"]:
                c["event_id"] = live_event_id(norad, c)
            self._results[norad] = res
            if norad == config.DEFAULT_PRIMARY_NORAD:
                config.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
                LIVE_SCREEN_PATH.write_text(json.dumps(res))
                from orbitguard import evaluate
                s = res["stats"]
                evaluate.save_metrics({"screening": {
                    "objects": s["objects"], "hours": s["hours"], "step_s": s["step_s"], "seconds": s["seconds"],
                    "primary": res["primary"]["name"], "prefiltered_objects": s["prefiltered_objects"],
                    "conjunctions": len(res["conjunctions"]), "threshold_km": s["threshold_km"],
                    "catalog_load_seconds": self.catalog_load_seconds,
                    "note": "seconds = SGP4 propagation + screening + TCA refinement; catalog parsing is catalog_load_seconds",
                    "run_utc": res["start_utc"]}})
        finally:
            self._running.discard(norad)

    # API views -------------------------------------------------------------------
    def conjunctions(self, norad: int, hours: float = 72) -> dict | None:
        res = self._results.get(norad)
        if res is None:
            if norad not in self._running:
                threading.Thread(target=self._safe_run, args=(norad, hours), daemon=True).start()
            return None
        return {"primary": res["primary"], "conjunctions": res["conjunctions"], "compute_seconds": res["compute_seconds"],
                "start_utc": res.get("start_utc"), "stats": res.get("stats")}

    def _safe_run(self, norad, hours):
        try:
            self._run(norad, hours)
        except KeyError:
            self._results[norad] = {"primary": {"norad": norad, "name": f"NORAD {norad}", "type": "UNKNOWN",
                                                "lat": 0, "lon": 0, "alt_km": 0},
                                    "conjunctions": [], "compute_seconds": 0.0, "computed_at_unix": time.time(),
                                    "error": "not in cached catalog"}
        except Exception:
            log.exception("on-demand screening failed for %s", norad)

    def catalog(self, limit: int) -> dict | None:
        """Positions 'now' (cached 30 s): primary, conjunction partners and in-band objects first."""
        if self._positions and time.time() - self._positions[0] < 30 and len(self._positions[1]["objects"]) >= limit:
            cached = self._positions[1]
            return {"epoch": cached["epoch"], "objects": cached["objects"][:limit]}
        cat = self.catalog_entries()
        if not cat:
            return None
        res = self._results.get(config.DEFAULT_PRIMARY_NORAD)
        prim_id = config.DEFAULT_PRIMARY_NORAD
        partners = {c["secondary"]["norad"] for c in (res or {}).get("conjunctions", [])}
        by_id = {c.norad: c for c in cat}
        prim = by_id.get(prim_id)
        rng = np.random.default_rng(0)
        first = [c for c in cat if c.norad == prim_id or c.norad in partners]
        band = [c for c in cat if prim and c not in first and c.apogee_km >= prim.perigee_km - 25 and c.perigee_km <= prim.apogee_km + 25]
        bset = {c.norad for c in first} | {c.norad for c in band}
        isro_items = [c for c in cat if c.norad not in bset and any(needle in c.name.upper() for needle in INDIAN_NEEDLES)]
        c1408_items = [c for c in cat if c.norad not in bset and ("COSMOS 1408" in c.name.upper() or "1408 DEB" in c.name.upper())]
        priority = isro_items[:30] + c1408_items
        pset = bset | {c.norad for c in priority}
        rest = [c for c in cat if c.norad not in pset]
        order = first + band + priority + [rest[i] for i in rng.permutation(len(rest))]
        chosen = order[:limit]
        now = datetime.now(timezone.utc)
        lat, lon, alt, ok = screen.positions_now(chosen, now)
        objs = [{"norad": c.norad, "name": c.name, "type": c.type, "tag": object_tag(c.name), "lat": round(float(la), 3), "lon": round(float(lo), 3),
                 "alt_km": round(float(al), 1)} for c, la, lo, al, k in zip(chosen, lat, lon, alt, ok) if k]
        out = {"epoch": now.isoformat(timespec="seconds").replace("+00:00", "Z"), "objects": objs}
        self._positions = (time.time(), out)
        return out

    def _display_order(self, limit: int):
        """Primary, conjunction partners, in-band objects, ISRO assets, Cosmos-1408 & ASAT debris, then random sample."""
        cat = self.catalog_entries()
        res = self._results.get(config.DEFAULT_PRIMARY_NORAD)
        partners = {c["secondary"]["norad"] for c in (res or {}).get("conjunctions", [])}
        prim = next((c for c in cat if c.norad == config.DEFAULT_PRIMARY_NORAD), None)
        first = [c for c in cat if c.norad == config.DEFAULT_PRIMARY_NORAD or c.norad in partners]
        fset = {c.norad for c in first}
        band = [c for c in cat if prim and c.norad not in fset
                and c.apogee_km >= prim.perigee_km - 25 and c.perigee_km <= prim.apogee_km + 25]
        bset = fset | {c.norad for c in band}

        isro_items = [c for c in cat if c.norad not in bset and any(needle in c.name.upper() for needle in INDIAN_NEEDLES)]
        c1408_items = [c for c in cat if c.norad not in bset and ("COSMOS 1408" in c.name.upper() or "1408 DEB" in c.name.upper())]
        asat_items = [c for c in cat if c.norad not in bset and "FENGYUN 1C" in c.name.upper()]
        priority = isro_items[:35] + c1408_items + asat_items[:120]
        pset = bset | {c.norad for c in priority}

        rest = [c for c in cat if c.norad not in pset]
        rng = np.random.default_rng(0)
        return (first + band + priority + [rest[i] for i in rng.permutation(len(rest))])[:limit]

    def tracks(self, limit: int, minutes: float, step_s: float, start: datetime | None = None) -> dict | None:
        """~30 min of Earth-fixed samples per object so the globe can animate in real time (cached per window)."""
        start = (start or datetime.now(timezone.utc)).replace(microsecond=0)
        start = start - timedelta(seconds=start.second % int(step_s))     # align → cache hits across viewers
        key = (start.isoformat(), limit, minutes, step_s)
        hit = getattr(self, "_tracks_cache", {}).get(key)
        if hit:
            return hit
        chosen = self._display_order(limit)
        if not chosen:
            return None
        xyz, t = screen.tracks_ecef(chosen, start, minutes, step_s)
        keep = ~np.isnan(xyz).any(axis=(1, 2))
        objs, samples = [], []
        for c, ok, arr in zip(chosen, keep, xyz):
            if ok:
                objs.append({"norad": c.norad, "name": c.name, "type": c.type, "tag": object_tag(c.name)})
                samples.append(np.rint(arr.reshape(-1)).astype(int).tolist())   # whole km: invisible at globe scale, ~2× smaller
        out = {"start": start.isoformat().replace("+00:00", "Z"), "step_s": step_s, "n_steps": int(len(t)),
               "objects": objs, "samples_km": samples}
        self._tracks_cache = {key: out}   # keep only the latest window
        return out

    def orbit(self, norad: int, minutes: float, step_s: float, start: datetime | None = None) -> dict | None:
        entry = next((c for c in self.catalog_entries() if c.norad == norad), None)
        return None if entry is None else {"points": screen.orbit_track(entry, minutes, step_s, start)}

    def presets(self) -> list[dict]:
        cat = self.catalog_entries()
        iss = [{"norad": c.norad, "name": c.name, "fleet": "station", "agency": "International Space Station"}
               for c in cat if c.norad == config.DEFAULT_PRIMARY_NORAD]
        isro_raw = screen.find_by_name(cat, *INDIAN_NEEDLES)
        isro = [{"norad": c["norad"], "name": c["name"], "fleet": "isro", "agency": "ISRO (India)"}
                for c in isro_raw[:25]]
        return iss + isro

    def _find(self, event_id: str) -> tuple[dict, dict] | None:
        for res in self._results.values():
            for c in res["conjunctions"]:
                if c.get("event_id") == event_id:
                    return res, c
        return None

    def alerts(self) -> list[dict]:
        out = []
        for res in self._results.values():
            for c in res["conjunctions"]:
                out.append(self._item(res, c))
        return out

    def _prediction(self, res: dict, c: dict) -> dict:
        eid = c.get("event_id") or live_event_id(res["primary"]["norad"], c)
        if eid in self._predictions:
            return self._predictions[eid]
        from orbitguard import predict
        hours = max(0.1, (datetime.fromisoformat(c["tca"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() / 3600)
        age_p = c["element_age_days"]["primary"]
        age_s = c["element_age_days"]["secondary"]
        cdm_input = {
            "event_id": eid,
            "time_to_tca_days": round(hours / 24.0, 3),
            "miss_distance_m": c["miss_km"] * 1000.0,
            "rel_speed_kms": c["rel_speed_kms"],
            "risk": c["pc_est"],
            "chaser_type": c["secondary"]["type"],
            "rtn_km": c.get("rtn_km", [0.0, c["miss_km"], 0.0]),
            "rel_v_rtn_kms": c.get("rel_v_rtn_kms", [0.0, c["rel_speed_kms"], 0.0]),
            "target_sigmas_m": (screen.assumed_sigmas_km(age_p) * 1000.0).tolist(),
            "chaser_sigmas_m": (screen.assumed_sigmas_km(age_s) * 1000.0).tolist(),
            "sma_km": c.get("primary_sma_km", 6780.0),
        }
        pred = predict.predict_cdm(cdm_input, cutoff=2)
        if pred.get("briefing"):
            pred["briefing"][0] = f"[ALERT] {res['primary']['name']} vs {c['secondary']['name']} ({c['secondary']['type']}): " + pred["briefing"][0].replace("[ALERT] ", "")
        self._predictions[eid] = pred
        return pred

    def _item(self, res: dict, c: dict) -> dict:
        band = sorted([c["pc_est"], c["pc_band"]["half"], c["pc_band"]["double"]])
        lg = lambda p: math.log10(max(p, 1e-30))  # noqa: E731
        hours = (datetime.fromisoformat(c["tca"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() / 3600
        return {"event_id": c["event_id"], "source": "live", "decision": screening_decision(c["pc_est"]),
                "time_to_tca_days": round(hours / 24, 3), "p_high": None,
                "risk_p10": lg(band[0]), "risk_p50": lg(c["pc_est"]), "risk_p90": lg(band[2]),
                "baseline_risk": lg(c["pc_est"]), "miss_distance_m": c["miss_km"] * 1000, "chaser_type": c["secondary"]["type"]}

    def detail(self, event_id: str) -> dict | None:
        found = self._find(event_id)
        if not found:
            return None
        res, c = found
        item = self._item(res, c)
        age = c["element_age_days"]
        lines = [
            f"[ALERT] {res['primary']['name']} vs {c['secondary']['name']} ({c['secondary']['type'].lower()}): estimated Pc "
            f"{c['pc_est']:.1e}, TCA {c['tca'].replace('T', ' ')[:16]} UTC.",
            f"[DIAGNOSTIC] Miss {c['miss_km']:.2f} km at {c['rel_speed_kms']:.1f} km/s; Pc uses assumed sigmas from "
            f"element age ({age['primary']:.1f} d / {age['secondary']:.1f} d), no covariance.",
            f"[ACTION] {item['decision']}: " + ("plan avoidance; see maneuver options." if item["decision"] == "MANEUVER"
                                                else "screening only, request a CDM with covariance before any burn."
                                                if item["decision"] == "WATCH" else "no action, re-screen at next catalog update."),
        ]
        return {**item, "cdm_history": [], "available_cutoffs": [], "shap_top": [], "briefing": lines,
                "briefing_source": "template", "true_final_risk": None}

    def maneuver(self, event_id: str) -> dict | None:
        if event_id in self._maneuvers:
            return self._maneuvers[event_id]
        found = self._find(event_id)
        if not found:
            return None
        res, c = found
        tca = datetime.fromisoformat(c["tca"].replace("Z", "+00:00"))
        hours = (tca - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours <= 0:
            return None
        _, extra = screen.estimated_pc(c["rtn_km"], c["rel_v_rtn_kms"], c["element_age_days"]["primary"],
                                       c["element_age_days"]["secondary"])
        inp = {"r": extra["r_m"], "v": extra["v_ms"], "cov_t": extra["cov_t"], "cov_c": extra["cov_c"],
               "radius": screen.LIVE_HARD_BODY_M, "sma_km": c["primary_sma_km"]}
        result = maneuver.search_maneuvers(inp, time_to_tca_h=hours, event_id=event_id)
        rec = result["recommended"]
        if rec["dv_ms"] > 0:
            cat = self.catalog_entries()
            prim = next(x for x in cat if x.norad == res["primary"]["norad"])
            direction = np.array(maneuver.DIRECTIONS[rec["direction"]]) * rec["dv_ms"]
            try:
                result["secondary_check"] = secondary_check(cat, prim, tca - timedelta(hours=rec["burn_lead_h"]), direction,
                                                            tca, ignore={c["secondary"]["norad"]})
            except Exception as exc:
                log.exception("secondary check failed")
                result["secondary_check"] = {"applicable": False, "new_conjunctions": [], "note": f"check failed: {exc}"}
        else:
            result["secondary_check"] = {"applicable": False, "new_conjunctions": [], "note": "no burn needed"}
        self._maneuvers[event_id] = result
        return result


_service: LiveService | None = None


def service() -> LiveService:
    global _service
    if _service is None:
        _service = LiveService()
    return _service


def main() -> int:
    """python -m orbitguard.live — refresh the persisted ISS screening + metrics (offline-safe)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    svc = service()
    svc._run(config.DEFAULT_PRIMARY_NORAD)
    res = svc._results[config.DEFAULT_PRIMARY_NORAD]
    print(f"{res['primary']['name']}: {len(res['conjunctions'])} conjunctions, {res['compute_seconds']} s; "
          f"catalog age {download.catalog_age_hours():.1f} h")
    if res["conjunctions"]:
        eid = res["conjunctions"][0]["event_id"]
        m = svc.maneuver(eid)
        if m:
            print("top conjunction maneuver:", {k: m["recommended"][k] for k in ("dv_ms", "direction", "burn_lead_h", "post_pc")},
                  "| secondary check:", m["secondary_check"]["note"], len(m["secondary_check"]["new_conjunctions"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
