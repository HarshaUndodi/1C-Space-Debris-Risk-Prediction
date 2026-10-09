"""models.predict invariants: P50 is the regressor's point estimate and the band always contains it."""
import numpy as np
import pandas as pd

from orbitguard import models


class Const:
    def __init__(self, v):
        self.v = v

    def predict(self, X, **_):
        return np.full(len(X), self.v, dtype=float)


class Clf:
    def predict_proba(self, X):
        return np.column_stack([np.full(len(X), 0.9), np.full(len(X), 0.1)])


class Ident:
    def predict(self, p):
        return np.asarray(p, float)

    def predict_proba(self, X):
        return np.column_stack([np.full(len(X), 0.5), np.full(len(X), 0.5)])


def bundle(q10, q90, resid=0.0):
    return models.Bundle(cutoff=2, features=["f"], reg=Const(resid), clf=Clf(), q10=Const(q10), q90=Const(q90),
                         iso=Ident(), baseline_lr=Ident(), tau=0.1, tau_raw=0.1, baseline_level=-10, alpha=1.0,
                         risk_range=(-6.5, -1.0))


def events():
    return pd.DataFrame({"f": [0.0, 0.0], "naive_pred": [-3.7, -30.0], "event_key": ["a", "b"]})


def test_collapsed_quantiles_do_not_drag_p50():
    p = models.predict(bundle(q10=-6.5, q90=-6.5), events())
    np.testing.assert_allclose(p["risk_p50"], [-3.7, -6.5])          # regressor (+ floored naive) kept
    assert (p["risk_p10"] <= p["risk_p50"]).all() and (p["risk_p50"] <= p["risk_p90"]).all()


def test_crossed_quantiles_are_reordered_around_p50():
    p = models.predict(bundle(q10=-3.0, q90=-5.0), events())
    assert (p["risk_p10"] <= p["risk_p50"]).all() and (p["risk_p50"] <= p["risk_p90"]).all()
    assert p["risk_p90"].iloc[0] == -3.0 and p["risk_p10"].iloc[0] == -5.0
