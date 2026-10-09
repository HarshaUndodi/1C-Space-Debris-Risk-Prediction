"""SPEC 14.5 — no leakage: features use only CDMs with time_to_tca >= cutoff; splits are disjoint by event."""
import numpy as np
import pandas as pd
import pytest

from orbitguard import config, features


def synthetic_cdms(n_events=40, seed=0) -> pd.DataFrame:
    """Minimal Kelvins-shaped CDM table: every column features.py touches."""
    rng = np.random.default_rng(seed)
    rows = []
    for e in range(n_events):
        times = np.sort(rng.uniform(0.05, 6.9, size=rng.integers(1, 12)))[::-1]
        for t in times:
            row = {"event_id": e, "mission_id": e % 3, "time_to_tca": t, "risk": rng.uniform(-30, -3),
                   "max_risk_estimate": rng.uniform(-20, -2), "miss_distance": rng.uniform(10, 5e4),
                   "c_object_type": rng.choice(["DEBRIS", "PAYLOAD", "UNKNOWN"]),
                   "F10": 150.0, "F3M": 140.0, "AP": 10.0, "SSN": 80.0}
            for side in "tc":
                for ax in "rtn":
                    row[f"{side}_sigma_{ax}"] = rng.uniform(1, 1000)
            for ax in "rtn":
                row[f"relative_position_{ax}"] = rng.normal(0, 1000)
            rows.append(row)
    return pd.DataFrame(rows)


@pytest.mark.parametrize("cutoff", [2.0, 3.0, 5.0])
def test_features_ignore_cdms_after_cutoff(cutoff):
    """Scrambling every CDM with time_to_tca < cutoff must not change any feature (only the label)."""
    cdm = synthetic_cdms()
    a = features.build_event_table(cdm, cutoff, require_last_lt1=False)
    late = cdm["time_to_tca"] < cutoff
    scrambled = cdm.copy()
    rng = np.random.default_rng(1)
    for c in ["risk", "max_risk_estimate", "miss_distance", "c_sigma_r", "t_sigma_t", "relative_position_r", "F10"]:
        scrambled.loc[late, c] = rng.uniform(-1e3, 1e3, size=late.sum())
    b = features.build_event_table(scrambled, cutoff, require_last_lt1=False)
    cols = features.feature_columns(a)
    assert list(a["event_key"]) == list(b["event_key"])
    pd.testing.assert_frame_equal(a[cols].reset_index(drop=True), b[cols].reset_index(drop=True))
    assert (a["last_time_to_tca"] >= cutoff).all()


def test_label_is_final_cdm_risk():
    cdm = synthetic_cdms()
    ev = features.build_event_table(cdm, 2.0, require_last_lt1=False).set_index("event_id")
    final = cdm.sort_values("time_to_tca").groupby("event_id").first()["risk"]
    np.testing.assert_allclose(ev["target_final_risk"], final.reindex(ev.index))


def test_splits_are_disjoint_and_stratified():
    cdm = synthetic_cdms(n_events=200)
    ev = features.build_event_table(cdm, 2.0, require_last_lt1=False)
    split, fold = features.assign_splits(ev, test_frac=0.15)
    assert set(split) == set(ev["event_key"])           # each event exactly one split (dict keys)
    assert set(fold) == {k for k, s in split.items() if s == "train"}
    assert set(fold.values()) <= set(range(config.N_FOLDS))


def _processed(cutoff):
    path = config.PROCESSED_DIR / f"events_cutoff{int(cutoff)}.parquet"
    if not path.exists():
        pytest.skip("processed event tables not built (python -m orbitguard.features)")
    return features.load_events(cutoff)


@pytest.mark.parametrize("cutoff", config.CUTOFFS_DAYS)
def test_real_tables_respect_cutoff_and_splits(cutoff):
    ev = _processed(cutoff)
    assert (ev["last_time_to_tca"] >= cutoff).all(), "a feature row used a CDM after the cutoff"
    assert ev["event_key"].is_unique
    assert ev.groupby("event_key")["split"].nunique().max() == 1
    train, test = ev[ev["split"] == "train"], ev[ev["split"] == "test"]
    assert set(train["event_key"]).isdisjoint(test["event_key"])
    assert set(train["fold"]) <= set(range(config.N_FOLDS)) and (test["fold"] == -1).all()


def test_split_assignment_identical_across_cutoffs():
    base = _processed(2).set_index("event_key")
    for d in config.CUTOFFS_DAYS[1:]:
        other = _processed(d).set_index("event_key")
        common = base.index.intersection(other.index)
        assert (base.loc[common, "split"] == other.loc[common, "split"]).all()
        assert (base.loc[common, "fold"] == other.loc[common, "fold"]).all()
