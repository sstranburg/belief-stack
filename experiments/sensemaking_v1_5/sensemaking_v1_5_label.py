#!/usr/bin/env python3
"""
Sensemaking v1.5 — Labeler (Phase B, stage 2).

Reads:
  sensemaking_v1_5/data/sensemaking_v1_5_rows.parquet

Writes:
  sensemaking_v1_5/data/sensemaking_v1_5_labeled.parquet
  sensemaking_v1_5/data/sensemaking_v1_5_primary_summary.json

Per pre-registration §3, §6, §9:
  - State → bucket mapping is fixed (no actor-direction flip, no REPRICING flip)
  - Hit / FP / FN per §6 truth table
  - Per-bucket and per-state metrics per §9
  - Baseline = Ambiguous bucket per §8.1

No measurement interpretation. Sensitivity / secondary / report are later stages.
"""

from __future__ import annotations

import json
import pathlib
from collections import defaultdict

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
IN_PATH      = ROOT / "data" / "sensemaking_v1_5_rows.parquet"
OUT_PARQUET  = ROOT / "data" / "sensemaking_v1_5_labeled.parquet"
OUT_SUMMARY  = ROOT / "data" / "sensemaking_v1_5_primary_summary.json"

RULES_VERSION = "v0.1"
HORIZONS      = (5, 20)

# §3.2 — pre-registered bucket mapping
BUCKETS = {
    "Constructive": {"CONFIRMED", "EARLY", "DISAGREEMENT"},
    "Cautious":     {"NEG_CONFIRMATION", "DIVERGENCE"},
    "Ambiguous":    {"MACRO", "PRICE-LED", "UNCLEAR", "REPRICING"},
}
STATE_TO_BUCKET: dict[str, str] = {s: b for b, states in BUCKETS.items() for s in states}


def label_row(bucket: str, fwd_rel: float | None) -> str | None:
    """§6 truth table. None bucket / None fwd_rel → label is None (excluded)."""
    if fwd_rel is None or pd.isna(fwd_rel):
        return None
    if bucket == "Constructive":
        return "Hit" if fwd_rel > 0 else "FP"
    if bucket == "Cautious":
        return "Hit" if fwd_rel < 0 else "FN"
    # Ambiguous: not labeled (no directional prediction made)
    return None


def per_bucket_metrics(df: pd.DataFrame, horizon: int) -> dict[str, dict]:
    """Compute §9 metrics per bucket for a given horizon."""
    fwd_col = f"fwd_rel_{horizon}d"
    label_col = f"label_{horizon}d"

    # Ambiguous baseline distribution (regardless of label, since ambiguous rows aren't labeled)
    ambig_rows = df[(df["bucket"] == "Ambiguous") & df[fwd_col].notna()]
    baseline_mean   = float(ambig_rows[fwd_col].mean())   if len(ambig_rows) else None
    baseline_median = float(ambig_rows[fwd_col].median()) if len(ambig_rows) else None
    baseline_pos    = float((ambig_rows[fwd_col] > 0).mean()) if len(ambig_rows) else None

    out: dict[str, dict] = {}
    for bucket in BUCKETS:
        rows = df[(df["bucket"] == bucket) & df[fwd_col].notna()]
        n = len(rows)
        if bucket in ("Constructive", "Cautious"):
            labeled = rows[rows[label_col].notna()]
            n_labeled = len(labeled)
            hits = int((labeled[label_col] == "Hit").sum())
            fps  = int((labeled[label_col] == "FP").sum())
            fns  = int((labeled[label_col] == "FN").sum())
            denom = hits + (fps if bucket == "Constructive" else fns)
            hit_rate = (hits / denom) if denom > 0 else None
        else:
            n_labeled = 0
            hits = fps = fns = 0
            hit_rate = None

        mean    = float(rows[fwd_col].mean())   if n else None
        median  = float(rows[fwd_col].median()) if n else None
        pct_pos = float((rows[fwd_col] > 0).mean()) if n else None

        out[bucket] = {
            "n":                    n,
            "n_labeled":            n_labeled,
            "hits":                 hits,
            "false_positives":      fps,
            "false_negatives":      fns,
            "hit_rate":             hit_rate,
            "avg_fwd_rel":          mean,
            "median_fwd_rel":       median,
            "pct_positive_fwd_rel": pct_pos,
            "baseline_avg_diff":    (mean - baseline_mean) if (mean is not None and baseline_mean is not None) else None,
            "baseline_median_diff": (median - baseline_median) if (median is not None and baseline_median is not None) else None,
            "baseline_pct_pos_diff":(pct_pos - baseline_pos) if (pct_pos is not None and baseline_pos is not None) else None,
        }
    return out


