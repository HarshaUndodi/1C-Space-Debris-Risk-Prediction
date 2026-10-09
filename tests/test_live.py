"""Live-mode physics: J2 burn propagation agrees with CW; screening helpers behave."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from orbitguard import cw, live, screen


def test_burn_delta_zero_dv_is_zero():
    r0, v0 = np.array([6778.0, 0, 0]), np.array([0, 7.6686, 0])
    d = live.burn_delta(r0, v0, np.zeros(3), 3600)
    assert np.abs(d(np.array([0, 1800, 3600]))).max() < 1e-6


def test_j2_along_track_drift_matches_cw():
    """0.1 m/s along-track burn, 1 day later: two-body+J2 drift ≈ CW's −3·Δv·t (≈ −25.9 km) within 10 %."""
    a = 6778.0
    v = np.sqrt(screen.MU_KM / a)
    r0, v0 = np.array([a, 0, 0]), np.array([0, v * np.cos(0.9), v * np.sin(0.9)])
    B = screen.rtn_basis(r0, v0)
    t = 86400.0
    d = live.burn_delta(r0, v0, B.T @ np.array([0, 1e-4, 0]), t)(t)
    # the RTN frame rotates with the orbit, so compare separation magnitudes (dominated by along-track drift)
    cw_y = cw.displacement_after_burn(np.array([0, 0.1, 0]), cw.mean_motion(a * 1e3), t)[1] / 1e3
    assert np.linalg.norm(d) == pytest.approx(abs(cw_y), rel=0.10)


def test_coarse_gate_covers_fast_crossings():
    assert screen.coarse_gate_km(60) >= 0.5 * 15 * 60
    assert screen.coarse_gate_km(1) == screen.COARSE_KM


def test_assumed_sigmas_grow_with_age():
    s0, s3 = screen.assumed_sigmas_km(0), screen.assumed_sigmas_km(3)
    np.testing.assert_allclose(s0, [0.1, 0.3, 0.1])
    np.testing.assert_allclose(s3, [0.25, 1.2, 0.25])


def test_secondary_check_runs_on_cached_catalog():
    try:
        cat, _ = screen.load_catalog()
    except Exception:
        pytest.skip("no cached catalog")
    prim = next((c for c in cat if c.norad == 25544), None)
    if prim is None:
        pytest.skip("ISS not in cached catalog")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    res = live.secondary_check(cat, prim, now + timedelta(hours=1), np.array([0, 0.5, 0]), now + timedelta(hours=7), ignore=set())
    assert res["applicable"] and isinstance(res["new_conjunctions"], list)
    for c in res["new_conjunctions"]:
        assert c["miss_km"] < live.NEW_CONJ_KM
