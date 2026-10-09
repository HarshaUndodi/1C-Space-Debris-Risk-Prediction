"""2D collision probability in the encounter plane (Foster / Alfano method) — SPEC 10.1.

Assumptions (standard short-encounter model): straight-line relative motion during the encounter,
constant combined position covariance, no velocity uncertainty. Then
    Pc = ∬_{|ξ| ≤ R} N(ξ; μ, Σ) dξ
where μ, Σ are the relative position and combined covariance projected onto the plane ⊥ to v_rel.
"""
from __future__ import annotations

import numpy as np

PC_FLOOR = 1e-30

# Polar quadrature over the hard-body disk (vectorised; called thousands of times by the maneuver search).
_NR, _NT = 64, 128
_gl_x, _gl_w = np.polynomial.legendre.leggauss(_NR)       # Gauss-Legendre in radius
_RHO = 0.5 * (_gl_x + 1.0)                                # nodes on [0, 1]
_RHO_W = 0.5 * _gl_w
_THETA = np.linspace(0.0, 2 * np.pi, _NT, endpoint=False)  # periodic trapezoid in angle (spectrally accurate)
_COS, _SIN = np.cos(_THETA), np.sin(_THETA)


def covariance_rtn(sr, st, sn, ctr=0.0, cnr=0.0, cnt=0.0) -> np.ndarray:
    """3x3 RTN covariance (m²) from sigmas (m) and correlation coefficients (Kelvins x_ct_r, x_cn_r, x_cn_t)."""
    def z(v):
        return 0.0 if v is None or not np.isfinite(v) else float(v)
    ctr, cnr, cnt = z(ctr), z(cnr), z(cnt)
    return np.array([[sr * sr, ctr * sr * st, cnr * sr * sn],
                     [ctr * sr * st, st * st, cnt * st * sn],
                     [cnr * sr * sn, cnt * st * sn, sn * sn]], dtype=float)


