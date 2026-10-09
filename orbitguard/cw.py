"""Clohessy–Wiltshire (Hill) linear relative motion about a circular reference orbit — SPEC 10.2.

Frame: x radial (outward), y along-track, z cross-track. State [x, y, z, ẋ, ẏ, ż].
Key intuition: an along-track Δv drifts the satellite along-track as −3·Δv·t, so an EARLIER burn
needs far less propellant for the same separation at TCA.
"""
from __future__ import annotations

import numpy as np

MU_EARTH = 3.986004418e14  # m^3/s^2


def mean_motion(a_m: float) -> float:
    return float(np.sqrt(MU_EARTH / a_m ** 3))


def cw_stm(n: float, t: float) -> np.ndarray:
    """6x6 state-transition matrix Φ(t) of the CW equations."""
    s, c = np.sin(n * t), np.cos(n * t)
    return np.array([
        [4 - 3 * c,        0, 0,      s / n,             2 * (1 - c) / n,          0],
        [6 * (s - n * t),  1, 0,      -2 * (1 - c) / n,  (4 * s - 3 * n * t) / n,  0],
        [0,                0, c,      0,                 0,                        s / n],
        [3 * n * s,        0, 0,      c,                 2 * s,                    0],
        [-6 * n * (1 - c), 0, 0,      -2 * s,            4 * c - 3,                0],
        [0,                0, -n * s, 0,                 0,                        c],
    ])


def displacement_after_burn(dv_rtn: np.ndarray, n: float, t: float) -> np.ndarray:
    """Position offset (m, RTN) at time t after an impulsive Δv (m/s, RTN) from zero initial offset."""
    return cw_stm(n, t)[:3, 3:] @ np.asarray(dv_rtn, float)


def displacement_batch(dv_rtn: np.ndarray, n: float, t: np.ndarray) -> np.ndarray:
    """Vectorised: dv (k,3), t (k,) → (k,3)."""
    t = np.asarray(t, float)
    s, c = np.sin(n * t), np.cos(n * t)
    dvx, dvy, dvz = dv_rtn[:, 0], dv_rtn[:, 1], dv_rtn[:, 2]
    x = s / n * dvx + 2 * (1 - c) / n * dvy
    y = -2 * (1 - c) / n * dvx + (4 * s - 3 * n * t) / n * dvy
    z = s / n * dvz
    return np.column_stack([x, y, z])
