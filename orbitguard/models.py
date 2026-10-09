"""Module 2 — baseline, LightGBM regressor / classifier / quantile models (SPEC Section 7).

Per cutoff:
  1. 5-fold out-of-fold (OOF) training on train events. In each fold: train on 3 folds, early-stop on
     1 fold, predict the held-out fold. OOF predictions feed calibration + threshold (calibrate.py)
     and the regressor shrinkage α.
  2. Final models on all train events with n_estimators = median best iteration of the folds.
  3. Save bundle to artifacts/models/cutoff{d}/ and τ etc. to artifacts/model_config.json.

Design choices (selected on OOF training data only, never on test — see README "Modelling notes"):
  * Risk targets are clipped at config.RISK_FLOOR_LOG10 (-6.5); the -30 floor otherwise dominates L2.
  * The regressor predicts the RESIDUAL vs the (clipped) latest CDM risk — the naive baseline is the
    prior, trees learn corrections — and the correction is shrunk by α ∈ {0.25, 0.5, 1} picked on OOF.
  * The classifier uses small trees and no class weighting (scale_pos_weight = n_neg/n_pos made it
    collapse with ~13 positives per fold); early stopping on log-loss (AUC-PR was too noisy).

Run: python -m orbitguard.models [--cutoffs 2 3 4 5 6]
"""
from __future__ import annotations

import argparse
import json
import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from orbitguard import calibrate, config, features, metrics

log = logging.getLogger("orbitguard.models")
warnings.filterwarnings("ignore", message="X does not have valid feature names")
warnings.filterwarnings("ignore", message=".*'eval_set' is deprecated.*")

FLOOR = config.RISK_FLOOR_LOG10
COMMON = dict(n_estimators=2000, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
              random_state=config.SEED, verbose=-1, n_jobs=-1)
PARAMS = {
    "reg": dict(objective="regression", learning_rate=0.01, num_leaves=4, min_child_samples=200, reg_lambda=10.0),
    "clf": dict(objective="binary", learning_rate=0.03, num_leaves=7, min_child_samples=40),
    "q10": dict(objective="quantile", alpha=0.1, learning_rate=0.03, num_leaves=15, min_child_samples=20),
    "q90": dict(objective="quantile", alpha=0.9, learning_rate=0.03, num_leaves=15, min_child_samples=20),
}
ES_METRIC = {"reg": "l2", "clf": "binary_logloss", "q10": "quantile", "q90": "quantile"}
EARLY_STOP = 100
HR_WEIGHT = 10.0
ALPHAS = (0.25, 0.5, 1.0)
KINDS = ("reg", "clf", "q10", "q90")
MODELS_DIR = config.ARTIFACTS_DIR / "models"


def model_dir(cutoff: float) -> Path:
    return MODELS_DIR / f"cutoff{int(cutoff)}"


class FoldEnsemble:
    """The 5 fold models used as one predictor (CV bagging).

    Production predictions come from the SAME models whose out-of-fold scores set tau, so the
    threshold transfers (a refit-on-all model has a different score scale). Classifier members are
    averaged in log-odds, which keeps TreeSHAP contributions exactly additive (mean of members').
    """

    def __init__(self, members: list, classifier: bool):
        self.members = members
        self.classifier = classifier

    def _margin(self, X) -> np.ndarray:
        return np.mean([m.predict(X, raw_score=True) for m in self.members], axis=0)

    def predict(self, X, pred_contrib: bool = False):
        if pred_contrib:
            return np.mean([m.predict(X, pred_contrib=True) for m in self.members], axis=0)
        if self.classifier:
            return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)
        return np.mean([m.predict(X) for m in self.members], axis=0)

    def predict_proba(self, X) -> np.ndarray:
        p = 1.0 / (1.0 + np.exp(-self._margin(X)))
        return np.column_stack([1 - p, p])


@dataclass
class Bundle:
    cutoff: float
    features: list[str]
    reg: FoldEnsemble
    clf: FoldEnsemble
    q10: FoldEnsemble
    q90: FoldEnsemble
    iso: object
    baseline_lr: object
    tau: float          # calibrated-probability value shown in the UI (= iso(tau_raw))
    tau_raw: float      # decision threshold on the raw classifier score
    baseline_level: float
    alpha: float
    risk_range: tuple[float, float]
    info: dict = field(default_factory=dict)


# --- fitting -----------------------------------------------------------------

def clip_risk(r) -> np.ndarray:
    return np.maximum(np.asarray(r, float), FLOOR)


def _fit(kind: str, X, y, X_es=None, y_es=None, n_estimators: int | None = None, sample_weight=None):
    params = {**COMMON, **PARAMS[kind]}
    if n_estimators is not None:
        params["n_estimators"] = n_estimators
    m = lgb.LGBMClassifier(**params) if kind == "clf" else lgb.LGBMRegressor(**params)
    kw = {"sample_weight": sample_weight}
    if X_es is not None:
        kw.update(eval_set=[(X_es, y_es)], eval_metric=ES_METRIC[kind],
                  callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)])
    m.fit(X, y, **kw)
    return m


