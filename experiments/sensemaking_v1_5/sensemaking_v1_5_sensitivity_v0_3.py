#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.3 — Sensitivity appendix (§12).

§12.1 Lifecycle event-type granularity (reconfirmed vs strengthened, contradicted vs weakened)
§12.2 Sub-window robustness for lifecycle primary (same cut as state §11.2)
§12.3 Experimental tickers included
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
LIFECYCLE_PATH = ROOT / "data" / "sensemaking_v1_5_lifecycle_v0_3.parquet"
ROWS_PATH      = ROOT / "data" / "sensemaking_v1_5_rows.parquet"
LIFECYCLE_RAW_PATH = STORM_ROOT / "data" / "derived" / "expectation_lifecycle_events.parquet"
ENTITIES_PATH      = STORM_ROOT / "data" / "derived" / "expectation_entities.parquet"
OUT_SUMMARY    = ROOT / "data" / "sensemaking_v1_5_sensitivity_summary_v0_3.json"

RULES_VERSION = "v0.3"
HORIZONS      = (5, 20)
CUT_DATE      = "2026-03-01"


def metric_block(rows: pd.DataFrame, fwd_col: str) -> dict:
    rows = rows[rows[fwd_col].notna()]
    n = len(rows)
    if n == 0:
        return {"n": 0}
    return {
        "n":                    n,
        "avg_fwd_rel":          float(rows[fwd_col].mean()),
        "median_fwd_rel":       float(rows[fwd_col].median()),
        "pct_positive_fwd_rel": float((rows[fwd_col] > 0).mean()),
    }


