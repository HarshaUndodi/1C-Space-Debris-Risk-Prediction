"""Precompute ~30 held-out Kelvins test events for the dashboard → artifacts/demo_events.json (SPEC 13).

Selection (from cutoff-2 test predictions): high-risk events the model catches, a few it misses, a few
false alarms and a set of correctly-held low-risk events. For every cutoff at which the event has CDMs:
prediction, decision, SHAP top-5, briefing and maneuver search. The API serves this file as-is.

Run: python -m orbitguard.build_demo [--no-llm]
"""
from __future__ import annotations

import argparse
import json
import logging
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from orbitguard import config, decision, explain, features, maneuver, models, pc

log = logging.getLogger("orbitguard.build_demo")
warnings.filterwarnings("ignore", message="X does not have valid feature names")

N_CAUGHT, N_MISSED, N_FALSE_ALARM, N_HOLD = 12, 3, 5, 10


def _f(x, n=4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, n) if np.isfinite(x) else None


def select_events(p2: pd.DataFrame, rng: np.random.Generator) -> list[str]:
    hr = p2["is_high_risk"] == 1
    flagged = p2["flag_model"]
    # every MANEUVER-decision event first (they are rare: P90 >= 1e-4), then caught events across severities
    maneuver_keys = list(p2[flagged & (p2["risk_p90"] >= config.MANEUVER_P90_LOG10)]
                         .sort_values("p_high_raw", ascending=False)["event_key"].head(8))
    caught = p2[hr & flagged & ~p2["event_key"].isin(maneuver_keys)].sort_values("target_final_risk", ascending=False)
    n_more = max(0, N_CAUGHT - len(maneuver_keys))
    idx = np.unique(np.linspace(0, len(caught) - 1, min(n_more, len(caught))).round().astype(int))
    picks = maneuver_keys + list(caught.iloc[idx]["event_key"])
    picks += list(p2[hr & ~p2["flag_model"]].sort_values("target_final_risk", ascending=False)["event_key"].head(N_MISSED))
    fa = p2[~hr & flagged & ~p2["event_key"].isin(picks)]
    picks += list(fa.sample(min(N_FALSE_ALARM, len(fa)), random_state=int(rng.integers(1_000_000_000)))["event_key"])
    hold = p2[~hr & ~flagged]
    picks += list(hold.sample(min(N_HOLD, len(hold)), random_state=int(rng.integers(1_000_000_000)))["event_key"])
    return list(dict.fromkeys(picks))


def pc_row(ev_row: pd.Series) -> dict:
    """Map an event-table row's last_* columns back to a CDM-like dict for pc.cdm_inputs."""
    return {k[len("last_"):]: ev_row[k] for k in ev_row.index if k.startswith("last_")}


