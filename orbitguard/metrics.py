"""Metric functions shared by training, evaluation and tests (pure numpy, no I/O)."""
from __future__ import annotations

import numpy as np

from orbitguard import config

HR = config.HIGH_RISK_LOG10


def fbeta(y_true: np.ndarray, y_flag: np.ndarray, beta: float = 2.0) -> float:
    y_true, y_flag = np.asarray(y_true, bool), np.asarray(y_flag, bool)
    tp = np.sum(y_true & y_flag)
    fp = np.sum(~y_true & y_flag)
    fn = np.sum(y_true & ~y_flag)
    denom = (1 + beta ** 2) * tp + beta ** 2 * fn + fp
    return float((1 + beta ** 2) * tp / denom) if denom else 0.0


def recall(y_true, y_flag) -> float:
    y_true, y_flag = np.asarray(y_true, bool), np.asarray(y_flag, bool)
    return float(np.sum(y_true & y_flag) / max(1, np.sum(y_true)))


def precision(y_true, y_flag) -> float:
    y_true, y_flag = np.asarray(y_true, bool), np.asarray(y_flag, bool)
    return float(np.sum(y_true & y_flag) / max(1, np.sum(y_flag)))


def false_alarm_rate(y_true, y_flag) -> float:
    """Fraction of low-risk events that get flagged."""
    y_true, y_flag = np.asarray(y_true, bool), np.asarray(y_flag, bool)
    return float(np.sum(~y_true & y_flag) / max(1, np.sum(~y_true)))


def mse_hr(true_risk, pred_risk) -> float:
    """MSE over events whose TRUE final risk is high (>= -6), as in the Kelvins score."""
    true_risk, pred_risk = np.asarray(true_risk, float), np.asarray(pred_risk, float)
    m = true_risk >= HR
    return float(np.mean((true_risk[m] - pred_risk[m]) ** 2)) if m.any() else float("nan")


def kelvins_score(true_risk, pred_risk) -> dict[str, float]:
    """Official Kelvins score L = MSE_HR / F2 (lower is better). F2 over all events at the -6 boundary."""
    true_risk, pred_risk = np.asarray(true_risk, float), np.asarray(pred_risk, float)
    f2 = fbeta(true_risk >= HR, pred_risk >= HR)
    m = mse_hr(true_risk, pred_risk)
    return {"kelvins_score": float(m / f2) if f2 > 0 else float("inf"), "mse_hr": m, "f2": f2}


def brier(y_true, p) -> float:
    return float(np.mean((np.asarray(p, float) - np.asarray(y_true, float)) ** 2))


def threshold_for_recall(y_true, score, target: float = 0.95) -> float:
    """Largest threshold t such that flagging score >= t gives recall >= target."""
    y_true, score = np.asarray(y_true, bool), np.asarray(score, float)
    pos = np.sort(score[y_true])[::-1]
    if len(pos) == 0:
        return float("inf")
    k = int(np.ceil(target * len(pos)))          # need at least k positives flagged
    return float(pos[k - 1])


def reliability_bins(y_true, p, n_bins: int = 10) -> list[dict]:
    """Quantile-binned reliability diagram (equal-count bins — needed under heavy class imbalance)."""
    y_true, p = np.asarray(y_true, float), np.asarray(p, float)
    order = np.argsort(p, kind="stable")
    out = []
    for chunk in np.array_split(order, n_bins):
        if len(chunk) == 0:
            continue
        out.append({"p_mean": float(p[chunk].mean()), "frac_pos": float(y_true[chunk].mean()),
                    "n": int(len(chunk)), "p_min": float(p[chunk].min()), "p_max": float(p[chunk].max())})
    return out
