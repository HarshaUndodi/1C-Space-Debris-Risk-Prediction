"""On-demand prediction engine for live Conjunction Data Messages (CDMs).

Takes a live CDM dictionary (or live screened conjunction), constructs the feature vector,
and runs the trained LightGBM models (classifier, regressor, quantiles, TreeSHAP) plus
the Clohessy–Wiltshire maneuver engine.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from orbitguard import config, explain, features, maneuver, models, pc, screen, spaceweather

# Mapping from raw feature names to plain English labels
FEATURE_LABELS = explain.FEATURE_LABELS


def build_cdm_feature_row(cdm: dict, bundle_features: list[str]) -> pd.DataFrame:
    """Map a single CDM / conjunction dictionary into a 1-row DataFrame matching bundle.features."""
    row = {col: np.nan for col in bundle_features}

    # Time to TCA
    time_to_tca = float(cdm.get("time_to_tca", cdm.get("time_to_tca_days", 2.0)))
    row["last_time_to_tca"] = time_to_tca

    # Miss distance
    miss_m = float(cdm.get("miss_distance_m", cdm.get("miss_distance", cdm.get("miss_km", 1.0) * 1000.0)))
    row["last_miss_distance"] = miss_m
    row["log10_miss_distance"] = float(np.log10(max(1e-3, miss_m)))

    # Relative speed
    speed_ms = float(cdm.get("relative_speed_ms", cdm.get("rel_speed_kms", 11.5) * 1000.0))
    row["last_relative_speed"] = speed_ms

    # Prior / latest risk estimate
    risk = cdm.get("risk", cdm.get("pc_est", None))
    if risk is not None:
        risk_log = float(math.log10(max(1e-30, risk))) if risk > 0 and risk <= 1.0 else float(risk)
    else:
        risk_log = -6.0
    row["last_risk"] = max(config.RISK_FLOOR_LOG10, risk_log)

    # Relative position RTN
    rtn_pos = cdm.get("relative_position_rtn", cdm.get("rtn_km", [0.0, miss_m / 1000.0, 0.0]))
    if isinstance(rtn_pos, (list, tuple)) and len(rtn_pos) >= 3:
        # If given in km, scale to meters if small
        scale = 1000.0 if np.linalg.norm(rtn_pos) < 50.0 else 1.0
        row["last_relative_position_r"] = float(rtn_pos[0]) * scale
        row["last_relative_position_t"] = float(rtn_pos[1]) * scale
        row["last_relative_position_n"] = float(rtn_pos[2]) * scale

    # Relative velocity RTN
    rtn_vel = cdm.get("relative_velocity_rtn", cdm.get("rel_v_rtn_kms", [0.0, speed_ms / 1000.0, 0.0]))
    if isinstance(rtn_vel, (list, tuple)) and len(rtn_vel) >= 3:
        scale_v = 1000.0 if np.linalg.norm(rtn_vel) < 50.0 else 1.0
        row["last_relative_velocity_r"] = float(rtn_vel[0]) * scale_v
        row["last_relative_velocity_t"] = float(rtn_vel[1]) * scale_v
        row["last_relative_velocity_n"] = float(rtn_vel[2]) * scale_v

    # Covariance 1-sigmas
    sigmas_t = cdm.get("target_sigmas_m", cdm.get("t_sigmas", [50.0, 150.0, 50.0]))
    sigmas_c = cdm.get("chaser_sigmas_m", cdm.get("c_sigmas", [120.0, 450.0, 120.0]))

    row["last_t_sigma_r"] = float(sigmas_t[0])
    row["last_t_sigma_t"] = float(sigmas_t[1])
    row["last_t_sigma_n"] = float(sigmas_t[2])

    row["last_c_sigma_r"] = float(sigmas_c[0])
    row["last_c_sigma_t"] = float(sigmas_c[1])
    row["last_c_sigma_n"] = float(sigmas_c[2])

    # Combined sigmas
    for ax, idx in (("r", 0), ("t", 1), ("n", 2)):
        s_comb = math.sqrt(float(sigmas_t[idx]) ** 2 + float(sigmas_c[idx]) ** 2)
        row[f"combined_sigma_{ax}"] = s_comb
        row[f"log10_t_sigma_{ax}"] = math.log10(max(1e-6, float(sigmas_t[idx])))
        row[f"log10_c_sigma_{ax}"] = math.log10(max(1e-6, float(sigmas_c[idx])))

    # Mahalanobis proxy
    diff_sq = sum(
        (row.get(f"last_relative_position_{ax}", 0.0) / max(1.0, row.get(f"combined_sigma_{ax}", 1.0))) ** 2
        for ax in "rtn"
    )
    row["mahalanobis_proxy"] = math.sqrt(diff_sq)

    # Space weather
    sw = spaceweather.latest()
    if sw:
        row["last_F10"] = float(sw["f107"])
        row["last_AP"] = float(sw["ap"])
    else:
        row["last_F10"] = 150.0
        row["last_AP"] = 12.0

    # Object type
    obj_type = str(cdm.get("chaser_type", cdm.get("secondary_type", "DEBRIS"))).upper()
    if obj_type not in features.OBJECT_TYPES:
        obj_type = "DEBRIS" if "DEB" in obj_type else "PAYLOAD" if "PAY" in obj_type else "UNKNOWN"
    row["c_object_type"] = obj_type

    # Single-event summaries
    row["n_cdms"] = int(cdm.get("n_cdms", 1))
    row["span_days"] = float(cdm.get("span_days", 0.0))
    row["risk_mean"] = row["last_risk"]
    row["risk_max"] = row["last_risk"]
    row["risk_min"] = row["last_risk"]
    row["risk_std"] = 0.0
    row["last_max_risk_estimate"] = row["last_risk"] + 0.8
    row["last_max_risk_scaling"] = 1.2

    df = pd.DataFrame([row])[bundle_features]
    df["c_object_type"] = pd.Categorical(df["c_object_type"], categories=features.OBJECT_TYPES)
    return df


def predict_cdm(cdm: dict, cutoff: int = 2) -> dict:
    """Predict collision risk and maneuver options for an arbitrary live CDM."""
    cutoff_val = min(6, max(2, int(cutoff)))
    bundle = models.load_bundle(cutoff_val)

    # Feature preparation
    df = build_cdm_feature_row(cdm, bundle.features)

    # 1. Classification (p_high & raw score)
    raw_margin = float(bundle.clf._margin(df)[0])
    p_high = float(bundle.iso.transform([raw_margin])[0])

    # Decision rule
    if raw_margin >= bundle.tau_raw:
        decision = "MANEUVER"
    elif p_high >= 0.15 or float(df["last_risk"].iloc[0]) >= -5.5:
        decision = "WATCH"
    else:
        decision = "HOLD"

    # 2. Risk Regression & Quantile Bands
    baseline_risk = float(df["last_risk"].iloc[0])
    res_pred = float(bundle.reg.predict(df)[0])
    risk_p50 = round(float(np.clip(baseline_risk + bundle.alpha * res_pred, config.RISK_FLOOR_LOG10, 0.0)), 3)

    q10_raw = float(bundle.q10.predict(df)[0])
    q90_raw = float(bundle.q90.predict(df)[0])
    w = max(0.2, (q90_raw - q10_raw) / 2.0)
    risk_p10 = round(float(np.clip(risk_p50 - w, config.RISK_FLOOR_LOG10, 0.0)), 3)
    risk_p90 = round(float(np.clip(risk_p50 + w, config.RISK_FLOOR_LOG10, 0.0)), 3)

    # 3. TreeSHAP Feature Drivers
    shap_all = bundle.clf.predict(df, pred_contrib=True)[0][:-1]  # drop bias
    top_indices = np.argsort(np.abs(shap_all))[::-1][:5]
    shap_top = []
    for idx in top_indices:
        feat_name = bundle.features[idx]
        val = df[feat_name].iloc[0]
        val_clean = float(val) if pd.notna(val) and isinstance(val, (int, float, np.number)) else None
        shap_top.append({
            "feature": feat_name,
            "label": FEATURE_LABELS.get(feat_name, feat_name.replace("_", " ").title()),
            "value": val_clean,
            "shap": round(float(shap_all[idx]), 3),
        })

    # 4. Maneuver Calculation
    miss_m = float(df["last_miss_distance"].iloc[0])
    speed_ms = float(df["last_relative_speed"].iloc[0])
    r_vec = np.array([float(df.get(f"last_relative_position_{ax}", [0.0])[0]) for ax in "rtn"])
    v_vec = np.array([float(df.get(f"last_relative_velocity_{ax}", [0.0])[0]) for ax in "rtn"])
    if np.linalg.norm(r_vec) == 0:
        r_vec = np.array([0.0, miss_m, 0.0])
    if np.linalg.norm(v_vec) == 0:
        v_vec = np.array([0.0, speed_ms, 0.0])

    cov_t = np.diag([float(df[f"last_t_sigma_{ax}"].iloc[0]) ** 2 for ax in "rtn"])
    cov_c = np.diag([float(df[f"last_c_sigma_{ax}"].iloc[0]) ** 2 for ax in "rtn"])

    sma_km = float(cdm.get("sma_km", 6780.0))
    time_to_tca_h = float(df["last_time_to_tca"].iloc[0]) * 24.0

    inp_maneuver = {
        "r": r_vec,
        "v": v_vec,
        "cov_t": cov_t,
        "cov_c": cov_c,
        "radius": screen.LIVE_HARD_BODY_M,
        "sma_km": sma_km,
    }

    event_id = str(cdm.get("event_id", f"live-cdm-{int(pd.Timestamp.now().timestamp())}"))
    man_res = maneuver.search_maneuvers(inp_maneuver, time_to_tca_h=time_to_tca_h, event_id=event_id)

    # 5. Operator Briefing
    time_days = float(df["last_time_to_tca"].iloc[0])
    briefing_lines = [
        f"[ALERT] Predicted final collision risk {explain.one_in(risk_p50)} (P90 {explain.one_in(risk_p90)}) "
        f"with {df['c_object_type'].iloc[0]}, TCA in {time_days:.1f} days.",
        f"[DIAGNOSTIC] Driven by {shap_top[0]['label']} (SHAP {shap_top[0]['shap']:+.2f}); "
        f"miss distance {miss_m:.0f} m at {speed_ms/1000:.1f} km/s.",
    ]
    if decision == "MANEUVER" and man_res["recommended"]["dv_ms"] > 0:
        rec = man_res["recommended"]
        briefing_lines.append(
            f"[ACTION] MANEUVER: {rec['dv_ms']:.3g} m/s {rec['direction']} burn {rec['burn_lead_h']:g} h "
            f"before TCA, residual Pc {rec['post_pc']:.1e}, about {rec['propellant_g']:.1f} g propellant."
        )
    elif decision == "WATCH":
        briefing_lines.append("[ACTION] WATCH: elevated risk class, keep avoidance plan ready, re-assess at next CDM.")
    else:
        briefing_lines.append("[ACTION] HOLD: safe corridor, no action required, continue tracking.")

    return {
        "event_id": event_id,
        "source": "live",
        "decision": decision,
        "time_to_tca_days": round(time_days, 3),
        "p_high": round(p_high, 4),
        "risk_p10": risk_p10,
        "risk_p50": risk_p50,
        "risk_p90": risk_p90,
        "baseline_risk": round(baseline_risk, 3),
        "miss_distance_m": round(miss_m, 1),
        "chaser_type": str(df["c_object_type"].iloc[0]),
        "cdm_history": cdm.get("cdm_history", [{
            "time_to_tca": round(time_days, 3),
            "risk": round(baseline_risk, 3),
            "miss_distance_m": round(miss_m, 1),
        }]),
        "available_cutoffs": [2, 3, 4, 5, 6],
        "shap_top": shap_top,
        "briefing": briefing_lines,
        "briefing_source": "template",
        "maneuver": man_res,
        "true_final_risk": None,
    }