def build(use_llm: bool = True) -> dict:
    rng = np.random.default_rng(config.SEED)
    bundles = {d: models.load_bundle(d) for d in config.CUTOFFS_DAYS}
    tables = {d: features.load_events(d) for d in config.CUTOFFS_DAYS}
    tests = {d: t[t["split"] == "test"].reset_index(drop=True) for d, t in tables.items()}
    preds = {d: models.predict(bundles[d], tests[d]) for d in config.CUTOFFS_DAYS}

    keys = select_events(preds[2], rng)
    _, test_cdm, labels = features.load_kelvins()
    labels = labels.set_index("event_id")
    cache = explain._load_cache()
    out: dict[str, dict] = {}

    for key in keys:
        eid = key.split("_", 1)[1]
        cdms = test_cdm[test_cdm["event_id"] == int(eid)].sort_values("time_to_tca", ascending=False)
        lab = labels.loc[int(eid)]
        entry = {
            "event_id": eid,
            "chaser_type": str(cdms["c_object_type"].iloc[-1]),
            "true_final_risk": _f(lab["true_risk"]),
            "true_final_time_to_tca": _f(lab["time_to_tca"]),
            "cdm_history": [{"time_to_tca": _f(r.time_to_tca), "risk": _f(r.risk),
                             "miss_distance_m": _f(r.miss_distance, 1)} for r in cdms.itertuples()],
            "cutoffs": {},
        }
        for d in config.CUTOFFS_DAYS:
            t, p, b = tests[d], preds[d], bundles[d]
            m = t["event_key"] == key
            if not m.any():
                continue
            i = int(np.flatnonzero(m.to_numpy())[0])
            row, pr = t.iloc[i], p.iloc[i]
            dec = decision.decide(pr["p_high_raw"], pr["risk_p90"], b.tau_raw)
            contrib = b.clf.predict(t.iloc[[i]][b.features], pred_contrib=True)[0, :-1]
            drivers = explain.top_drivers(contrib, row, b.features)

            inp = pc.cdm_inputs(pc_row(row))
            man = None
            if inp is not None:
                man = maneuver.search_maneuvers(inp, time_to_tca_h=float(row["last_time_to_tca"]) * 24, event_id=eid)

            item = {
                "event_id": eid, "source": "historical", "decision": dec,
                "time_to_tca_days": _f(row["last_time_to_tca"], 3),
                "p_high": _f(pr["p_high"]), "p_high_raw": _f(pr["p_high_raw"], 5),
                "risk_p10": _f(pr["risk_p10"], 3), "risk_p50": _f(pr["risk_p50"], 3), "risk_p90": _f(pr["risk_p90"], 3),
                "baseline_risk": _f(pr["naive_pred"], 3), "miss_distance_m": _f(row["last_miss_distance"], 1),
                "chaser_type": str(row["c_object_type"]),
            }
            ctx = {**{k: item[k] for k in ("event_id", "decision", "time_to_tca_days", "p_high", "risk_p10",
                                           "risk_p50", "risk_p90", "miss_distance_m", "chaser_type")},
                   "drivers": [{"label": dr["label"], "shap": round(dr["shap"], 3)} for dr in drivers[:3]],
                   "space_weather": {"F10": _f(row.get("last_F10"), 1), "AP": _f(row.get("last_AP"), 1)},
                   "maneuver": ({k: man["recommended"][k] for k in ("dv_ms", "direction", "burn_lead_h", "post_pc",
                                                                  "propellant_g")}
                                if man and dec == "MANEUVER" and man["recommended"]["dv_ms"] > 0 else None)}
            lines, src = explain.briefing(ctx, f"{eid}@{d}", use_llm=use_llm and d == 2, cache=cache)
            if man is not None and d != 2:
                # full option grid only at the 2-day decision point (keeps the file small); summary elsewhere
                man = {k: man[k] for k in ("target_pc", "target_met", "pre_burn_pc", "recommended", "note")}
            if man is not None:
                for pt in man.get("points", []):
                    pt["post_pc"] = float(f"{pt['post_pc']:.3g}")
                    pt["dv_ms"] = float(f"{pt['dv_ms']:.4g}")
            entry["cutoffs"][str(d)] = {**item, "shap_top": drivers, "briefing": lines, "briefing_source": src,
                                        "maneuver": man}
        out[eid] = entry
        log.info("event %s: cutoffs %s, decision@2=%s", eid, list(entry["cutoffs"]),
                 entry["cutoffs"].get("2", {}).get("decision"))

    explain.save_cache(cache)
    mc = json.loads(config.MODEL_CONFIG_PATH.read_text())
    demo = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "ESA Kelvins test set (held out)",
            "cutoffs": config.CUTOFFS_DAYS,
            "tau": {str(d): mc["cutoffs"][str(d)]["tau"] for d in config.CUTOFFS_DAYS},
            "risk_floor_log10": config.RISK_FLOOR_LOG10,
            "events": out}
    config.DEMO_EVENTS_PATH.write_text(json.dumps(demo, separators=(",", ":")))
    return demo


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="force template briefings")
    args = ap.parse_args(argv)
    demo = build(use_llm=not args.no_llm)
    ev = demo["events"]
    decs = pd.Series([e["cutoffs"]["2"]["decision"] for e in ev.values() if "2" in e["cutoffs"]]).value_counts()
    print(f"wrote {config.DEMO_EVENTS_PATH} with {len(ev)} events; decisions at 2 d: {decs.to_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
