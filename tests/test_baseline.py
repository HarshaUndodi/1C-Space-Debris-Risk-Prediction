"""SPEC 14.6 — the naive baseline's Kelvins score is finite and recomputable; metric functions are correct."""
import math

import numpy as np
import pytest

from orbitguard import config, features, metrics


def test_kelvins_score_hand_example():
    true = np.array([-5.0, -4.0, -10.0, -30.0])
    pred = np.array([-5.5, -7.0, -10.0, -5.0])
    # HR events: idx 0, 1 → MSE_HR = (0.25 + 9) / 2
    # flags: pred>=-6 → [T, F, F, T]; truth → [T, T, F, F]: tp=1, fn=1, fp=1 → F2 = 5/(5+4+1) = 0.5
    k = metrics.kelvins_score(true, pred)
    assert k["mse_hr"] == pytest.approx(4.625)
    assert k["f2"] == pytest.approx(0.5)
    assert k["kelvins_score"] == pytest.approx(9.25)


def test_threshold_for_recall():
    y = np.array([1, 1, 1, 1, 0, 0])
    s = np.array([0.9, 0.8, 0.3, 0.2, 0.5, 0.1])
    assert metrics.threshold_for_recall(y, s, 0.75) == pytest.approx(0.3)
    assert metrics.recall(y, s >= 0.3) >= 0.75
    assert metrics.threshold_for_recall(y, s, 1.0) == pytest.approx(0.2)


def test_baseline_score_on_training_events_finite_and_recomputable():
    path = config.PROCESSED_DIR / "events_cutoff2.parquet"
    if not path.exists():
        pytest.skip("processed event tables not built")
    ev = features.load_events(2)
    tr = ev[ev["split"] == "train"]
    a = metrics.kelvins_score(tr["target_final_risk"], tr["naive_pred"])
    b = metrics.kelvins_score(tr["target_final_risk"].to_numpy(), tr["naive_pred"].to_numpy())
    assert math.isfinite(a["kelvins_score"]) and a == b
    clipped = metrics.kelvins_score(tr["target_final_risk"], np.maximum(tr["naive_pred"], config.RISK_FLOOR_LOG10))
    assert math.isfinite(clipped["kelvins_score"])