def per_state_metrics(df: pd.DataFrame, horizon: int) -> dict[str, dict]:
    """Per-state row §9 'state-bucket table'."""
    fwd_col = f"fwd_rel_{horizon}d"
    out = {}
    for state, group in df.groupby("state"):
        rows = group[group[fwd_col].notna()]
        n = len(rows)
        out[state] = {
            "bucket":               STATE_TO_BUCKET.get(state, "Unknown"),
            "n":                    n,
            "avg_fwd_rel":          float(rows[fwd_col].mean())   if n else None,
            "median_fwd_rel":       float(rows[fwd_col].median()) if n else None,
            "pct_positive_fwd_rel": float((rows[fwd_col] > 0).mean()) if n else None,
        }
    return out


def main() -> None:
    print("Loading harness rows…")
    df = pd.read_parquet(IN_PATH)
    print(f"  total rows: {len(df):,}")

    # Restrict to primary universe for the primary measurement
    primary = df[df["in_primary"]].copy()
    print(f"  primary universe rows: {len(primary):,}")

    primary["bucket"] = primary["state"].map(STATE_TO_BUCKET)
    unmapped = primary[primary["bucket"].isna()]
    if not unmapped.empty:
        print(f"  WARN: {len(unmapped)} rows with unmapped states: {sorted(unmapped['state'].unique())}")

    for h in HORIZONS:
        primary[f"label_{h}d"] = [
            label_row(b, v) for b, v in zip(primary["bucket"], primary[f"fwd_rel_{h}d"])
        ]

    OUT_PARQUET.parent.mkdir(exist_ok=True)
    primary.to_parquet(OUT_PARQUET, index=False)
    print(f"  wrote {OUT_PARQUET}")

    # Summary
    summary: dict = {
        "rules_version":  RULES_VERSION,
        "universe":       {"in_primary_rows": len(primary)},
        "per_horizon":    {},
    }
    for h in HORIZONS:
        summary["per_horizon"][f"{h}d"] = {
            "per_bucket": per_bucket_metrics(primary, h),
            "per_state":  per_state_metrics(primary, h),
        }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  wrote {OUT_SUMMARY}")

    # Console summary
    for h in HORIZONS:
        print()
        print("=" * 72)
        print(f"PRIMARY HEAD ({h}D HORIZON)")
        print("=" * 72)
        b = summary["per_horizon"][f"{h}d"]["per_bucket"]
        print(f"  {'bucket':14s}  {'n':>6s}  {'hits':>6s}  {'FP/FN':>6s}  {'hit_rate':>10s}  {'avg_fwd_rel':>12s}  {'median':>10s}  {'%pos':>8s}  {'Δ vs baseline':>12s}")
        for bucket in ("Constructive", "Cautious", "Ambiguous"):
            r = b[bucket]
            fp_fn = r["false_positives"] if bucket == "Constructive" else r["false_negatives"]
            hr = f"{r['hit_rate']:.3f}" if r["hit_rate"] is not None else "n/a"
            avg = f"{r['avg_fwd_rel']:.4f}" if r["avg_fwd_rel"] is not None else "n/a"
            med = f"{r['median_fwd_rel']:.4f}" if r["median_fwd_rel"] is not None else "n/a"
            pct = f"{r['pct_positive_fwd_rel']:.3f}" if r["pct_positive_fwd_rel"] is not None else "n/a"
            bd  = f"{r['baseline_avg_diff']:+.4f}" if r["baseline_avg_diff"] is not None else "n/a"
            print(f"  {bucket:14s}  {r['n']:>6,}  {r['hits']:>6,}  {fp_fn:>6,}  {hr:>10s}  {avg:>12s}  {med:>10s}  {pct:>8s}  {bd:>12s}")

        # Per-state detail
        print()
        print(f"  Per-state ({h}D):")
        ps = summary["per_horizon"][f"{h}d"]["per_state"]
        for state in sorted(ps, key=lambda s: (ps[s]["bucket"], -ps[s]["n"])):
            r = ps[state]
            avg = f"{r['avg_fwd_rel']:.4f}" if r["avg_fwd_rel"] is not None else "n/a"
            med = f"{r['median_fwd_rel']:.4f}" if r["median_fwd_rel"] is not None else "n/a"
            pct = f"{r['pct_positive_fwd_rel']:.3f}" if r["pct_positive_fwd_rel"] is not None else "n/a"
            print(f"    [{r['bucket']:12s}] {state:18s}  n={r['n']:5,}  avg={avg:>10s}  med={med:>10s}  %pos={pct:>6s}")


if __name__ == "__main__":
    main()
