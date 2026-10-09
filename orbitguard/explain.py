"""Module 4 — SHAP drivers + operator briefing (SPEC Section 9).

SHAP values come from LightGBM's built-in TreeSHAP (`pred_contrib=True`) — the same exact algorithm
as shap.TreeExplainer, without a second dependency in the hot path. Values are in log-odds of the
high-risk class (classifier).

Briefing: exactly three lines [ALERT] / [DIAGNOSTIC] / [ACTION]. An LLM writes them when
LLM_PROVIDER=anthropic and a key is set (8 s timeout, numbers only from the input JSON); otherwise,
or on any error, a deterministic template does. Cached per event id in artifacts/briefings.json.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re

import numpy as np
import pandas as pd

from orbitguard import config

log = logging.getLogger("orbitguard.explain")

# --- plain-English feature labels ---------------------------------------------

FEATURE_LABELS: dict[str, str] = {
    "last_risk": "Latest CDM risk",
    "naive_pred": "Latest CDM risk",
    "last_max_risk_estimate": "Worst-case risk (scaled covariance)",
    "last_max_risk_scaling": "Covariance scaling needed for worst case",
    "last_miss_distance": "Latest miss distance",
    "log10_miss_distance": "Latest miss distance (log)",
    "last_relative_speed": "Relative speed",
    "last_c_sigma_r": "Debris radial uncertainty",
    "last_c_sigma_t": "Debris along-track uncertainty",
    "last_c_sigma_n": "Debris cross-track uncertainty",
    "last_t_sigma_r": "Satellite radial uncertainty",
    "last_t_sigma_t": "Satellite along-track uncertainty",
    "last_t_sigma_n": "Satellite cross-track uncertainty",
    "delta_risk": "Change in risk since previous CDM",
    "delta_miss_distance": "Change in miss distance since previous CDM",
    "delta_max_risk_estimate": "Change in worst-case risk since previous CDM",
    "slope_risk": "Risk trend over time",
    "risk_max": "Highest risk seen so far",
    "risk_min": "Lowest risk seen so far",
    "risk_mean": "Average risk so far",
    "risk_std": "Risk volatility across CDMs",
    "n_cdms": "Number of CDMs received",
    "span_days": "Days of CDM history",
    "last_time_to_tca": "Time to closest approach",
    "mahalanobis_proxy": "Miss distance in units of uncertainty",
    "last_mahalanobis_distance": "Mahalanobis distance (ESA)",
    "c_object_type": "Chaser object type",
    "last_F10": "Solar flux F10.7",
    "last_F3M": "Solar flux 81-day mean",
    "last_AP": "Geomagnetic activity (Ap)",
    "last_SSN": "Sunspot number",
    "last_geocentric_latitude": "Latitude of conjunction",
    "last_azimuth": "Approach azimuth",
    "last_elevation": "Approach elevation",
}

_SIDE = {"t": "Satellite", "c": "Debris"}
_AX = {"r": "radial", "t": "along-track", "n": "cross-track", "rdot": "radial-velocity",
       "tdot": "along-track-velocity", "ndot": "cross-track-velocity"}
_FIELD = {"sigma": "uncertainty", "h_apo": "apogee", "h_per": "perigee", "j2k_sma": "semi-major axis",
          "j2k_ecc": "eccentricity", "j2k_inc": "inclination", "span": "size", "obs_used": "observations used",
          "obs_available": "observations available", "weighted_rms": "orbit-fit residual RMS",
          "residuals_accepted": "residuals accepted", "actual_od_span": "orbit-determination span",
          "recommended_od_span": "recommended OD span", "time_lastob_start": "age of last observation (start)",
          "time_lastob_end": "age of last observation (end)", "sedr": "energy dissipation rate",
          "rcs_estimate": "radar cross-section", "cd_area_over_mass": "drag area-to-mass",
          "cr_area_over_mass": "solar-pressure area-to-mass", "position_covariance_det": "position covariance size"}


def label(feature: str) -> str:
    """Plain-English label; falls back to a rule-based translation of the raw name."""
    if feature in FEATURE_LABELS:
        return FEATURE_LABELS[feature]
    name, prefix = feature, ""
    for p, word in (("last_", ""), ("delta_", "Change in "), ("log10_", ""), ("combined_", "Combined ")):
        if name.startswith(p):
            name, prefix = name[len(p):], prefix + word
    m = re.match(r"^([tc])_(.+)$", name)
    side = ""
    if m:
        side, name = _SIDE[m.group(1)] + " ", m.group(2)
    m = re.match(r"^sigma_(\w+)$", name)
    if m:
        return f"{prefix}{side}{_AX.get(m.group(1), m.group(1))} uncertainty".strip().capitalize()
    for k, v in _FIELD.items():
        if name == k:
            return f"{prefix}{side}{v}".strip().capitalize()
    return f"{prefix}{side}{name.replace('_', ' ')}".strip().capitalize()


# --- SHAP ----------------------------------------------------------------------

def shap_matrix(model, X: pd.DataFrame) -> np.ndarray:
    """TreeSHAP contributions (n, n_features); last column (expected value) dropped."""
    contrib = model.predict(X, pred_contrib=True)
    return np.asarray(contrib)[:, :-1]


def top_drivers(contrib_row: np.ndarray, x_row: pd.Series, features: list[str], k: int = 5) -> list[dict]:
    order = np.argsort(-np.abs(contrib_row))[:k]
    out = []
    for i in order:
        f = features[i]
        v = x_row[f]
        try:
            value = None if pd.isna(v) else float(v)
        except (TypeError, ValueError):
            value = None  # categorical
        out.append({"feature": f, "label": label(f), "value": value, "shap": float(contrib_row[i])})
    return out


def global_importance(model, X: pd.DataFrame, features: list[str]) -> pd.Series:
    c = shap_matrix(model, X)
    return pd.Series(np.abs(c).mean(axis=0), index=features).sort_values(ascending=False)


# --- briefing ------------------------------------------------------------------

def one_in(log10_risk: float) -> str:
    if log10_risk <= config.RISK_FLOOR_LOG10 + 1e-9:
        return f"below 1 in {round(10 ** -config.RISK_FLOOR_LOG10):,}"
    return f"about 1 in {int(round(10 ** -log10_risk)):,}"


_OBJECT_PHRASE = {"DEBRIS": "debris", "PAYLOAD": "a payload", "ROCKET BODY": "a rocket body",
                  "UNKNOWN": "an object of unknown type", "TBA": "an unidentified object"}


def _lc(label_text: str) -> str:
    """Lower-case the first letter unless it starts an acronym (keeps 'CDM', 'Ap')."""
    return label_text if label_text[:2].isupper() else label_text[:1].lower() + label_text[1:]


def _grams(g: float) -> str:
    return f"{g:.1f} g" if g < 10 else f"{g:.0f} g"


def template_briefing(ctx: dict) -> list[str]:
    drivers = ctx.get("drivers", [])
    d1 = _lc(drivers[0]["label"]) if drivers else "the latest CDM"
    d2 = f" and {_lc(drivers[1]['label'])}" if len(drivers) > 1 else ""
    obj = _OBJECT_PHRASE.get(str(ctx.get("chaser_type", "")).upper(), "an object")
    alert = (f"[ALERT] Final collision risk {one_in(ctx['risk_p50'])} (P90 {one_in(ctx['risk_p90'])}) "
             f"with {obj}, TCA in {ctx['time_to_tca_days']:.1f} days.")
    diag = f"[DIAGNOSTIC] Driven mainly by {d1}{d2}; miss distance {ctx['miss_distance_m']:.0f} m."
    burn = ctx.get("maneuver")
    if ctx["decision"] == "MANEUVER":
        if burn:
            action = (f"[ACTION] MANEUVER: {burn['dv_ms']:.3g} m/s {burn['direction']} burn {burn['burn_lead_h']:g} h "
                      f"before TCA, residual Pc {burn['post_pc']:.1e}, about {_grams(burn['propellant_g'])} propellant.")
        else:
            action = "[ACTION] MANEUVER: plan avoidance burn; re-assess at next CDM."
    elif ctx["decision"] == "WATCH":
        action = "[ACTION] WATCH: high-risk class, keep maneuver option ready, re-assess at next CDM."
    else:
        action = "[ACTION] HOLD: no action, re-assess at next CDM."
    return [alert, diag, action]


SYSTEM_PROMPT = """You write collision-avoidance briefings for satellite operators.
Input: a JSON object describing one conjunction event.
Output exactly three lines and nothing else:
[ALERT] <one sentence: risk level, time to TCA, object type>
[DIAGNOSTIC] <one sentence: the top 1-2 drivers in plain words>
[ACTION] <one sentence: the decision and the delta-v recommendation if present, otherwise "no action, re-assess at next CDM">
Rules: use only numbers that appear in the input JSON and never invent values; at most 25 words per line;
express risk as "1 in N" using the provided risk_one_in fields; keep the decision word exactly as given."""


def _llm_enabled() -> bool:
    return config.LLM_PROVIDER == "anthropic" and bool(config.ANTHROPIC_API_KEY)


def llm_briefing(ctx: dict) -> list[str] | None:
    """Return three validated lines from the LLM, or None (caller falls back to the template)."""
    if not _llm_enabled():
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        payload = {**ctx, "risk_one_in_p50": one_in(ctx["risk_p50"]), "risk_one_in_p90": one_in(ctx["risk_p90"])}
        resp = client.with_options(timeout=config.LLM_TIMEOUT_S, max_retries=0).messages.create(
            model=config.LLM_MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload, default=float)}],
        )
        if resp.stop_reason not in ("end_turn", "stop_sequence"):
            return None
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        tags = ("[ALERT]", "[DIAGNOSTIC]", "[ACTION]")
        if len(lines) != 3 or any(not ln.startswith(t) for ln, t in zip(lines, tags)):
            log.warning("LLM briefing malformed, using template: %r", text[:200])
            return None
        if any(len(ln.split()) > 32 for ln in lines):  # 25 words + tag + slack
            return None
        return lines
    except Exception as exc:  # timeout, auth, network, SDK errors — the demo must never crash
        log.warning("LLM briefing failed (%s), using template", type(exc).__name__)
        return None


def _load_cache() -> dict:
    try:
        return json.loads(config.BRIEFINGS_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _ctx_hash(ctx: dict) -> str:
    return hashlib.sha1(json.dumps(ctx, sort_keys=True, default=str).encode()).hexdigest()[:16]


def briefing(ctx: dict, cache_key: str, *, use_llm: bool = True, cache: dict | None = None) -> tuple[list[str], str]:
    """Return (three lines, source) where source is "llm" or "template". Uses/updates the cache dict.

    Entries are reused only when the input numbers are identical (content hash), so a retrained model
    can never be described by a stale briefing.
    """
    cache = _load_cache() if cache is None else cache
    h = _ctx_hash(ctx)
    hit = cache.get(cache_key)
    if hit and hit.get("ctx_hash") == h and (hit["source"] == "llm" or not (use_llm and _llm_enabled())):
        return hit["lines"], hit["source"]
    lines = llm_briefing(ctx) if use_llm else None
    source = "llm" if lines else "template"
    lines = lines or template_briefing(ctx)
    cache[cache_key] = {"lines": lines, "source": source, "ctx_hash": h}
    return lines, source


def save_cache(cache: dict) -> None:
    config.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    config.BRIEFINGS_PATH.write_text(json.dumps(cache, indent=1))