def encounter_frame(r: np.ndarray, v: np.ndarray) -> np.ndarray:
    """2x3 projection P = [x̂; ẑ] onto the plane ⊥ to the relative velocity (x̂ along the miss vector)."""
    y_hat = v / np.linalg.norm(v)
    r_perp = r - np.dot(r, y_hat) * y_hat
    n = np.linalg.norm(r_perp)
    if n < 1e-9:  # dead-centre: any unit vector ⊥ ŷ
        trial = np.array([1.0, 0.0, 0.0]) if abs(y_hat[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        r_perp = trial - np.dot(trial, y_hat) * y_hat
        n = np.linalg.norm(r_perp)
    x_hat = r_perp / n
    z_hat = np.cross(x_hat, y_hat)
    return np.vstack([x_hat, z_hat])


def pc_2d(mu: np.ndarray, sigma: np.ndarray, radius: float) -> float:
    """∬ over the disk |ξ| ≤ radius of N(ξ; mu, sigma) by polar Gauss-Legendre × trapezoid quadrature."""
    return float(pc_2d_batch(np.asarray(mu, float)[None, :], np.asarray(sigma, float)[None, :, :], radius)[0])


def pc_2d_batch(mu: np.ndarray, sigma: np.ndarray, radius: float | np.ndarray) -> np.ndarray:
    """Vectorised over a batch: mu (n,2), sigma (n,2,2), radius scalar or (n,)."""
    mu = np.asarray(mu, float)
    sigma = np.asarray(sigma, float)
    R = np.broadcast_to(np.asarray(radius, float), (mu.shape[0],))
    a, b, d = sigma[:, 0, 0], sigma[:, 0, 1], sigma[:, 1, 1]
    det = a * d - b * b
    det = np.where(det <= 0, np.nan, det)
    ia, ib, id_ = d / det, -b / det, a / det                # inverse covariance entries
    rho = R[:, None] * _RHO[None, :]                        # (n, NR)
    x = rho[:, :, None] * _COS[None, None, :] - mu[:, 0, None, None]
    y = rho[:, :, None] * _SIN[None, None, :] - mu[:, 1, None, None]
    q = ia[:, None, None] * x * x + 2 * ib[:, None, None] * x * y + id_[:, None, None] * y * y
    dens = np.exp(-0.5 * q) / (2 * np.pi * np.sqrt(det))[:, None, None]
    # ∫0^R ∫0^2π f ρ dθ dρ  ≈  Σ_i w_i R ρ_i Σ_j f (2π/NT)
    integral = (dens.sum(axis=2) * (2 * np.pi / _NT) * rho * (_RHO_W[None, :] * R[:, None])).sum(axis=1)
    return np.clip(np.nan_to_num(integral, nan=0.0), 0.0, 1.0)


def collision_probability(r_rel: np.ndarray, v_rel: np.ndarray, cov_t: np.ndarray, cov_c: np.ndarray,
                          radius: float) -> tuple[float, float]:
    """Pc and log10(Pc) for relative position r (m, secondary − primary), velocity v (m/s), RTN covariances."""
    P = encounter_frame(np.asarray(r_rel, float), np.asarray(v_rel, float))
    mu = P @ r_rel
    S = P @ (cov_t + cov_c) @ P.T
    pc = max(pc_2d(mu, S, radius), PC_FLOOR)
    return pc, float(np.log10(pc))


def hard_body_radius(t_span: float, c_span: float) -> float:
    """R = (t_span + c_span)/2 — spans are diameters; Kelvins uses a 2 m minimum for the chaser."""
    t = t_span if np.isfinite(t_span) else 2.0
    c = max(c_span if np.isfinite(c_span) else 2.0, 2.0)
    return 0.5 * (t + c)


# --- Kelvins CDM → Pc inputs -----------------------------------------------------

def chaser_to_target_rtn(rel_v_rtn: np.ndarray, sma_km: float) -> np.ndarray:
    """Rotation taking the chaser's RTN frame into the target's RTN frame (approximate).

    Kelvins gives the chaser covariance in the chaser's own RTN frame. At TCA both objects are at
    (nearly) the same position, so R̂ is shared; the chaser's T̂ follows its velocity
    v_c = v_t + v_rel, with v_t ≈ (0, sqrt(μ/a), 0) in the target RTN frame (near-circular orbit).
    """
    v_t = np.array([0.0, np.sqrt(3.986004418e14 / (sma_km * 1e3)), 0.0])
    v_c = v_t + rel_v_rtn
    r_hat = np.array([1.0, 0.0, 0.0])
    t_c = v_c - np.dot(v_c, r_hat) * r_hat
    t_c /= np.linalg.norm(t_c)
    n_c = np.cross(r_hat, t_c)
    return np.column_stack([r_hat, t_c, n_c])  # columns = chaser axes expressed in target RTN


def cdm_inputs(row) -> dict | None:
    """Build Pc inputs from one Kelvins CDM row (pandas Series or dict). None if covariance is incomplete."""
    need = ["relative_position_r", "relative_position_t", "relative_position_n",
            "relative_velocity_r", "relative_velocity_t", "relative_velocity_n",
            "t_sigma_r", "t_sigma_t", "t_sigma_n", "c_sigma_r", "c_sigma_t", "c_sigma_n", "t_j2k_sma"]
    vals = {k: row[k] for k in need}
    if any(v is None or not np.isfinite(v) for v in vals.values()):
        return None
    r = np.array([vals["relative_position_r"], vals["relative_position_t"], vals["relative_position_n"]], float)
    v = np.array([vals["relative_velocity_r"], vals["relative_velocity_t"], vals["relative_velocity_n"]], float)
    if np.linalg.norm(v) < 1e-6:
        return None
    cov_t = covariance_rtn(row["t_sigma_r"], row["t_sigma_t"], row["t_sigma_n"],
                           row.get("t_ct_r"), row.get("t_cn_r"), row.get("t_cn_t"))
    cov_c_own = covariance_rtn(row["c_sigma_r"], row["c_sigma_t"], row["c_sigma_n"],
                               row.get("c_ct_r"), row.get("c_cn_r"), row.get("c_cn_t"))
    M = chaser_to_target_rtn(v, float(row["t_j2k_sma"]))
    cov_c = M @ cov_c_own @ M.T
    radius = hard_body_radius(float(row.get("t_span", np.nan)), float(row.get("c_span", np.nan)))
    return {"r": r, "v": v, "cov_t": cov_t, "cov_c": cov_c, "radius": radius, "sma_km": float(row["t_j2k_sma"])}


def validate_against_kelvins(cdm_df, n: int = 20000, seed: int = 42) -> dict:
    """Spearman correlation of log10(Pc_ours) vs Kelvins `risk` on CDMs with complete covariance."""
    from scipy.stats import spearmanr

    sample = cdm_df.sample(min(n, len(cdm_df)), random_state=seed)
    ours, theirs = [], []
    for _, row in sample.iterrows():
        inp = cdm_inputs(row)
        if inp is None or not np.isfinite(row["risk"]):
            continue
        _, lp = collision_probability(inp["r"], inp["v"], inp["cov_t"], inp["cov_c"], inp["radius"])
        ours.append(lp)
        theirs.append(float(row["risk"]))
    ours, theirs = np.array(ours), np.array(theirs)
    above = theirs > -30 + 1e-9  # exclude ESA's -30 floor (ties carry no rank information)
    both = above & (ours > np.log10(PC_FLOOR) + 1e-9)
    res = {
        "n_cdms": int(len(ours)),
        "spearman_all": float(spearmanr(ours, theirs).statistic),
        "n_above_floor": int(both.sum()),
        "spearman_above_floor": float(spearmanr(ours[both], theirs[both]).statistic) if both.sum() > 10 else None,
        "median_abs_log10_diff_above_floor": float(np.median(np.abs(ours[both] - theirs[both]))) if both.any() else None,
        "within_1_order_of_magnitude": float(np.mean(np.abs(ours[both] - theirs[both]) <= 1.0)) if both.any() else None,
    }
    return res


def main() -> int:
    """python -m orbitguard.pc — validate vs Kelvins `risk` and write metrics.json["pc_validation"]."""
    from orbitguard import evaluate, features

    train, _, _ = features.load_kelvins()
    res = validate_against_kelvins(train)
    evaluate.save_metrics({"pc_validation": res})
    print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
