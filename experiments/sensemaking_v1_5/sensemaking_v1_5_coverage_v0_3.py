#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.3 — Warrant coverage (§11.3 state + §11.4 lifecycle).
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
STATE_PATH     = ROOT / "data" / "sensemaking_v1_5_state_v0_3.parquet"
LIFECYCLE_PATH = ROOT / "data" / "sensemaking_v1_5_lifecycle_v0_3.parquet"
OUT_SUMMARY    = ROOT / "data" / "sensemaking_v1_5_coverage_summary_v0_3.json"

RULES_VERSION = "v0.3"
HORIZONS      = (5, 20)


def metric_block(rows: pd.DataFrame, horizon: int) -> dict:
    fwd_col = f"fwd_rel_{horizon}d"
    rows = rows[rows[fwd_col].notna()]
    n = len(rows)
    if n == 0:
        return {"n": 0}
    return {
        "n":                    n,
        "avg_fwd_rel":          float(rows[fwd_col].mean()),
        "pct_positive_fwd_rel": float((rows[fwd_col] > 0).mean()),
    }


def main() -> None:
    print("Loading state + lifecycle v0.3 outputs…")
    state = pd.read_parquet(STATE_PATH)
    lc    = pd.read_parquet(LIFECYCLE_PATH)

    summary = {
        "rules_version": RULES_VERSION,
        "state":         {},
        "lifecycle":     {},
    }

    # §11.3 state warrant coverage
    for h in HORIZONS:
        per_partition = {}
        for sd_value in (True, False):
            partition_rows = state[state["sufficient_data"] == sd_value]
            per_bucket = {}
            for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
                b_rows = partition_rows[partition_rows["bucket"] == bucket]
                per_bucket[bucket] = metric_block(b_rows, h)
            base_avg = per_bucket["Ambiguous"].get("avg_fwd_rel")
            for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough"):
                if per_bucket[bucket].get("avg_fwd_rel") is not None and base_avg is not None:
                    per_bucket[bucket]["partition_baseline_diff"] = per_bucket[bucket]["avg_fwd_rel"] - base_avg
                else:
                    per_bucket[bucket]["partition_baseline_diff"] = None
            per_partition[f"sufficient_data_{sd_value}"] = per_bucket
        summary["state"][f"{h}d"] = per_partition

    # §11.4 lifecycle warrant coverage — partition lifecycle events by joined sufficient_data
    for h in HORIZONS:
        per_partition = {}
        for sd_value in (True, False):
            partition_rows = lc[lc["sufficient_data"] == sd_value]
            per_bucket = {}
            for lb in ("Constructive_revision", "Cautious_revision"):
                b_rows = partition_rows[partition_rows["lifecycle_bucket"] == lb]
                per_bucket[lb] = metric_block(b_rows, h)
            # Lifecycle internal gap per partition
            c = per_bucket["Constructive_revision"].get("avg_fwd_rel")
            k = per_bucket["Cautious_revision"].get("avg_fwd_rel")
            per_bucket["internal_gap"] = (c - k) if (c is not None and k is not None) else None
            per_partition[f"sufficient_data_{sd_value}"] = per_bucket
        summary["lifecycle"][f"{h}d"] = per_partition

    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  wrote {OUT_SUMMARY}")

    # Console
    print()
    print("=" * 72)
    print("V0.3 §11.3 STATE WARRANT COVERAGE")
    print("=" * 72)
    for h in HORIZONS:
        print(f"\n  {h}D:")
        cov = summary["state"][f"{h}d"]
        for partition in ("sufficient_data_True", "sufficient_data_False"):
            print(f"    {partition}:")
            for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
                r = cov[partition][bucket]
                n = r["n"]
                if n == 0:
                    print(f"      {bucket:22s}  n=0")
                    continue
                avg = f"{r['avg_fwd_rel']:+.4f}"
                pct = f"{r['pct_positive_fwd_rel']:.3f}"
                d = r.get("partition_baseline_diff")
                dd = f"{d:+.4f}" if d is not None else "—"
                print(f"      {bucket:22s}  n={n:>5,}  avg={avg}  %pos={pct}  Δpart_base={dd}")

    print()
    print("=" * 72)
    print("V0.3 §11.4 LIFECYCLE WARRANT COVERAGE (internal gap focus)")
    print("=" * 72)
    for h in HORIZONS:
        print(f"\n  {h}D:")
        cov = summary["lifecycle"][f"{h}d"]
        for partition in ("sufficient_data_True", "sufficient_data_False"):
            print(f"    {partition}:")
            for lb in ("Constructive_revision", "Cautious_revision"):
                r = cov[partition][lb]
                n = r["n"]
                if n == 0:
                    print(f"      {lb:24s}  n=0")
                    continue
                avg = f"{r['avg_fwd_rel']:+.4f}"
                pct = f"{r['pct_positive_fwd_rel']:.3f}"
                print(f"      {lb:24s}  n={n:>3}  avg={avg}  %pos={pct}")
            gap = cov[partition].get("internal_gap")
            print(f"      INTERNAL GAP: {gap:+.4f}" if gap is not None else "      INTERNAL GAP: n/a")


if __name__ == "__main__":
    main()
