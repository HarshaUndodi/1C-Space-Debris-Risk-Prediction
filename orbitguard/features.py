"""Module 1 — event-level dataset (SPEC Section 6).

One feature row per event, built ONLY from CDMs with time_to_tca >= cutoff (no leakage).
Labels (final risk) use the full CDM series (train) or the official private labels (test).

Run: python -m orbitguard.features            # builds data/processed/events_cutoff{2,3,4,5,7}.parquet
"""
from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd

from orbitguard import config, download

log = logging.getLogger("orbitguard.features")

OBJECT_TYPES = ["DEBRIS", "PAYLOAD", "ROCKET BODY", "UNKNOWN", "TBA"]
TREND_COLS = ["risk", "miss_distance", "max_risk_estimate",
              "t_sigma_r", "t_sigma_t", "t_sigma_n", "c_sigma_r", "c_sigma_t", "c_sigma_n"]
META_COLS = ["event_key", "event_id", "dataset", "mission_id", "split", "fold",
             "target_final_risk", "is_high_risk", "naive_pred", "final_time_to_tca"]


# --- loading -----------------------------------------------------------------

def load_kelvins() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (train CDMs, test CDMs, test labels). Test labels come from test_data_private.csv."""
    files = download.kelvins_files()
    if not (files["train"] and files["test"]):
        raise FileNotFoundError(download.KELVINS_MANUAL_MSG)
    train = pd.read_csv(files["train"])
    test = pd.read_csv(files["test"])
    private = None
    for p in config.KELVINS_DIR.rglob("*private*.csv"):
        private = pd.read_csv(p)
        break
    if private is None:
        # SPEC 5.1: if test ground truth is missing, test events are carved from train instead.
        log.warning("no test_data_private.csv — test labels unavailable; carving test set from train")
        labels = pd.DataFrame(columns=["event_id", "true_risk", "time_to_tca"])
    else:
        labels = private[["event_id", "true_risk", "time_to_tca"]].copy()
    return train, test, labels


def risk_range(train: pd.DataFrame) -> tuple[float, float]:
    """Observed log10 PoC range; all predictions are clipped to it (SPEC 5.1)."""
    return float(train["risk"].min()), float(train["risk"].max())


# --- feature builder ---------------------------------------------------------

def _slope(inputs: pd.DataFrame) -> pd.Series:
    """Least-squares slope of risk vs time_to_tca per event (NaN if < 2 CDMs or no spread in time)."""
    x, y = inputs["time_to_tca"], inputs["risk"]
    s = pd.DataFrame({"event_id": inputs["event_id"], "x": x, "y": y, "xx": x * x, "xy": x * y})
    agg = s.groupby("event_id").agg(n=("x", "size"), sx=("x", "sum"), sy=("y", "sum"), sxx=("xx", "sum"), sxy=("xy", "sum"))
    denom = agg.n * agg.sxx - agg.sx ** 2
    slope = (agg.n * agg.sxy - agg.sx * agg.sy) / denom.where(denom.abs() > 1e-12)
    slope[agg.n < 2] = np.nan
    return slope


def build_event_table(cdm_df: pd.DataFrame, cutoff_days: float = config.DEFAULT_CUTOFF_DAYS, *,
                      labels: pd.DataFrame | None = None, dataset: str = "train",
                      require_last_lt1: bool = True) -> pd.DataFrame:
    """One row per event using only CDMs with time_to_tca >= cutoff_days.

    labels: optional (event_id, true_risk, time_to_tca) table giving the final risk (Kelvins test set).
            Without it the label is the risk of the CDM with the smallest time_to_tca.
    require_last_lt1: training filter — keep events whose final CDM is < 1 day from TCA.
    """
    df = cdm_df.sort_values(["event_id", "time_to_tca"], ascending=[True, False]).reset_index(drop=True)

    # Label (uses the whole series — label only, never a feature).
    if labels is not None and len(labels):
        lab = labels.set_index("event_id")
        target = lab["true_risk"].rename("target_final_risk")
        final_t = lab["time_to_tca"].rename("final_time_to_tca")
    else:
        last_all = df.groupby("event_id").tail(1).set_index("event_id")
        target = last_all["risk"].rename("target_final_risk")
        final_t = last_all["time_to_tca"].rename("final_time_to_tca")

    inputs = df[df["time_to_tca"] >= cutoff_days]
    if inputs.empty:
        return pd.DataFrame()
    g = inputs.groupby("event_id")
    last = g.tail(1).set_index("event_id")             # tail() keeps NaNs (unlike .last())
    prev = g.nth(-2).set_index("event_id")
    first = g.head(1).set_index("event_id")

    numeric = [c for c in df.columns if c not in ("event_id", "c_object_type") and pd.api.types.is_numeric_dtype(df[c])]
    new: dict[str, pd.Series] = {}
    for c in TREND_COLS:
        new[f"delta_{c}"] = last[c] - prev[c].reindex(last.index)   # NaN for single-CDM events
    new["slope_risk"] = _slope(inputs)
    agg = g["risk"].agg(["size", "max", "min", "mean", "std"])
    new["n_cdms"] = agg["size"]
    for k in ("max", "min", "mean", "std"):
        new[f"risk_{k}"] = agg[k]
    new["span_days"] = first["time_to_tca"] - last["time_to_tca"]
    # last_time_to_tca comes from the numeric block; space weather is last_F10 / last_F3M / last_AP / last_SSN.

    # Geometry: combined 1-sigma per RTN axis and a diagonal Mahalanobis-style miss distance.
    for ax in "rtn":
        new[f"combined_sigma_{ax}"] = np.sqrt(last[f"t_sigma_{ax}"] ** 2 + last[f"c_sigma_{ax}"] ** 2)
    new["mahalanobis_proxy"] = np.sqrt(sum(
        (last[f"relative_position_{ax}"] / new[f"combined_sigma_{ax}"]) ** 2 for ax in "rtn"))
    new["log10_miss_distance"] = np.log10(last["miss_distance"].clip(lower=1e-3))
    for side in "tc":
        for ax in "rtn":
            new[f"log10_{side}_sigma_{ax}"] = np.log10(last[f"{side}_sigma_{ax}"].clip(lower=1e-6))
    new["c_object_type"] = pd.Series(pd.Categorical(last["c_object_type"].fillna("UNKNOWN"), categories=OBJECT_TYPES),
                                     index=last.index)

    new["naive_pred"] = last["risk"]
    new["mission_id"] = last["mission_id"]
    new["target_final_risk"] = target.reindex(last.index)
    new["final_time_to_tca"] = final_t.reindex(last.index)
    out = pd.concat([last[numeric].add_prefix("last_"), pd.DataFrame(new, index=last.index)], axis=1)
    out = out[out["target_final_risk"].notna()]
    if require_last_lt1:
        out = out[out["final_time_to_tca"] < 1.0]
    out = out.copy()
    out["is_high_risk"] = (out["target_final_risk"] >= config.HIGH_RISK_LOG10).astype(int)
    out["dataset"] = dataset
    out = out.reset_index().rename(columns={"index": "event_id"})
    out["event_key"] = dataset + "_" + out["event_id"].astype(str)
    return out


def feature_columns(events: pd.DataFrame) -> list[str]:
    return [c for c in events.columns if c not in META_COLS and c != "last_mission_id"]


# --- splits ------------------------------------------------------------------

def assign_splits(train_events: pd.DataFrame, seed: int = config.SEED, n_folds: int = config.N_FOLDS,
                  test_frac: float = 0.0) -> tuple[dict[str, str], dict[str, int]]:
    """Event-level splits, stratified on is_high_risk (each class shuffled and dealt out separately).

    Returns ({event_key: split}, {event_key: fold}). split is "train" (or "test" when test_frac > 0,
    i.e. when the Kelvins test labels are unavailable). Every train event gets a fold 0..n_folds-1.

    Deviation from SPEC 7.5 (documented): the cutoff-2 training set holds only ~66 high-risk events,
    so a single 20 % validation split leaves ~7 positives for calibration — too few to set a 95 %-recall
    threshold. Instead each event's validation prediction comes from the fold model that did NOT train
    on it (out-of-fold), and calibration + threshold use all of them. Grouping is still by event.
    """
    rng = np.random.default_rng(seed)
    split: dict[str, str] = {}
    fold: dict[str, int] = {}
    for _, grp in train_events.groupby("is_high_risk"):
        keys = np.array(sorted(grp["event_key"]))
        rng.shuffle(keys)
        n_test = int(round(len(keys) * test_frac))
        split.update({k: "test" for k in keys[:n_test]})
        for i, k in enumerate(keys[n_test:]):
            split[k] = "train"
            fold[k] = i % n_folds
    return split, fold


def build_all(cutoffs: list[float] | None = None) -> dict[float, pd.DataFrame]:
    """Build and save event tables for every cutoff with ONE fixed split assignment across cutoffs."""
    cutoffs = cutoffs or config.CUTOFFS_DAYS
    train_cdm, test_cdm, labels = load_kelvins()
    lo, hi = risk_range(train_cdm)
    have_test_labels = len(labels) > 0

    # Splits are assigned once, from the cutoff-2 eligible training events, and reused for every cutoff.
    base = build_event_table(train_cdm, min(cutoffs), dataset="train")
    split_map, fold_map = assign_splits(base, test_frac=0.0 if have_test_labels else 0.15)

    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    tables = {}
    for d in cutoffs:
        tr = build_event_table(train_cdm, d, dataset="train")
        tr["split"] = tr["event_key"].map(split_map)
        tr["fold"] = tr["event_key"].map(fold_map).fillna(-1).astype(int)
        tr = tr[tr["split"].notna()]  # events not eligible at the base cutoff can't appear later
        parts = [tr]
        if have_test_labels:
            te = build_event_table(test_cdm, d, labels=labels, dataset="test", require_last_lt1=False)
            te["split"] = "test"
            te["fold"] = -1
            parts.append(te)
        ev = pd.concat(parts, ignore_index=True)
        ev["c_object_type"] = pd.Categorical(ev["c_object_type"], categories=OBJECT_TYPES)
        ev.attrs["risk_range"] = (lo, hi)
        path = config.PROCESSED_DIR / f"events_cutoff{int(d)}.parquet"
        ev.to_parquet(path, index=False)
        counts = ev.groupby("split")["is_high_risk"].agg(["size", "sum"])
        log.info("cutoff %s: %d events -> %s\n%s", d, len(ev), path.name, counts.to_string())
        tables[d] = ev
    return tables


def load_events(cutoff: float) -> pd.DataFrame:
    path = config.PROCESSED_DIR / f"events_cutoff{int(cutoff)}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing — run `python -m orbitguard.features` first")
    ev = pd.read_parquet(path)
    ev["c_object_type"] = pd.Categorical(ev["c_object_type"], categories=OBJECT_TYPES)
    return ev


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoffs", type=float, nargs="*", default=None)
    args = ap.parse_args(argv)
    build_all(args.cutoffs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
