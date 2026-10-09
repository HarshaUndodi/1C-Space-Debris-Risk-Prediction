"""Module 3 — evaluation on the held-out Kelvins test set (SPEC Section 8).

Writes artifacts/metrics.json (merging: keys owned by other modules, e.g. "screening" and
"pc_validation", are preserved) and plots to artifacts/plots/.

Run: python -m orbitguard.evaluate
"""
from __future__ import annotations

import json
import logging
import warnings
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score  # noqa: E402

from orbitguard import config, explain, features, metrics, models  # noqa: E402

log = logging.getLogger("orbitguard.evaluate")
warnings.filterwarnings("ignore", message="X does not have valid feature names")
HR = config.HIGH_RISK_LOG10


def _r(x, n=4):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


def load_metrics() -> dict:
    try:
        return json.loads(config.METRICS_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_metrics(update: dict) -> dict:
    """Merge `update` into metrics.json (top-level keys) and write it."""
    m = load_metrics()
    m.update(update)
    config.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    config.METRICS_PATH.write_text(json.dumps(m, indent=2))
    return m


def test_predictions(cutoff: float) -> tuple[models.Bundle, pd.DataFrame, pd.DataFrame]:
    b = models.load_bundle(cutoff)
    ev = features.load_events(cutoff)
    te = ev[ev["split"] == "test"].reset_index(drop=True)
    return b, te, models.predict(b, te)


def headline(b: models.Bundle, p: pd.DataFrame) -> dict:
    t = p["target_final_risk"].to_numpy()
    y = p["is_high_risk"].to_numpy().astype(bool)
    naive, naive_c, p50 = p["naive_pred"].to_numpy(), p["naive_clipped"].to_numpy(), p["risk_p50"].to_numpy()
    flag_m, flag_b95 = p["flag_model"].to_numpy(), p["flag_baseline_95"].to_numpy()

    base = metrics.kelvins_score(t, naive)
    base_flag = naive >= HR
    baseline = {"kelvins_score": base["kelvins_score"], "mse_hr": base["mse_hr"], "f2": base["f2"],
                "recall": metrics.recall(y, base_flag), "false_alarm_rate": metrics.false_alarm_rate(y, base_flag),
                "brier": metrics.brier(y, p["p_baseline"])}
    bc = metrics.kelvins_score(t, naive_c)
    m = metrics.kelvins_score(t, p50)
    t_floor = np.maximum(t, config.RISK_FLOOR_LOG10)
    model = {"kelvins_score": m["kelvins_score"], "mse_hr": m["mse_hr"], "f2": m["f2"],
             "recall": metrics.recall(y, flag_m), "false_alarm_rate": metrics.false_alarm_rate(y, flag_m),
             "precision": metrics.precision(y, flag_m), "f2_at_tau": metrics.fbeta(y, flag_m),
             "brier": metrics.brier(y, p["p_high"]), "brier_uncalibrated": metrics.brier(y, p["p_high_raw"]),
             "band_coverage_p10_p90": float(np.mean((t_floor >= p["risk_p10"]) & (t_floor <= p["risk_p90"]))),
             "threshold": b.tau, "threshold_raw": b.tau_raw}
    far_at = {}
    for r in (0.9, 0.94, 0.95, 0.97, 1.0):
        tm = metrics.threshold_for_recall(y, p["p_high_raw"].to_numpy(), r)
        tb = metrics.threshold_for_recall(y, naive, r)
        far_at[str(r)] = {"model": metrics.false_alarm_rate(y, p["p_high_raw"] >= tm),
                          "baseline": metrics.false_alarm_rate(y, naive >= tb)}
    return {
        "baseline": {k: _r(v) for k, v in baseline.items()},
        "baseline_clipped": {k: _r(v) for k, v in bc.items()},
        "baseline_at_95_recall_level": {"level_log10": _r(b.baseline_level), "recall": _r(metrics.recall(y, flag_b95)),
                                        "false_alarm_rate": _r(metrics.false_alarm_rate(y, flag_b95)),
                                        "f2": _r(metrics.fbeta(y, flag_b95))},
        "model": {k: _r(v) for k, v in model.items()},
        "ranking": {"auc_pr_model": _r(average_precision_score(y, p["p_high_raw"])),
                    "auc_pr_baseline": _r(average_precision_score(y, naive)),
                    "roc_auc_model": _r(roc_auc_score(y, p["p_high_raw"])),
                    "roc_auc_baseline": _r(roc_auc_score(y, naive)),
                    "far_at_recall_diagnostic": {k: {kk: _r(vv) for kk, vv in v.items()} for k, v in far_at.items()}},
        "reliability": {"model_calibrated": metrics.reliability_bins(y, p["p_high"]),
                        "model_uncalibrated": metrics.reliability_bins(y, p["p_high_raw"]),
                        "baseline_logistic": metrics.reliability_bins(y, p["p_baseline"])},
    }


def lead_time() -> list[dict]:
    """Recall/F2 per cutoff over ALL cutoff-2 test events: an event with no CDM yet at cutoff d counts as
    not flagged (you cannot flag what you have not seen). Baseline = its own 95%-recall level per cutoff."""
    _, te2, _ = test_predictions(2)
    universe = te2[["event_key", "is_high_risk"]]
    y = universe["is_high_risk"].to_numpy().astype(bool)
    out = []
    for d in config.CUTOFFS_DAYS:
        _, _, p = test_predictions(d)
        j = universe.merge(p[["event_key", "flag_model", "flag_baseline_95", "naive_pred"]], on="event_key", how="left")
        fm = j["flag_model"].fillna(False).to_numpy().astype(bool)
        fb = j["flag_baseline_95"].fillna(False).to_numpy().astype(bool)
        f6 = (j["naive_pred"].fillna(-99) >= HR).to_numpy()
        out.append({"cutoff_days": d, "n_available": int(len(p)),
                    "model_recall": _r(metrics.recall(y, fm)), "baseline_recall": _r(metrics.recall(y, fb)),
                    "model_f2": _r(metrics.fbeta(y, fm)), "baseline_f2": _r(metrics.fbeta(y, fb)),
                    "model_far": _r(metrics.false_alarm_rate(y, fm)), "baseline_far": _r(metrics.false_alarm_rate(y, fb)),
                    "baseline_minus6_recall": _r(metrics.recall(y, f6)), "baseline_minus6_far": _r(metrics.false_alarm_rate(y, f6))})
    return out


# --- plots ---------------------------------------------------------------------

def _style():
    plt.rcParams.update({"figure.dpi": 130, "axes.grid": True, "grid.alpha": 0.3, "font.size": 10})


def plot_reliability(rel: dict, path):
    _style()
    fig, ax = plt.subplots(figsize=(5, 4.5))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
    for key, lbl, c in (("model_calibrated", "model (isotonic)", "#0d9488"),
                        ("model_uncalibrated", "model (raw)", "#94a3b8"),
                        ("baseline_logistic", "baseline (logistic of latest risk)", "#f59e0b")):
        b = rel[key]
        ax.plot([x["p_mean"] for x in b], [x["frac_pos"] for x in b], "o-", color=c, label=lbl)
    ax.set(xlabel="predicted P(high risk)", ylabel="observed frequency", title="Reliability (test, 10 quantile bins)",
           xscale="symlog", xlim=(0, 1), ylim=(-0.02, 1.02))
    ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def plot_lead_time(lt: list[dict], path):
    _style()
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.8))
    d = [x["cutoff_days"] for x in lt]
    ax[0].plot(d, [x["model_recall"] for x in lt], "o-", color="#0d9488", label="model @ tau")
    ax[0].plot(d, [x["baseline_recall"] for x in lt], "s--", color="#f59e0b", label="baseline @ 95% level")
    ax[0].set(xlabel="days before TCA (feature cutoff)", ylabel="recall (high-risk)", ylim=(0, 1.05), title="Recall")
    ax[1].plot(d, [x["model_far"] for x in lt], "o-", color="#0d9488", label="model @ tau")
    ax[1].plot(d, [x["baseline_far"] for x in lt], "s--", color="#f59e0b", label="baseline @ 95% level")
    ax[1].set(xlabel="days before TCA (feature cutoff)", ylabel="false-alarm rate", ylim=(0, 1.05), title="False alarms")
    for a in ax:
        a.invert_xaxis(); a.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def plot_shap(imp: pd.Series, path, k: int = 15):
    _style()
    top = imp.head(k)[::-1]
    fig, ax = plt.subplots(figsize=(6.5, 5))
    ax.barh([explain.label(f) for f in top.index], top.values, color="#0d9488")
    ax.set(xlabel="mean |SHAP| (log-odds, classifier)", title="Global feature importance (test)")
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def plot_pr(y, s_model, s_base, path):
    _style()
    fig, ax = plt.subplots(figsize=(5, 4.5))
    for s, lbl, c in ((s_model, "model", "#0d9488"), (s_base, "baseline (latest risk)", "#f59e0b")):
        pr, rc, _ = precision_recall_curve(y, s)
        ax.plot(rc, pr, color=c, label=f"{lbl} AP={average_precision_score(y, s):.3f}")
    ax.axvline(0.95, color="k", ls=":", lw=1)
    ax.set(xlabel="recall", ylabel="precision", title="Precision-recall (test)")
    ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config.PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    b, te, p = test_predictions(2)
    y = p["is_high_risk"].to_numpy()
    h = headline(b, p)
    lt = lead_time()
    imp = explain.global_importance(b.clf, te[b.features], b.features)
    train_hr = json.loads(config.MODEL_CONFIG_PATH.read_text())["cutoffs"]["2"]
    update = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cutoff_days": 2,
        "n_test_events": int(len(p)),
        "n_test_high_risk": int(y.sum()),
        "n_train_events": train_hr["n_train"],
        "n_train_high_risk": train_hr["n_train_high_risk"],
        **h,
        "lead_time": lt,
        "shap_global": [{"feature": f, "label": explain.label(f), "mean_abs_shap": _r(v)} for f, v in imp.head(15).items()],
        "notes": [
            "Held-out test = official Kelvins test set (labels from test_data_private.csv); never used for any choice.",
            "Test is hand-picked to over-represent high-risk events (6.9% vs 0.8% in training), so calibrated "
            "probabilities (fitted on training prevalence) read low on test; see reliability diagram.",
            "baseline = latest CDM risk (Kelvins naive). baseline_clipped = same, floored at -6.5: this alone "
            "beats our regressor on the Kelvins score.",
            "model recall/false_alarm_rate are at tau, chosen out-of-fold on training data for >=95% recall.",
            "Band coverage is measured against the true final risk floored at -6.5 (risks below the floor are "
            "reported as '< 1 in 3.2 million').",
            f"Lead-time cutoffs {config.CUTOFFS_DAYS}: Kelvins CDMs start < 7 days before TCA, so 6 replaces 7.",
        ],
    }
    update.setdefault("screening", load_metrics().get("screening", {"objects": 0, "hours": 72, "step_s": 60, "seconds": 0.0}))
    save_metrics(update)
    plot_reliability(h["reliability"], config.PLOTS_DIR / "reliability.png")
    plot_lead_time(lt, config.PLOTS_DIR / "lead_time.png")
    plot_shap(imp, config.PLOTS_DIR / "shap_global.png")
    plot_pr(y, p["p_high_raw"], p["naive_pred"], config.PLOTS_DIR / "pr_curve.png")

    print(f"test events {len(p)} (high-risk {int(y.sum())})")
    print(pd.DataFrame({k: h[k] for k in ("baseline", "baseline_clipped", "model")}).T.to_string())
    print(pd.DataFrame(lt).to_string(index=False))
    print("ranking:", {k: v for k, v in h["ranking"].items() if k != "far_at_recall_diagnostic"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
