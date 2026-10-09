"""SPEC 14.1–14.4 — Pc engine, Clohessy–Wiltshire, maneuver monotonicity."""
import numpy as np
import pytest

from orbitguard import cw, maneuver, pc


@pytest.mark.parametrize("sigma,R", [(100.0, 5.0), (10.0, 10.0)])
def test_pc_centred_isotropic_closed_form(sigma, R):
    """μ = 0, Σ = σ²I  →  Pc = 1 − exp(−R² / 2σ²)."""
    got = pc.pc_2d(np.zeros(2), sigma ** 2 * np.eye(2), R)
    want = 1.0 - np.exp(-R ** 2 / (2 * sigma ** 2))
    assert got == pytest.approx(want, rel=1e-3)


def test_pc_far_miss_is_negligible():
    assert pc.pc_2d(np.array([10_000.0, 0.0]), 50.0 ** 2 * np.eye(2), 10.0) < 1e-20


def test_pc_full_3d_pipeline_matches_2d_for_isotropic_case():
    """collision_probability with isotropic 3D covariances reduces to the 2D closed form."""
    s = 30.0
    cov = (s ** 2 / 2) * np.eye(3)          # two objects → combined σ² = s²
    p, lp = pc.collision_probability(np.array([0.0, 0.0, 0.0]), np.array([0.0, -14000.0, 100.0]), cov, cov, 5.0)
    assert p == pytest.approx(1 - np.exp(-25 / (2 * s ** 2)), rel=1e-3)
    assert lp == pytest.approx(np.log10(p))


def test_cw_identity_and_along_track_drift():
    n = cw.mean_motion(6_778e3)
    np.testing.assert_allclose(cw.cw_stm(n, 0.0), np.eye(6), atol=1e-12)
    dv, t = 0.1, 86_400.0
    d = cw.displacement_after_burn(np.array([0.0, dv, 0.0]), n, t)
    assert d[1] == pytest.approx(-3 * dv * t, rel=0.02)          # ≈ −25.9 km after one day


def test_cw_special_cases_match_stm():
    n, t = cw.mean_motion(7_000e3), 5_000.0
    s, c = np.sin(n * t), np.cos(n * t)
    along = cw.displacement_after_burn(np.array([0.0, 1.0, 0.0]), n, t)
    radial = cw.displacement_after_burn(np.array([1.0, 0.0, 0.0]), n, t)
    cross = cw.displacement_after_burn(np.array([0.0, 0.0, 1.0]), n, t)
    np.testing.assert_allclose(along[:2], [(2 / n) * (1 - c), 4 * s / n - 3 * t])
    np.testing.assert_allclose(radial[:2], [s / n, (2 / n) * (c - 1)])
    assert cross[2] == pytest.approx(s / n)
    batch = cw.displacement_batch(np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0]]), n, np.array([t, t]))
    np.testing.assert_allclose(batch, np.vstack([along, radial]))


def head_on_event():
    """Synthetic head-on conjunction: 20 m radial miss, 14 km/s closing along-track, 100 m sigmas."""
    cov = np.diag([100.0 ** 2, 300.0 ** 2, 100.0 ** 2])
    return {"r": np.array([20.0, 0.0, 10.0]), "v": np.array([0.0, -14_000.0, 50.0]),
            "cov_t": cov, "cov_c": cov, "radius": 10.0, "sma_km": 6_878.0}


def test_maneuver_pareto_monotone_and_target_met():
    res = maneuver.search_maneuvers(head_on_event(), time_to_tca_h=72, target_pc=1e-6)
    front = [p["post_pc"] for p in res["pareto"]]
    assert all(b <= a * (1 + 1e-9) for a, b in zip(front, front[1:])), "larger Δv increased best Pc"
    assert res["pre_burn_pc"] > 1e-4
    assert res["target_met"] and res["recommended"]["post_pc"] <= 1e-6
    assert res["recommended"]["propellant_g"] > 0
    assert len(res["points"]) == 40 * 4 * 6


def test_maneuver_skips_burns_in_the_past():
    res = maneuver.search_maneuvers(head_on_event(), time_to_tca_h=30)
    assert max(p["burn_lead_h"] for p in res["points"]) <= 30


def test_propellant_rocket_equation():
    # 0.12 m/s on 500 kg at Isp 220 s ≈ 27.8 g
    assert maneuver.propellant_g(0.12) == pytest.approx(27.8, abs=0.1)
