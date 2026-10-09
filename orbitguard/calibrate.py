"""Module 2b — calibration and threshold selection (SPEC 7.5, 7.6).

All fits use OUT-OF-FOLD predictions on training events (see features.assign_splits for why),
never the test set.
"""
from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from orbitguard import metrics


def fit_isotonic(p_raw: np.ndarray, y: np.ndarray) -> IsotonicRegression:
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(np.asarray(p_raw, float), np.asarray(y, float))
    return iso


def choose_threshold(p_cal: np.ndarray, y: np.ndarray, target_recall: float = 0.95) -> float:
    """Largest tau with recall(p_cal >= tau) >= target_recall."""
    return metrics.threshold_for_recall(y, p_cal, target_recall)


def baseline_level_for_recall(naive_pred: np.ndarray, y: np.ndarray, target_recall: float = 0.95) -> float:
    """Naive-baseline flag level (flag if latest CDM risk >= level) that reaches the same recall."""
    return metrics.threshold_for_recall(y, naive_pred, target_recall)


def fit_baseline_logistic(naive_pred: np.ndarray, y: np.ndarray) -> LogisticRegression:
    """Baseline probability for Brier comparison: logistic fit of the latest CDM risk."""
    lr = LogisticRegression(C=1.0)
    lr.fit(np.asarray(naive_pred, float).reshape(-1, 1), np.asarray(y, int))
    return lr
