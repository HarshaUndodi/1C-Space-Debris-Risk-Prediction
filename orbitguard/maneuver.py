"""Maneuver search: burn size × direction × timing with CW relative motion (SPEC 10.3).

For each option the primary is displaced by δ (CW) at TCA, the relative position becomes r' = r − δ
(secondary unchanged), velocity and covariances are kept, and Pc is recomputed. The encounter-plane
basis depends only on v, so Σ is shared by every option and the search is one vectorised Pc batch.
"""
from __future__ import annotations

import numpy as np

from orbitguard import config, cw, pc

DV_GRID = np.logspace(-3, np.log10(2.0), 40)                     # m/s
DIRECTIONS = {"+along": (0.0, 1.0, 0.0), "-along": (0.0, -1.0, 0.0),
              "+radial": (1.0, 0.0, 0.0), "-radial": (-1.0, 0.0, 0.0)}
LEADS_H = (6, 12, 24, 36, 48, 72)


def propellant_g(dv_ms: float, m0_kg: float = config.DEFAULT_SAT_MASS_KG, isp_s: float = config.DEFAULT_ISP_S) -> float:
    """Rocket equation: m_prop = m0 (1 − exp(−Δv / (Isp g0))), in grams."""
    return float(m0_kg * (1.0 - np.exp(-dv_ms / (isp_s * config.G0))) * 1000.0)


def _plane_basis(v: np.ndarray) -> np.ndarray:
    y_hat = v / np.linalg.norm(v)
    trial = np.array([1.0, 0.0, 0.0]) if abs(y_hat[0]) < 0.9 else np.array([0.0, 0.0, 1.0])
    e1 = trial - np.dot(trial, y_hat) * y_hat
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(e1, y_hat)
    return np.vstack([e1, e2])


def search_maneuvers(inp: dict, time_to_tca_h: float | None = None, target_pc: float = config.TARGET_PC,
                     event_id: str = "", secondary_check: dict | None = None) -> dict:
    """inp: {r, v, cov_t, cov_c, radius, sma_km} (pc.cdm_inputs). Returns the Section 13 maneuver JSON.

    Burn lead times longer than the time remaining to TCA are skipped (a burn cannot be in the past).
    """
    r, v = np.asarray(inp["r"], float), np.asarray(inp["v"], float)
    E = _plane_basis(v)
    S = E @ (inp["cov_t"] + inp["cov_c"]) @ E.T
    R = float(inp["radius"])
    n = cw.mean_motion(inp["sma_km"] * 1e3)
    pre = max(pc.pc_2d(E @ r, S, R), pc.PC_FLOOR)

    leads = [h for h in LEADS_H if time_to_tca_h is None or h <= time_to_tca_h + 1e-9] or [min(LEADS_H)]
    dirs = list(DIRECTIONS)
    grid = np.array([(dv, di, h) for dv in DV_GRID for di in range(len(dirs)) for h in leads])
    dv_vec = grid[:, 0:1] * np.array([DIRECTIONS[dirs[int(i)]] for i in grid[:, 1]])
    delta = cw.displacement_batch(dv_vec, n, grid[:, 2] * 3600.0)
    mu = (r[None, :] - delta) @ E.T
    post = np.maximum(pc.pc_2d_batch(mu, np.broadcast_to(S, (len(mu), 2, 2)), R), pc.PC_FLOOR)

    points = [{"dv_ms": float(g[0]), "direction": dirs[int(g[1])], "burn_lead_h": float(g[2]), "post_pc": float(p)}
              for g, p in zip(grid, post)]
    pareto = []
    for dv in DV_GRID:
        m = grid[:, 0] == dv
        pareto.append({"dv_ms": float(dv), "post_pc": float(post[m].min())})

    note = None
    if pre <= target_pc:
        rec = {"dv_ms": 0.0, "direction": "+along", "burn_lead_h": 0.0, "post_pc": float(pre), "propellant_g": 0.0}
        met = True
        note = "pre-burn Pc already below target — no maneuver needed"
    else:
        ok = np.where(post <= target_pc)[0]
        if len(ok):
            # smallest Δv; tie-break: later burn (shorter lead keeps options open)
            i = min(ok, key=lambda k: (grid[k, 0], grid[k, 2]))
            met = True
        else:
            i = int(np.argmin(post))
            met = False
            note = "no option in the search grid reaches the target Pc — showing the lowest achievable"
        rec = {**points[i], "propellant_g": propellant_g(points[i]["dv_ms"])}

    return {
        "event_id": str(event_id),
        "target_pc": target_pc,
        "target_met": bool(met),
        "pre_burn_pc": float(pre),
        "recommended": rec,
        "points": points,
        "pareto": pareto,
        "secondary_check": secondary_check or {"applicable": False, "new_conjunctions": [],
                                               "note": "not applicable — no catalog context (historical ESA CDM)"},
        "note": note,
        "assumptions": {"mass_kg": config.DEFAULT_SAT_MASS_KG, "isp_s": config.DEFAULT_ISP_S,
                        "hard_body_radius_m": R, "dynamics": "Clohessy-Wiltshire (linear, near-circular)"},
    }
