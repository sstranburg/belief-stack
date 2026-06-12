#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.2 — Secondary analyses.

Per pre-registration §11. Lifecycle event buckets and warrant coverage are
unchanged in protocol; baseline = v0.2 Ambiguous bucket (which now excludes
REPRICING per §3.2).
"""

from __future__ import annotations

import json
import pathlib
from collections import defaultdict

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent

LABELED_PATH   = ROOT / "data" / "sensemaking_v1_5_labeled_v0_2.parquet"
ROWS_PATH      = ROOT / "data" / "sensemaking_v1_5_rows.parquet"
LIFECYCLE_PATH = STORM_ROOT / "data" / "derived" / "expectation_lifecycle_events.parquet"
ENTITIES_PATH  = STORM_ROOT / "data" / "derived" / "expectation_entities.parquet"
OUT_SUMMARY    = ROOT / "data" / "sensemaking_v1_5_secondary_summary_v0_2.json"

RULES_VERSION = "v0.2"
HORIZONS      = (5, 20)

# Lifecycle event bucket mapping (unchanged from v0.1)
LIFECYCLE_BUCKETS = {
    "Constructive_revision": {"reconfirmed", "strengthened"},
    "Cautious_revision":     {"contradicted", "weakened"},
}
LIFECYCLE_EVENT_TO_BUCKET = {e: b for b, evs in LIFECYCLE_BUCKETS.items() for e in evs}


def metric_block(rows: pd.DataFrame, horizon: int) -> dict:
    fwd_col = f"fwd_rel_{horizon}d"
    rows = rows[rows[fwd_col].notna()]
    n = len(rows)
    if n == 0:
        return {"n": 0, "avg": None, "median": None, "pct_pos": None}
    return {
        "n":       n,
        "avg":     float(rows[fwd_col].mean()),
        "median":  float(rows[fwd_col].median()),
        "pct_pos": float((rows[fwd_col] > 0).mean()),
    }


def main() -> None:
    print("Loading v0.2 labeled + raw rows…")
    rows_all = pd.read_parquet(ROWS_PATH)
    primary  = pd.read_parquet(LABELED_PATH)

    summary: dict = {
        "rules_version": RULES_VERSION,
        "lifecycle":     {},
        "coverage":      {},
    }

    # ─── §11.1 Lifecycle ─────────────────────────────────────────────────────
    print("Loading lifecycle + entities…")
    lc = pd.read_parquet(LIFECYCLE_PATH)
    entities = pd.read_parquet(ENTITIES_PATH)
    ticker_lookup = dict(zip(entities["entity_id"], entities["ticker"]))
    lc["ticker"] = lc["entity_id"].map(ticker_lookup)
    lc["date"]   = lc["date"].astype(str)
    lc = lc[lc["event_type"].isin(LIFECYCLE_EVENT_TO_BUCKET)].copy()
    lc["lifecycle_bucket"] = lc["event_type"].map(LIFECYCLE_EVENT_TO_BUCKET)
    print(f"  revision-class events: {len(lc):,}")

    rows_for_join = rows_all[["date", "ticker", "fwd_rel_5d", "fwd_rel_20d", "in_primary"]].copy()
    rows_for_join["date"]   = rows_for_join["date"].astype(str)
    rows_for_join["ticker"] = rows_for_join["ticker"].astype(str)
    lc_joined = lc.merge(rows_for_join, on=["date", "ticker"], how="left")
    matched = lc_joined["fwd_rel_5d"].notna() | lc_joined["fwd_rel_20d"].notna()
    summary["lifecycle"]["matched_count"]   = int(matched.sum())
    summary["lifecycle"]["unmatched_count"] = int((~matched).sum())

    lc_primary = lc_joined[lc_joined["in_primary"] == True].copy()

    # Baseline = v0.2 Ambiguous (smaller after REPRICING removal)
    v02_ambig = primary[primary["bucket"] == "Ambiguous"]

    for h in HORIZONS:
        per_bucket = {}
        for lb in LIFECYCLE_BUCKETS:
            rows = lc_primary[lc_primary["lifecycle_bucket"] == lb]
            per_bucket[lb] = metric_block(rows, h)
        per_bucket["Ambiguous_baseline_v0_2"] = metric_block(v02_ambig, h)
        b_avg = per_bucket["Ambiguous_baseline_v0_2"]["avg"]
        for k in ("Constructive_revision", "Cautious_revision"):
            if per_bucket[k]["avg"] is not None and b_avg is not None:
                per_bucket[k]["avg_minus_baseline"] = per_bucket[k]["avg"] - b_avg
            else:
                per_bucket[k]["avg_minus_baseline"] = None
        summary["lifecycle"][f"{h}d"] = per_bucket

    # ─── §11.2 Warrant coverage ──────────────────────────────────────────────
    for h in HORIZONS:
        per_partition = {}
        for sd_value in (True, False):
            partition_rows = primary[primary["sufficient_data"] == sd_value]
            per_bucket = {}
            for bucket in ("Constructive", "Cautious", "Early_followthrough", "Ambiguous"):
                b_rows = partition_rows[partition_rows["bucket"] == bucket]
                per_bucket[bucket] = metric_block(b_rows, h)
            partition_baseline = per_bucket["Ambiguous"]["avg"]
            for bucket in ("Constructive", "Cautious", "Early_followthrough"):
                if per_bucket[bucket]["avg"] is not None and partition_baseline is not None:
                    per_bucket[bucket]["avg_minus_baseline"] = per_bucket[bucket]["avg"] - partition_baseline
                else:
                    per_bucket[bucket]["avg_minus_baseline"] = None
            per_partition[f"sufficient_data_{sd_value}"] = per_bucket
        summary["coverage"][f"{h}d"] = per_partition

    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote {OUT_SUMMARY}")

    # Console
    print()
    print("=" * 72)
    print("V0.2 SECONDARY §11.1 — LIFECYCLE REVISION (vs v0.2 Ambiguous baseline)")
    print("=" * 72)
    for h in HORIZONS:
        print(f"\n  {h}D horizon:")
        sec = summary["lifecycle"][f"{h}d"]
        for lb in ("Constructive_revision", "Cautious_revision", "Ambiguous_baseline_v0_2"):
            r = sec[lb]
            n = r["n"]
            if n == 0:
                print(f"    {lb:28s}  n=0")
                continue
            avg = f"{r['avg']:+.4f}"
            med = f"{r['median']:+.4f}"
            pct = f"{r['pct_pos']:.3f}"
            d = r.get("avg_minus_baseline")
            dd = f"{d:+.4f}" if d is not None else "—"
            print(f"    {lb:28s}  n={n:>4}  avg={avg}  med={med}  %pos={pct}  Δ_base={dd}")

    print()
    print("=" * 72)
    print("V0.2 TERTIARY §11.2 — WARRANT COVERAGE PARTITION")
    print("=" * 72)
    for h in HORIZONS:
        print(f"\n  {h}D horizon:")
        cov = summary["coverage"][f"{h}d"]
        for partition_key in ("sufficient_data_True", "sufficient_data_False"):
            print(f"    {partition_key}:")
            for bucket in ("Constructive", "Cautious", "Early_followthrough", "Ambiguous"):
                r = cov[partition_key][bucket]
                n = r["n"]
                if n == 0:
                    print(f"      {bucket:22s}  n=0")
                    continue
                avg = f"{r['avg']:+.4f}"
                pct = f"{r['pct_pos']:.3f}"
                d = r.get("avg_minus_baseline")
                dd = f"{d:+.4f}" if d is not None else "—"
                print(f"      {bucket:22s}  n={n:>5}  avg={avg}  %pos={pct}  Δ_partition_base={dd}")


if __name__ == "__main__":
    main()
