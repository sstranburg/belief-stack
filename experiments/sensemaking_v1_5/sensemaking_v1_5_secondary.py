#!/usr/bin/env python3
"""
Sensemaking v1.5 — Secondary analyses (Phase B, stage 3).

Per pre-registration §11:
  §11.1 Lifecycle revision-prediction (secondary):
    Bucket lifecycle events by event_type; compute forward 5D/20D relative
    return per bucket. Reuses the harness rows.
  §11.2 Warrant coverage / sufficient-data reliability (tertiary):
    Partition primary universe by sufficient_data ∈ {True, False}; compute
    per-bucket / per-horizon metrics per partition. Tests whether insufficient
    rows produce distributions indistinguishable from the Ambiguous baseline.

Reads:
  sensemaking_v1_5/data/sensemaking_v1_5_labeled.parquet
  data/derived/expectation_lifecycle_events.parquet
  data/derived/expectation_entities.parquet      (entity_id → ticker)

Writes:
  sensemaking_v1_5/data/sensemaking_v1_5_secondary_summary.json
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent

LABELED_PATH   = ROOT / "data" / "sensemaking_v1_5_labeled.parquet"
ROWS_PATH      = ROOT / "data" / "sensemaking_v1_5_rows.parquet"
LIFECYCLE_PATH = STORM_ROOT / "data" / "derived" / "expectation_lifecycle_events.parquet"
ENTITIES_PATH  = STORM_ROOT / "data" / "derived" / "expectation_entities.parquet"
OUT_SUMMARY    = ROOT / "data" / "sensemaking_v1_5_secondary_summary.json"

RULES_VERSION = "v0.1"
HORIZONS      = (5, 20)

# §3.2 bucket mapping (same as label.py)
BUCKETS = {
    "Constructive": {"CONFIRMED", "EARLY", "DISAGREEMENT"},
    "Cautious":     {"NEG_CONFIRMATION", "DIVERGENCE"},
    "Ambiguous":    {"MACRO", "PRICE-LED", "UNCLEAR", "REPRICING"},
}
STATE_TO_BUCKET = {s: b for b, states in BUCKETS.items() for s in states}

# §11.1 — pre-registered lifecycle event buckets
# Constructive lifecycle events: reconfirmed, strengthened
# Cautious lifecycle events: contradicted, weakened
# Neutral/non-revision events: born, retired (excluded from primary lifecycle measurement;
# they are field-population events, not revision events).
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
    print("Loading harness + label outputs…")
    rows_all = pd.read_parquet(ROWS_PATH)
    primary  = pd.read_parquet(LABELED_PATH)
    print(f"  rows: {len(rows_all):,}  primary: {len(primary):,}")

    summary: dict = {
        "rules_version":  RULES_VERSION,
        "lifecycle":      {},
        "coverage":       {},
    }

    # ─── §11.1 Lifecycle revision-prediction ─────────────────────────────────
    print("\nLoading lifecycle events…")
    lc = pd.read_parquet(LIFECYCLE_PATH)
    entities = pd.read_parquet(ENTITIES_PATH)
    ticker_lookup = dict(zip(entities["entity_id"], entities["ticker"]))
    lc["ticker"] = lc["entity_id"].map(ticker_lookup)
    lc["date"]   = lc["date"].astype(str)
    lc = lc[lc["event_type"].isin(LIFECYCLE_EVENT_TO_BUCKET)].copy()
    lc["lifecycle_bucket"] = lc["event_type"].map(LIFECYCLE_EVENT_TO_BUCKET)
    print(f"  revision-class events: {len(lc):,}  ({lc['event_type'].value_counts().to_dict()})")

    # Join to harness rows on (date, ticker) to pick up fwd_rel_5d / fwd_rel_20d
    rows_for_join = rows_all[["date", "ticker", "fwd_rel_5d", "fwd_rel_20d", "in_primary"]].copy()
    rows_for_join["date"]   = rows_for_join["date"].astype(str)
    rows_for_join["ticker"] = rows_for_join["ticker"].astype(str)
    lc_joined = lc.merge(rows_for_join, on=["date", "ticker"], how="left")
    matched = lc_joined["fwd_rel_5d"].notna() | lc_joined["fwd_rel_20d"].notna()
    print(f"  events matched to a harness row: {matched.sum():,} / {len(lc_joined):,}")
    print(f"  events with no harness row (off-trading-day or off-universe): {(~matched).sum():,}")

    summary["lifecycle"]["matched_count"]   = int(matched.sum())
    summary["lifecycle"]["unmatched_count"] = int((~matched).sum())

    # Restrict to primary-universe lifecycle events for the headline figure
    lc_primary = lc_joined[lc_joined["in_primary"] == True].copy()

    for h in HORIZONS:
        per_bucket = {}
        for lb in LIFECYCLE_BUCKETS:
            rows = lc_primary[lc_primary["lifecycle_bucket"] == lb]
            per_bucket[lb] = metric_block(rows, h)
        # Baseline = primary Ambiguous rows (same as §8.1 for primary)
        baseline_rows = primary[primary["bucket"] == "Ambiguous"]
        per_bucket["Ambiguous_baseline"] = metric_block(baseline_rows, h)
        # Add deltas
        b_avg = per_bucket["Ambiguous_baseline"]["avg"]
        for k in ("Constructive_revision", "Cautious_revision"):
            if per_bucket[k]["avg"] is not None and b_avg is not None:
                per_bucket[k]["avg_minus_baseline"] = per_bucket[k]["avg"] - b_avg
            else:
                per_bucket[k]["avg_minus_baseline"] = None
        summary["lifecycle"][f"{h}d"] = per_bucket

    # ─── §11.2 Warrant coverage / sufficient-data reliability ────────────────
    print("\nComputing warrant-coverage partitioned metrics…")
    for h in HORIZONS:
        per_partition = {}
        for sd_value in (True, False):
            partition_rows = primary[primary["sufficient_data"] == sd_value]
            per_bucket = {}
            for bucket in BUCKETS:
                b_rows = partition_rows[partition_rows["bucket"] == bucket]
                per_bucket[bucket] = metric_block(b_rows, h)
            # baseline within partition = Ambiguous rows in the same partition
            partition_baseline = per_bucket["Ambiguous"]["avg"]
            for bucket in ("Constructive", "Cautious"):
                if per_bucket[bucket]["avg"] is not None and partition_baseline is not None:
                    per_bucket[bucket]["avg_minus_baseline"] = per_bucket[bucket]["avg"] - partition_baseline
                else:
                    per_bucket[bucket]["avg_minus_baseline"] = None
            per_partition[f"sufficient_data_{sd_value}"] = per_bucket
        summary["coverage"][f"{h}d"] = per_partition

    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote {OUT_SUMMARY}")

    # Console summary
    print()
    print("=" * 72)
    print("SECONDARY §11.1 — LIFECYCLE REVISION-PREDICTION")
    print("=" * 72)
    for h in HORIZONS:
        print(f"\n  {h}D horizon:")
        sec = summary["lifecycle"][f"{h}d"]
        for lb in ("Constructive_revision", "Cautious_revision", "Ambiguous_baseline"):
            r = sec[lb]
            n = r["n"]
            if n == 0:
                print(f"    {lb:24s}  n=0")
                continue
            avg = f"{r['avg']:+.4f}"
            med = f"{r['median']:+.4f}"
            pct = f"{r['pct_pos']:.3f}"
            delta = r.get("avg_minus_baseline")
            d = f"{delta:+.4f}" if delta is not None else "—"
            print(f"    {lb:24s}  n={n:>4}  avg={avg}  med={med}  %pos={pct}  Δ_vs_baseline={d}")

    print()
    print("=" * 72)
    print("TERTIARY §11.2 — WARRANT COVERAGE PARTITION")
    print("=" * 72)
    for h in HORIZONS:
        print(f"\n  {h}D horizon:")
        cov = summary["coverage"][f"{h}d"]
        for partition_key in ("sufficient_data_True", "sufficient_data_False"):
            print(f"    {partition_key}:")
            for bucket in ("Constructive", "Cautious", "Ambiguous"):
                r = cov[partition_key][bucket]
                n = r["n"]
                if n == 0:
                    print(f"      {bucket:14s}  n=0")
                    continue
                avg = f"{r['avg']:+.4f}"
                pct = f"{r['pct_pos']:.3f}"
                delta = r.get("avg_minus_baseline")
                d = f"{delta:+.4f}" if delta is not None else "—"
                print(f"      {bucket:14s}  n={n:>5}  avg={avg}  %pos={pct}  Δ_vs_partition_baseline={d}")


if __name__ == "__main__":
    main()