def _best_iter(m) -> int:
    return int(m.best_iteration_ or m.n_estimators)


def _target(df: pd.DataFrame, kind: str) -> np.ndarray:
    if kind == "clf":
        return df["is_high_risk"].to_numpy()
    t = clip_risk(df["target_final_risk"])
    return t - clip_risk(df["naive_pred"]) if kind == "reg" else t


def _weights(df: pd.DataFrame, kind: str):
    return np.where(df["is_high_risk"] == 1, HR_WEIGHT, 1.0) if kind == "reg" else None


def _raw(models: dict, X: pd.DataFrame) -> dict[str, np.ndarray]:
    return {"reg": models["reg"].predict(X), "clf": models["clf"].predict_proba(X)[:, 1],
            "q10": models["q10"].predict(X), "q90": models["q90"].predict(X)}


def train_cutoff(cutoff: float) -> tuple[Bundle, pd.DataFrame]:
    ev = features.load_events(cutoff)
    feats = features.feature_columns(ev)
    train = ev[ev["split"] == "train"].reset_index(drop=True)
    hi = float(train["target_final_risk"].max())

    # 1) out-of-fold
    oof = {k: np.full(len(train), np.nan) for k in KINDS}
    best: dict[str, list[int]] = {k: [] for k in KINDS}
    members: dict[str, list] = {k: [] for k in KINDS}
    for k in range(config.N_FOLDS):
        es_fold = (k + 1) % config.N_FOLDS
        tr = train[(train["fold"] != k) & (train["fold"] != es_fold)]
        es = train[train["fold"] == es_fold]
        ho = (train["fold"] == k).to_numpy()
        fm = {kind: _fit(kind, tr[feats], _target(tr, kind), es[feats], _target(es, kind),
                         sample_weight=_weights(tr, kind)) for kind in KINDS}
        for kind in KINDS:
            best[kind].append(_best_iter(fm[kind]))
            members[kind].append(fm[kind])
        raw = _raw(fm, train.loc[ho, feats])
        for kind in KINDS:
            oof[kind][ho] = raw[kind]
    log.info("cutoff %s best iterations: %s", cutoff, best)

    # 2) production predictor = the fold models themselves (see FoldEnsemble)
    final = {kind: FoldEnsemble(members[kind], classifier=(kind == "clf")) for kind in KINDS}

    # 3) choices fitted on OOF predictions
    y = train["is_high_risk"].to_numpy()
    t = train["target_final_risk"].to_numpy()
    nc = clip_risk(train["naive_pred"])
    alpha_scores = {a: metrics.kelvins_score(t, np.clip(nc + a * oof["reg"], FLOOR, hi))["kelvins_score"] for a in ALPHAS}
    alpha = min(alpha_scores, key=alpha_scores.get)
    iso = calibrate.fit_isotonic(oof["clf"], y)
    p_cal_oof = iso.predict(oof["clf"])
    # Threshold on the RAW score: isotonic output is a step function, and its lowest plateau holds most
    # events, so a 95%-recall cut on calibrated values can collapse to "flag everything". The raw score
    # keeps the ranking; tau (calibrated) = iso(tau_raw) is what the UI shows.
    tau_raw = calibrate.choose_threshold(oof["clf"], y, 0.95)
    tau = float(iso.predict([tau_raw])[0])
    base_level = calibrate.baseline_level_for_recall(train["naive_pred"].to_numpy(), y, 0.95)
    base_lr = calibrate.fit_baseline_logistic(train["naive_pred"].to_numpy(), y)

    p50_oof = np.clip(nc + alpha * oof["reg"], FLOOR, hi)
    bundle = Bundle(cutoff=cutoff, features=feats, reg=final["reg"], clf=final["clf"], q10=final["q10"],
                    q90=final["q90"], iso=iso, baseline_lr=base_lr, tau=tau, tau_raw=float(tau_raw),
                    baseline_level=float(base_level), alpha=float(alpha), risk_range=(FLOOR, hi),
                    info={"n_train": int(len(train)), "n_train_high_risk": int(y.sum()),
                          "best_iterations": best, "alpha_oof_scores": {str(a): s for a, s in alpha_scores.items()},
                          "oof_recall_at_tau": metrics.recall(y, oof["clf"] >= tau_raw),
                          "oof_far_at_tau": metrics.false_alarm_rate(y, oof["clf"] >= tau_raw),
                          "oof_kelvins_model": metrics.kelvins_score(t, p50_oof),
                          "oof_kelvins_baseline_clipped": metrics.kelvins_score(t, nc)})
    oof_df = train[["event_key", "is_high_risk", "target_final_risk", "naive_pred"]].copy()
    oof_df["p_raw"], oof_df["p_cal"], oof_df["risk_p50"] = oof["clf"], p_cal_oof, p50_oof
    return bundle, oof_df


# --- persistence -------------------------------------------------------------

def save_bundle(b: Bundle) -> None:
    d = model_dir(b.cutoff)
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(b, d / "bundle.joblib")