def main() -> None:
    print("Loading lifecycle (v0.3) + rows + raw lifecycle…")
    lc = pd.read_parquet(LIFECYCLE_PATH)
    rows_all = pd.read_parquet(ROWS_PATH)

    summary = {"rules_version": RULES_VERSION}

    # §12.1 event-type granularity
    print("§12.1 lifecycle event-type granularity…")
    per_horizon_granular = {}
    for h in HORIZONS:
        per_event = {}
        for event_type in ("reconfirmed", "strengthened", "contradicted", "weakened"):
            rows = lc[lc["event_type"] == event_type]
            per_event[event_type] = metric_block(rows, f"fwd_rel_{h}d")
        per_horizon_granular[f"{h}d"] = per_event
    summary["s12_1_event_type_granularity"] = per_horizon_granular

    # §12.2 sub-window robustness for lifecycle primary
    print("§12.2 lifecycle sub-window robustness…")
    lc["date"] = pd.to_datetime(lc["date"])
    cut = pd.Timestamp(CUT_DATE)
    lc["sub_window"] = lc["date"].apply(lambda d: "A_early" if d < cut else "B_later")

    per_horizon_subwindow = {}
    for h in HORIZONS:
        per_window = {}
        for w in ("A_early", "B_later"):
            w_rows = lc[lc["sub_window"] == w]
            per_bucket = {}
            for lb in ("Constructive_revision", "Cautious_revision"):
                b_rows = w_rows[w_rows["lifecycle_bucket"] == lb]
                per_bucket[lb] = metric_block(b_rows, f"fwd_rel_{h}d")
            c = per_bucket["Constructive_revision"].get("avg_fwd_rel")
            k = per_bucket["Cautious_revision"].get("avg_fwd_rel")
            per_bucket["internal_gap"] = (c - k) if (c is not None and k is not None) else None
            per_window[w] = per_bucket
        per_horizon_subwindow[f"{h}d"] = per_window
    summary["s12_2_sub_window_robustness"] = per_horizon_subwindow

    # §12.3 experimental-included — rebuild lifecycle with all (including experimental)
    print("§12.3 experimental tickers included…")
    raw_lc = pd.read_parquet(LIFECYCLE_RAW_PATH)
    entities = pd.read_parquet(ENTITIES_PATH)
    ticker_lookup = dict(zip(entities["entity_id"], entities["ticker"]))
    raw_lc["ticker"] = raw_lc["entity_id"].map(ticker_lookup)
    raw_lc["date"] = raw_lc["date"].astype(str)
    LIFECYCLE_EVENT_TO_BUCKET = {
        "reconfirmed": "Constructive_revision",
        "strengthened": "Constructive_revision",
        "contradicted": "Cautious_revision",
        "weakened":     "Cautious_revision",
    }
    raw_lc = raw_lc[raw_lc["event_type"].isin(LIFECYCLE_EVENT_TO_BUCKET)].copy()
    raw_lc["lifecycle_bucket"] = raw_lc["event_type"].map(LIFECYCLE_EVENT_TO_BUCKET)
    rows_for_join = rows_all[["date", "ticker", "fwd_rel_5d", "fwd_rel_20d"]].copy()
    rows_for_join["date"] = rows_for_join["date"].astype(str)
    rows_for_join["ticker"] = rows_for_join["ticker"].astype(str)
    raw_lc_joined = raw_lc.merge(rows_for_join, on=["date", "ticker"], how="left")

    per_horizon_exp = {}
    for h in HORIZONS:
        per_bucket = {}
        for lb in ("Constructive_revision", "Cautious_revision"):
            b_rows = raw_lc_joined[raw_lc_joined["lifecycle_bucket"] == lb]
            per_bucket[lb] = metric_block(b_rows, f"fwd_rel_{h}d")
        c = per_bucket["Constructive_revision"].get("avg_fwd_rel")
        k = per_bucket["Cautious_revision"].get("avg_fwd_rel")
        per_bucket["internal_gap"] = (c - k) if (c is not None and k is not None) else None
        per_horizon_exp[f"{h}d"] = per_bucket
    summary["s12_3_experimental_included"] = per_horizon_exp

    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  wrote {OUT_SUMMARY}")

    # Console
    print()
    print("=" * 72)
    print("§12.1 LIFECYCLE EVENT-TYPE GRANULARITY")
    print("=" * 72)
    for h in HORIZONS:
        print(f"\n  {h}D:")
        for ev in ("reconfirmed", "strengthened", "contradicted", "weakened"):
            r = summary["s12_1_event_type_granularity"][f"{h}d"][ev]
            n = r.get("n", 0)
            if n == 0:
                print(f"    {ev:14s}  n=0")
                continue
            print(f"    {ev:14s}  n={n:>3}  avg={r['avg_fwd_rel']:+.4f}  med={r['median_fwd_rel']:+.4f}  %pos={r['pct_positive_fwd_rel']:.3f}")

    print()
    print("=" * 72)
    print("§12.2 SUB-WINDOW ROBUSTNESS (LIFECYCLE PRIMARY)")
    print("=" * 72)
    for h in HORIZONS:
        print(f"\n  {h}D:")
        for w in ("A_early", "B_later"):
            print(f"    {w}:")
            for lb in ("Constructive_revision", "Cautious_revision"):
                r = summary["s12_2_sub_window_robustness"][f"{h}d"][w][lb]
                n = r.get("n", 0)
                if n == 0:
                    print(f"      {lb:24s}  n=0")
                    continue
                print(f"      {lb:24s}  n={n:>3}  avg={r['avg_fwd_rel']:+.4f}  %pos={r['pct_positive_fwd_rel']:.3f}")
            gap = summary["s12_2_sub_window_robustness"][f"{h}d"][w].get("internal_gap")
            if gap is not None:
                print(f"      INTERNAL GAP: {gap:+.4f}")

    print()
    print("=" * 72)
    print("§12.3 EXPERIMENTAL INCLUDED")
    print("=" * 72)
    for h in HORIZONS:
        print(f"\n  {h}D:")
        for lb in ("Constructive_revision", "Cautious_revision"):
            r = summary["s12_3_experimental_included"][f"{h}d"][lb]
            n = r.get("n", 0)
            if n == 0:
                continue
            print(f"    {lb:24s}  n={n:>3}  avg={r['avg_fwd_rel']:+.4f}  %pos={r['pct_positive_fwd_rel']:.3f}")
        gap = summary["s12_3_experimental_included"][f"{h}d"].get("internal_gap")
        if gap is not None:
            print(f"    INTERNAL GAP: {gap:+.4f}")


if __name__ == "__main__":
    main()
