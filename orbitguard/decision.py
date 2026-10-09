"""Go / No-Go / Watch logic (SPEC 9.2). Thresholds live in config / model_config.json."""
from __future__ import annotations

from typing import Literal

from orbitguard import config

Decision = Literal["MANEUVER", "WATCH", "HOLD"]


def decide(score: float, p90_risk: float, threshold: float,
           maneuver_p90: float = config.MANEUVER_P90_LOG10) -> Decision:
    """MANEUVER = Go (plan avoidance) · WATCH = high-risk class, monitor · HOLD = No-Go, no action.

    score/threshold: the classifier's raw score and tau_raw. Isotonic calibration is monotone, so
    "raw >= tau_raw" is SPEC's "p_high_calibrated >= tau" with ties broken by the raw score.
    """
    if score >= threshold and p90_risk >= maneuver_p90:
        return "MANEUVER"
    if score >= threshold:
        return "WATCH"
    return "HOLD"