def load_bundle(cutoff: float) -> Bundle:
    path = model_dir(cutoff) / "bundle.joblib"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing — run `python -m orbitguard.models`")
    return joblib.load(path)


def write_model_config(bundles: dict[float, Bundle]) -> None:
    cfg = {"high_risk_log10": config.HIGH_RISK_LOG10, "maneuver_p90_log10": config.MANEUVER_P90_LOG10,
           "risk_floor_log10": FLOOR, "cutoffs": {}}
    if config.MODEL_CONFIG_PATH.exists():
        cfg["cutoffs"] = json.loads(config.MODEL_CONFIG_PATH.read_text()).get("cutoffs", {})
    for d, b in bundles.items():
        cfg["cutoffs"][str(int(d))] = {"tau": b.tau, "tau_raw": b.tau_raw, "baseline_level": b.baseline_level, "alpha": b.alpha,
                                       "risk_range": list(b.risk_range), "n_features": len(b.features), **b.info}
    config.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    config.MODEL_CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


# --- prediction --------------------------------------------------------------

def predict(b: Bundle, ev: pd.DataFrame) -> pd.DataFrame:
    X = ev[b.features]
    lo, hi = b.risk_range
    nc = clip_risk(ev["naive_pred"])
    p50 = np.clip(nc + b.alpha * b.reg.predict(X), lo, hi)
    # Enforce P10 <= P50 <= P90 by widening the band around the point estimate. (SPEC says "by sorting",
    # but at long lead times the quantile models can collapse to the floor, and sorting would then drag
    # the point estimate down with them.)
    q10, q90 = np.clip(b.q10.predict(X), lo, hi), np.clip(b.q90.predict(X), lo, hi)
    q = np.column_stack([np.minimum(np.minimum(q10, q90), p50), p50, np.maximum(np.maximum(q10, q90), p50)])
    p_raw = b.clf.predict_proba(X)[:, 1]
    out = pd.DataFrame({
        "event_key": ev["event_key"].to_numpy(),
        "risk_p10": q[:, 0], "risk_p50": q[:, 1], "risk_p90": q[:, 2],
        "p_high_raw": p_raw, "p_high": b.iso.predict(p_raw),
        "naive_pred": ev["naive_pred"].to_numpy(), "naive_clipped": nc,
        "p_baseline": b.baseline_lr.predict_proba(ev[["naive_pred"]].to_numpy())[:, 1],
    })
    out["flag_model"] = out["p_high_raw"] >= b.tau_raw
    out["flag_baseline_95"] = out["naive_pred"] >= b.baseline_level
    if "target_final_risk" in ev:
        out["target_final_risk"] = ev["target_final_risk"].to_numpy()
        out["is_high_risk"] = ev["is_high_risk"].to_numpy()
    return out


def core_table(pred: pd.DataFrame) -> pd.DataFrame:
    """Baseline vs model on the M1 metrics. Rows 1-3 score risk regressions; rows 4-5 score alert flags."""
    t, y = pred["target_final_risk"].to_numpy(), pred["is_high_risk"].to_numpy().astype(bool)
    rows = {}
    for name, risk in (("baseline: latest CDM risk", pred["naive_pred"]),
                       ("baseline: latest CDM, clipped -6.5", pred["naive_clipped"]),
                       ("model: LightGBM regressor (P50)", pred["risk_p50"])):
        r = risk.to_numpy()
        flag = r >= config.HIGH_RISK_LOG10
        rows[name] = {**metrics.kelvins_score(t, r), "recall": metrics.recall(y, flag), "FAR": metrics.false_alarm_rate(y, flag)}
    for name, flag in (("baseline flag @ 95%-recall level", pred["flag_baseline_95"]),
                       ("model classifier @ tau", pred["flag_model"])):
        rows[name] = {"kelvins_score": np.nan, "mse_hr": np.nan, "f2": metrics.fbeta(y, flag),
                      "recall": metrics.recall(y, flag), "FAR": metrics.false_alarm_rate(y, flag)}
    return pd.DataFrame(rows).T


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoffs", type=float, nargs="*", default=config.CUTOFFS_DAYS)
    args = ap.parse_args(argv)
    bundles = {}
    for d in args.cutoffs:
        b, oof = train_cutoff(d)
        save_bundle(b)
        oof.to_parquet(model_dir(d) / "oof.parquet", index=False)
        bundles[d] = b
        ev = features.load_events(d)
        test = ev[ev["split"] == "test"]
        tab = core_table(predict(b, test))
        print(f"\n=== cutoff {d:g} d | TEST events {len(test)} (high-risk {int(test['is_high_risk'].sum())}) "
              f"| tau_raw={b.tau_raw:.4f} (calibrated {b.tau:.4f}) | alpha={b.alpha} | baseline 95% level={b.baseline_level:.2f} ===")
        print(tab.round(4).to_string())
    write_model_config(bundles)
    return 0


if __name__ == "__main__":
    # Run via the imported module so pickled Bundles reference orbitguard.models.Bundle, not __main__.Bundle.
    from orbitguard import models as _models
    raise SystemExit(_models.main())
